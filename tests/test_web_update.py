"""Integration tests for the web update API.

The real ``ThreadingHTTPServer`` is started in-process against a temporary data
folder, and a second local server plays the release manifest/archive host.
Every test is hermetic: no internet, no writes to the checkout that is running
the tests, and no dependence on the developer's ``config.json``.

The one-shot startup update check is disabled for these tests. It is a separate
background concern whose thread would outlive the temporary folder; the
endpoints below are still exercised through real HTTP requests.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from update_support import make_zip, served, temp_home  # noqa: E402

from sweep_app import __version__, updates  # noqa: E402
from sweep_app.web import server as web_server  # noqa: E402
from sweep_app.web import service  # noqa: E402


def manifest_for(base: str, version: str, payload: bytes) -> dict:
    """A native-schema manifest that points at ``payload`` on the fake host."""
    return {
        "version": version,
        "url": f"{base}/Sweep-{version}.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "notes": "integration test release",
        "channel": "stable",
    }


class WebUpdateApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_ctx = temp_home()
        self.home = self._home_ctx.__enter__()
        self.addCleanup(self._home_ctx.__exit__, None, None, None)

        # A fake install tree: state()/writable_install() must never probe the
        # real checkout while the tests run.
        self.install = self.home / "install"
        (self.install / "sweep_app").mkdir(parents=True)
        (self.install / "main.py").write_text("launcher", encoding="utf-8")
        (self.install / "sweep_app" / "__init__.py").write_text(
            f'__version__ = "{__version__}"\n', encoding="utf-8"
        )
        old_app_root = updates.app_root
        updates.app_root = lambda: self.install
        self.addCleanup(setattr, updates, "app_root", old_app_root)

        self._clear_pending()
        self.addCleanup(self._clear_pending)

        # Do not let the startup check thread read config after teardown.
        self._started_before = web_server._UPDATE_CHECK_STARTED
        web_server._UPDATE_CHECK_STARTED = True
        self.addCleanup(
            setattr, web_server, "_UPDATE_CHECK_STARTED", self._started_before
        )

        self.httpd, self.token, _reported = web_server.create_server("127.0.0.1", 0)
        # create_server() reports the requested port, which is 0 here; the
        # kernel picked the real one, so read it from the bound socket.
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            kwargs={"poll_interval": 0.02},
            name="sweep-test-web",
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._stop_server)

    # -- lifecycle ------------------------------------------------------ #
    @staticmethod
    def _clear_pending() -> None:
        with service.PENDING_LOCK:
            service.PENDING.clear()
            service.PENDING_RELEASES.clear()

    def _stop_server(self) -> None:
        try:
            self.httpd.shutdown()
        finally:
            self.thread.join(timeout=5)
            self.httpd.server_close()
            # setup_logging() opens a FileHandler inside the temporary folder;
            # close it before TemporaryDirectory tries to remove the tree on
            # Windows, where an open file cannot be deleted.
            for handler in list(web_server.log.handlers):
                web_server.log.removeHandler(handler)
                handler.close()

    def serve(self, routes: dict[str, tuple[int, bytes, str]]) -> str:
        ctx = served(routes)
        base = ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)
        return base

    # -- HTTP plumbing -------------------------------------------------- #
    def api(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        token: bool = True,
        origin: str | None = None,
    ) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if token:
            request.add_header("X-Sweep-Token", self.token)
        if origin is not None:
            request.add_header("Origin", origin)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return response.status, json.loads(raw.decode("utf-8")) if raw else {}
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, json.loads(raw.decode("utf-8")) if raw else {}

    def wait_job(self, job_id: str, timeout: float = 15.0) -> dict:
        deadline = time.time() + timeout
        last: dict | None = None
        while time.time() < deadline:
            status, body = self.api("GET", f"/api/jobs/{job_id}")
            self.assertEqual(status, 200)
            last = body["data"]
            if last["status"] in ("done", "error", "cancelled"):
                return last
            time.sleep(0.02)
        self.fail(f"job {job_id} did not finish within {timeout}s; last={last!r}")

    # -- GET /api/update ------------------------------------------------ #
    def test_get_update_shape(self):
        status, body = self.api("GET", "/api/update")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        data = body["data"]
        self.assertIn("state", data)
        self.assertIn("result", data)
        self.assertIsNone(data["result"])

        state = data["state"]
        for key in (
            "current",
            "install",
            "app_root",
            "updates_dir",
            "platform",
            "enabled",
            "channel",
            "check_interval_hours",
            "manifest_url",
            "configured",
            "skipped",
            "last_check",
            "last_result",
            "can_apply",
            "backups",
        ):
            self.assertIn(key, state)
        self.assertEqual(state["current"], __version__)
        self.assertEqual(state["install"], "source")
        self.assertEqual(state["app_root"], str(self.install))
        self.assertEqual(state["updates_dir"], str(self.home / "updates"))
        self.assertTrue(state["enabled"])
        self.assertEqual(state["channel"], "stable")
        self.assertFalse(state["configured"])
        self.assertTrue(state["can_apply"])
        self.assertEqual(state["backups"], [])

    # -- POST /api/update/check ----------------------------------------- #
    def test_check_available(self):
        # The manifest body contains the fake host's own port, so start the
        # server first and fill the route map afterwards. The handler reads the
        # same dict at request time.
        routes: dict[str, tuple[int, bytes, str]] = {}
        base = self.serve(routes)
        payload = make_zip("99.0.0")
        release = manifest_for(base, "99.0.0", payload)
        routes["/latest.json"] = (
            200,
            json.dumps(release).encode(),
            "application/json",
        )
        routes["/Sweep-99.0.0.zip"] = (200, payload, "application/zip")

        status, body = self.api(
            "POST", "/api/update/settings", {"manifest_url": f"{base}/latest.json"}
        )
        self.assertEqual(status, 200, body)
        self.assertTrue(body["data"]["configured"])

        status, body = self.api("POST", "/api/update/check", {"force": True})
        self.assertEqual(status, 200, body)
        data = body["data"]
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["current"], __version__)
        self.assertEqual(data["latest"], "99.0.0")
        self.assertIsNotNone(data["release"])
        self.assertEqual(data["release"]["url"], f"{base}/Sweep-99.0.0.zip")
        self.assertEqual(data["release"]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertTrue(data["checked_at"])
        self.assertFalse(data["cached"])

    def test_check_up_to_date(self):
        routes: dict[str, tuple[int, bytes, str]] = {}
        base = self.serve(routes)
        payload = make_zip("0.0.1")
        release = manifest_for(base, "0.0.1", payload)
        routes["/latest.json"] = (
            200,
            json.dumps(release).encode(),
            "application/json",
        )
        self.api(
            "POST", "/api/update/settings", {"manifest_url": f"{base}/latest.json"}
        )
        status, body = self.api("POST", "/api/update/check", {"force": True})
        self.assertEqual(status, 200, body)
        data = body["data"]
        self.assertEqual(data["status"], "up_to_date")
        self.assertEqual(data["latest"], "0.0.1")
        self.assertEqual(data["release"]["version"], "0.0.1")

    def test_check_http_404_is_an_error_result(self):
        base = self.serve({})  # every path is a 404
        self.api(
            "POST", "/api/update/settings", {"manifest_url": f"{base}/missing.json"}
        )
        status, body = self.api("POST", "/api/update/check", {"force": True})
        self.assertEqual(status, 200, body)
        data = body["data"]
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["details"]["status"], 404)
        self.assertIn("404", data["message"])
        self.assertTrue(data["reason"])
        self.assertTrue(data["hint"])

    # -- POST /api/update/settings -------------------------------------- #
    def test_settings_validation_rejects_bad_values(self):
        status, body = self.api(
            "POST", "/api/update/settings", {"channel": "nightly"}
        )
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertEqual(body["error"]["details"]["field"], "updates")

        status, body = self.api(
            "POST",
            "/api/update/settings",
            {"manifest_url": "ftp://example.com/latest.json"},
        )
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "invalid_request")

        # Nothing invalid reached config.json.
        self.assertFalse((self.home / "config.json").exists())
        status, body = self.api("GET", "/api/update")
        self.assertEqual(status, 200)
        self.assertEqual(body["data"]["state"]["channel"], "stable")

    # -- auth / CSRF ---------------------------------------------------- #
    def test_missing_token_is_401(self):
        status, body = self.api("GET", "/api/update", token=False)
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "unauthorized")

    def test_foreign_origin_is_403(self):
        status, body = self.api(
            "GET", "/api/update", origin="https://evil.example"
        )
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "forbidden_origin")

    # -- download ------------------------------------------------------- #
    def test_download_starts_job_and_stages(self):
        routes: dict[str, tuple[int, bytes, str]] = {}
        base = self.serve(routes)
        payload = make_zip("99.0.0")
        release = manifest_for(base, "99.0.0", payload)
        routes["/latest.json"] = (
            200,
            json.dumps(release).encode(),
            "application/json",
        )
        routes["/Sweep-99.0.0.zip"] = (200, payload, "application/zip")
        self.api(
            "POST", "/api/update/settings", {"manifest_url": f"{base}/latest.json"}
        )
        status, body = self.api("POST", "/api/update/check", {"force": True})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["data"]["status"], "available")

        status, body = self.api(
            "POST", "/api/update/download", {"version": "99.0.0"}
        )
        self.assertEqual(status, 200, body)
        job = body["data"]
        self.assertEqual(job["kind"], "update-download")
        self.assertIn(job["status"], ("queued", "running", "done"))
        self.assertTrue(job["id"])

        finished = self.wait_job(job["id"])
        self.assertEqual(finished["status"], "done", finished.get("error"))
        result = finished["result"]
        self.assertEqual(result["version"], "99.0.0")
        self.assertTrue(result["staged"])
        staged = Path(result["staged"])
        self.assertTrue(staged.is_dir())
        self.assertTrue((staged / "main.py").is_file())
        self.assertIn(
            "99.0.0", (staged / "sweep_app" / "__init__.py").read_text(encoding="utf-8")
        )
        # The download and its checksum-verified archive live under the temp
        # updates folder, never in the real one.
        self.assertEqual(staged.parent.parent, self.home / "updates")

    # -- apply refusals ------------------------------------------------- #
    def test_apply_requires_confirmation(self):
        status, body = self.api(
            "POST", "/api/update/apply", {"version": "99.0.0"}
        )
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "confirmation_required")

    def test_apply_without_pending_is_refused(self):
        # No download ran in this test, so PENDING is empty and apply must not
        # spawn a helper or write an apply plan.
        status, body = self.api(
            "POST", "/api/update/apply", {"confirm": "update"}
        )
        self.assertEqual(status, 409)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"]["code"], "no_pending_update")
        self.assertEqual(list((self.home / "updates").glob("apply-*.json")), [])
        self.assertEqual(
            (self.install / "main.py").read_text(encoding="utf-8"), "launcher"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
