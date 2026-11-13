"""Tests for the update engine, config store and apply helper.

Run from the ``sweep`` folder:

    python -m unittest discover -s tests -v

The suite uses only the standard library (plus the bundled ``psutil`` that
``sweep_app.paths`` imports), and it never touches the real install folder: the
data directory and the app root are redirected into a temporary tree.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from sweep_app import config, paths, updates  # noqa: E402
from sweep_app import updater  # noqa: E402

# Keep the suite hermetic: ``temp_home`` restores the "no feed" placeholder so a
# check never reaches the real official manifest.
PLACEHOLDER_MANIFEST = (
    "https://github.com/OWNER/REPO/releases/latest/download/latest.json"
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
@contextmanager
def temp_home():
    """Point config/quarantine/logs/updates at a fresh temporary folder."""
    with tempfile.TemporaryDirectory(prefix="sweep-test-") as raw:
        home = Path(raw)
        sweep_home = home / "Sweep"
        old = {
            "SWEEP_HOME": paths.SWEEP_HOME,
            "QUARANTINE": paths.QUARANTINE,
            "LOGS": paths.LOGS,
            "CONFIG_FILE": paths.CONFIG_FILE,
            "UPDATES": paths.UPDATES,
        }
        old_local = os.environ.get("LOCALAPPDATA")
        old_default = updates.DEFAULT_MANIFEST_URL
        old_url = os.environ.pop("SWEEP_UPDATE_URL", None)
        updates.DEFAULT_MANIFEST_URL = PLACEHOLDER_MANIFEST
        paths.SWEEP_HOME = sweep_home
        paths.QUARANTINE = sweep_home / "quarantine"
        paths.LOGS = sweep_home / "logs"
        paths.CONFIG_FILE = sweep_home / "config.json"
        paths.UPDATES = sweep_home / "updates"
        sweep_home.mkdir(parents=True, exist_ok=True)
        # The standalone updater helper deliberately reads LOCALAPPDATA itself.
        os.environ["LOCALAPPDATA"] = str(home)
        try:
            yield sweep_home
        finally:
            for name, value in old.items():
                setattr(paths, name, value)
            updates.DEFAULT_MANIFEST_URL = old_default
            if old_url is not None:
                os.environ["SWEEP_UPDATE_URL"] = old_url
            if old_local is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = old_local


@contextmanager
def served(routes: dict[str, tuple[int, bytes, str]]):
    """Serve a tiny fixed map of path -> (status, body, content-type)."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401, ANN002
            return

        def do_GET(self):  # noqa: N802
            status, body, ctype = routes.get(self.path, (404, b"not found", "text/plain"))
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def make_zip(version: str = "9.9.9", extra: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "main.py", '"""fake launcher"""\nprint("hello")\n'
        )
        archive.writestr(
            "sweep_app/__init__.py", f'__version__ = "{version}"\n'
        )
        archive.writestr("sweep_app/engine.py", "VALUE = 1\n")
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def release_for(base: str, version: str = "9.9.9", payload: bytes | None = None) -> updates.Release:
    payload = payload if payload is not None else make_zip(version)
    return updates.Release(
        version=version,
        url=f"{base}/Sweep-{version}.zip",
        sha256=hashlib.sha256(payload).hexdigest(),
        size=len(payload),
        notes="notes",
    )


# --------------------------------------------------------------------------- #
# versions
# --------------------------------------------------------------------------- #
class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updates.parse_version("1.2.3"), (1, 2, 3, 0))
        self.assertEqual(updates.parse_version("v2"), (2, 0, 0, 0))
        self.assertEqual(updates.parse_version("1.2.3.4"), (1, 2, 3, 4))

    def test_bad(self):
        with self.assertRaises(ValueError):
            updates.parse_version("not-a-version")

    def test_compare(self):
        self.assertGreater(updates.compare_versions("1.2.0", "1.1.9"), 0)
        self.assertLess(updates.compare_versions("1.1.0", "1.10.0"), 0)
        self.assertEqual(updates.compare_versions("v1.2", "1.2.0"), 0)
        self.assertLess(updates.compare_versions("1.2.0-beta.1", "1.2.0"), 0)
        self.assertGreater(updates.compare_versions("1.2.0", "1.2.0-rc.2"), 0)
        self.assertLess(updates.compare_versions("1.2.0-beta.2", "1.2.0-beta.10"), 0)

    def test_is_newer(self):
        self.assertTrue(updates.is_newer("1.1.0", "1.0.0"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("0.9.0", "1.0.0"))


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
class ConfigTests(unittest.TestCase):
    def test_defaults_and_merge(self):
        with temp_home():
            data = config.load()
            self.assertEqual(data["mode"], "quarantine")
            self.assertTrue(data["updates"]["enabled"])
            paths.CONFIG_FILE.write_text(
                json.dumps({"mode": "permanent", "unknown": {"keep": 1}}), encoding="utf-8"
            )
            data = config.load()
            self.assertEqual(data["mode"], "permanent")
            self.assertEqual(data["unknown"], {"keep": 1})
            self.assertEqual(data["updates"]["channel"], "stable")

    def test_corrupt_file_falls_back(self):
        with temp_home():
            paths.CONFIG_FILE.write_text("{not json", encoding="utf-8")
            self.assertEqual(config.load()["mode"], "quarantine")

    def test_bom_from_notepad_is_tolerated(self):
        with temp_home():
            paths.CONFIG_FILE.write_text(
                json.dumps({"mode": "permanent"}), encoding="utf-8-sig"
            )
            self.assertEqual(config.load()["mode"], "permanent")

    def test_set_updates_validates_and_persists(self):
        with temp_home():
            saved = config.set_updates({"enabled": False, "channel": "beta"})
            self.assertFalse(saved["enabled"])
            self.assertEqual(saved["channel"], "beta")
            self.assertEqual(config.updates()["channel"], "beta")
            with self.assertRaises(ValueError):
                config.set_updates({"channel": "nightly"})
            with self.assertRaises(ValueError):
                config.set_updates({"manifest_url": "ftp://example.com/x.json"})

    def test_record_check(self):
        with temp_home():
            config.record_check({"checked_at": 123.0, "latest": "2.0.0", "status": "available"})
            prefs = config.updates()
            self.assertEqual(prefs["last_check"], 123.0)
            self.assertEqual(prefs["last_version"], "2.0.0")
            self.assertEqual(prefs["last_status"], "available")


# --------------------------------------------------------------------------- #
# manifest parsing
# --------------------------------------------------------------------------- #
class ManifestTests(unittest.TestCase):
    def test_native(self):
        release = updates.parse_release(
            {
                "version": "2.0.0",
                "url": "https://example.com/Sweep-2.0.0.zip",
                "sha256": "a" * 64,
                "size": 10,
                "notes": "new",
                "channel": "beta",
            }
        )
        self.assertEqual(release.version, "2.0.0")
        self.assertEqual(release.channel, "beta")
        self.assertEqual(release.sha256, "a" * 64)

    def test_github_shape(self):
        release = updates.parse_release(
            {
                "tag_name": "v3.1.0",
                "body": "changelog",
                "prerelease": False,
                "html_url": "https://github.com/o/r/releases/tag/v3.1.0",
                "assets": [
                    {"name": "checksums.txt", "browser_download_url": "https://x/y.txt"},
                    {
                        "name": "Sweep-3.1.0.zip",
                        "browser_download_url": "https://x/Sweep-3.1.0.zip",
                        "size": 42,
                        "digest": "sha256:" + "b" * 64,
                    },
                ],
            }
        )
        self.assertEqual(release.version, "3.1.0")
        self.assertEqual(release.sha256, "b" * 64)
        self.assertEqual(release.size, 42)

    def test_missing_fields(self):
        with self.assertRaises(updates.UpdateError):
            updates.parse_release({})
        with self.assertRaises(updates.UpdateError):
            updates.parse_release({"version": "1.0.0"})
        with self.assertRaises(updates.UpdateError):
            updates.parse_release({"version": "1.0.0", "url": "https://x/y.zip", "sha256": "bad"})

    def test_insecure_url_refused(self):
        with self.assertRaises(updates.UpdateError) as caught:
            updates.fetch_manifest("http://example.com/latest.json")
        self.assertEqual(caught.exception.code, "insecure_source")


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
class SourceTests(unittest.TestCase):
    def test_official_feed_is_the_default(self):
        # No ``_build_info.py`` in a checkout: the copy still knows where to ask.
        self.assertEqual(updates.DEFAULT_MANIFEST_URL, updates.OFFICIAL_MANIFEST_URL)
        self.assertIn("Anassh780/Clean-up-tool", updates.DEFAULT_MANIFEST_URL)


class CheckTests(unittest.TestCase):
    def test_unconfigured(self):
        with temp_home():
            result = updates.check(force=True, manifest_url="")
            self.assertEqual(result.status, updates.STATUS_UNCONFIGURED)

    def test_disabled(self):
        with temp_home():
            config.set_updates({"enabled": False})
            result = updates.check(force=True, manifest_url="https://example.com/latest.json")
            self.assertEqual(result.status, updates.STATUS_DISABLED)

    def test_available(self):
        with temp_home():
            manifest = {
                "version": "99.0.0",
                "url": "https://example.com/Sweep-99.0.0.zip",
                "sha256": "c" * 64,
                "notes": "big release",
            }
            body = json.dumps(manifest).encode()
            with served({"/latest.json": (200, body, "application/json")}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_AVAILABLE)
            self.assertEqual(result.latest, "99.0.0")
            self.assertEqual(result.release.notes, "big release")
            self.assertTrue(result.checked_at)
            # The hint must be the whole sentence, not just its first half.
            self.assertIn("quarantine, logs and settings", result.hint)

    def test_up_to_date(self):
        with temp_home():
            body = json.dumps(
                {
                    "version": "0.0.1",
                    "url": "https://example.com/Sweep-0.0.1.zip",
                    "sha256": "d" * 64,
                }
            ).encode()
            with served({"/latest.json": (200, body, "application/json")}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_UP_TO_DATE)

    def test_beta_is_not_offered_on_stable(self):
        with temp_home():
            body = json.dumps(
                {
                    "version": "99.0.0-beta.1",
                    "url": "https://example.com/x.zip",
                    "sha256": "e" * 64,
                    "channel": "beta",
                }
            ).encode()
            with served({"/latest.json": (200, body, "application/json")}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_UP_TO_DATE)
            self.assertIn("beta", result.message)

            config.set_updates({"channel": "beta"})
            with served({"/latest.json": (200, body, "application/json")}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_AVAILABLE)

    def test_skipped(self):
        with temp_home():
            config.set_updates({"skipped": "99.0.0"})
            body = json.dumps(
                {"version": "99.0.0", "url": "https://e/x.zip", "sha256": "f" * 64}
            ).encode()
            with served({"/latest.json": (200, body, "application/json")}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_SKIPPED)

    def test_http_error_is_a_result_not_an_exception(self):
        with temp_home():
            with served({}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_ERROR)
            self.assertIn("404", result.message)
            self.assertTrue(result.hint)

    def test_bad_json(self):
        with temp_home():
            with served({"/latest.json": (200, b"<html>nope</html>", "text/html")}) as base:
                result = updates.check(force=True, manifest_url=f"{base}/latest.json")
            self.assertEqual(result.status, updates.STATUS_ERROR)

    def test_cache_is_used_without_force(self):
        with temp_home():
            body = json.dumps(
                {"version": "99.0.0", "url": "https://e/x.zip", "sha256": "1" * 64}
            ).encode()
            with served({"/latest.json": (200, body, "application/json")}) as base:
                url = f"{base}/latest.json"
                first = updates.check(force=True, manifest_url=url)
                self.assertFalse(first.cached)
                # The server is gone now; a cached answer must still come back.
            second = updates.check(manifest_url=url)
            self.assertTrue(second.cached)
            self.assertEqual(second.latest, "99.0.0")


class RedirectSafetyTests(unittest.TestCase):
    """An https manifest must not be reachable through a plain-http redirect."""

    def test_redirect_to_plain_http_is_refused(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: ANN002 - quiet test output
                return

            def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract
                self.send_response(302)
                self.send_header("Location", "http://192.0.2.1/latest.json")
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with temp_home():
                with self.assertRaises(updates.UpdateError) as caught:
                    updates.fetch_manifest(
                        f"http://127.0.0.1:{server.server_address[1]}/latest.json"
                    )
            self.assertEqual(caught.exception.code, "insecure_source")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# download + stage
# --------------------------------------------------------------------------- #
class DownloadStageTests(unittest.TestCase):
    def test_download_and_stage(self):
        payload = make_zip("9.9.9")
        with temp_home():
            with served(
                {"/Sweep-9.9.9.zip": (200, payload, "application/zip")}
            ) as base:
                release = release_for(base, payload=payload)
                progress = []
                path = updates.download(release, progress=lambda d, t: progress.append((d, t)))
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(progress[-1][0], len(payload))
            root = updates.stage(path, release)
            self.assertTrue((root / "main.py").is_file())
            self.assertIn("9.9.9", (root / "sweep_app" / "__init__.py").read_text())

    def test_checksum_mismatch(self):
        payload = make_zip("9.9.9")
        with temp_home():
            with served({"/Sweep-9.9.9.zip": (200, payload, "application/zip")}) as base:
                release = release_for(base, payload=payload)
                release = updates.Release(
                    version=release.version,
                    url=release.url,
                    sha256="0" * 64,
                    size=release.size,
                )
                with self.assertRaises(updates.UpdateError) as caught:
                    updates.download(release)
            self.assertEqual(caught.exception.code, "checksum_mismatch")
            leftovers = list(paths.UPDATES.rglob("*.part"))
            self.assertEqual(leftovers, [])

    def test_missing_checksum_refused(self):
        with temp_home():
            release = updates.Release(version="9.9.9", url="https://example.com/x.zip")
            with self.assertRaises(updates.UpdateError) as caught:
                updates.download(release)
            self.assertEqual(caught.exception.code, "missing_checksum")

    def test_zip_slip_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../escape.txt", "nope")
            archive.writestr("main.py", "x")
        payload = buffer.getvalue()
        with temp_home():
            with served({"/Sweep-9.9.9.zip": (200, payload, "application/zip")}) as base:
                release = release_for(base, payload=payload)
                path = updates.download(release)
            with self.assertRaises(updates.UpdateError) as caught:
                updates.stage(path, release)
            self.assertEqual(caught.exception.code, "unsafe_archive")

    def test_version_mismatch_refused(self):
        payload = make_zip("1.0.0")
        with temp_home():
            with served({"/Sweep-9.9.9.zip": (200, payload, "application/zip")}) as base:
                release = release_for(base, version="9.9.9", payload=payload)
                path = updates.download(release)
            with self.assertRaises(updates.UpdateError) as caught:
                updates.stage(path, release)
            self.assertEqual(caught.exception.code, "version_mismatch")

    def test_not_sweep(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("readme.txt", "hello")
        payload = buffer.getvalue()
        with temp_home():
            with served({"/Sweep-9.9.9.zip": (200, payload, "application/zip")}) as base:
                release = release_for(base, payload=payload)
                path = updates.download(release)
            with self.assertRaises(updates.UpdateError) as caught:
                updates.stage(path, release)
            self.assertEqual(caught.exception.code, "archive_invalid")


# --------------------------------------------------------------------------- #
# apply plan
# --------------------------------------------------------------------------- #
class ApplyTests(unittest.TestCase):
    def test_apply_writes_plan_and_spawns_helper(self):
        with temp_home() as home:
            install = home / "install"
            (install / "sweep_app").mkdir(parents=True)
            (install / "main.py").write_text("x", encoding="utf-8")
            (install / "sweep_app" / "__init__.py").write_text("__version__='1.0.0'")
            staged = home / "staged"
            staged.mkdir()

            captured = {}

            class FakePopen:
                def __init__(self, cmd, **kwargs):
                    captured["cmd"] = cmd
                    captured["kwargs"] = kwargs

            old_root = updates.app_root
            old_popen = updates.subprocess.Popen
            updates.app_root = lambda: install
            updates.subprocess.Popen = FakePopen
            try:
                release = updates.Release(version="9.9.9", url="https://e/x.zip", sha256="0" * 64)
                plan_path = updates.apply(staged, release, relaunch=["python", "main.py"])
            finally:
                updates.app_root = old_root
                updates.subprocess.Popen = old_popen

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["version"], "9.9.9")
            self.assertEqual(plan["app_root"], str(install))
            self.assertEqual(plan["relaunch"], ["python", "main.py"])
            self.assertEqual(plan["pid"], os.getpid())
            self.assertIn("updater.py", captured["cmd"][1])
            self.assertEqual(captured["cmd"][2], "--plan")

    def test_apply_refuses_read_only_install(self):
        with temp_home() as home:
            missing = home / "nope"
            old_root = updates.app_root
            updates.app_root = lambda: missing
            try:
                release = updates.Release(version="9.9.9", url="https://e/x.zip", sha256="0" * 64)
                with self.assertRaises(updates.UpdateError) as caught:
                    updates.apply(home / "staged", release)
            finally:
                updates.app_root = old_root
            self.assertEqual(caught.exception.code, "install_not_writable")


# --------------------------------------------------------------------------- #
# helper: apply + restore on a temporary install
# --------------------------------------------------------------------------- #
class HelperTests(unittest.TestCase):
    def _plan(self, home: Path, version: str = "2.0.0") -> tuple[Path, Path]:
        install = home / "install"
        (install / "sweep_app").mkdir(parents=True)
        (install / "main.py").write_text("old launcher", encoding="utf-8")
        (install / "sweep_app" / "__init__.py").write_text(
            '__version__ = "1.0.0"\n', encoding="utf-8"
        )
        (install / "sweep_app" / "stale.py").write_text("OLD = True\n", encoding="utf-8")
        (install / "sweep_app" / "__pycache__").mkdir()
        (install / "sweep_app" / "__pycache__" / "x.pyc").write_bytes(b"old")

        staged = home / "staged"
        (staged / "sweep_app").mkdir(parents=True)
        (staged / "main.py").write_text("new launcher", encoding="utf-8")
        (staged / "sweep_app" / "__init__.py").write_text(
            f'__version__ = "{version}"\n', encoding="utf-8"
        )
        (staged / "sweep_app" / "engine.py").write_text("NEW = True\n", encoding="utf-8")

        backup = home / "backup"
        plan_path = home / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "version": version,
                    "from_version": "1.0.0",
                    "app_root": str(install),
                    "staged": str(staged),
                    "backup": str(backup),
                    "keep_backup": True,
                    "relaunch": [],
                    "pid": 0,
                }
            ),
            encoding="utf-8",
        )
        return plan_path, install

    def test_apply_plan_replaces_files_and_keeps_backup(self):
        with temp_home() as home:
            plan_path, install = self._plan(home)
            log = updater.Log(home / "helper.log")
            try:
                code = updater.apply_plan(plan_path, log)
            finally:
                log.close()
            self.assertEqual(code, 0)
            self.assertEqual((install / "main.py").read_text(encoding="utf-8"), "new launcher")
            self.assertIn('"2.0.0"', (install / "sweep_app" / "__init__.py").read_text())
            self.assertTrue((install / "sweep_app" / "engine.py").is_file())
            # Stale module moved to the backup, pycache removed.
            self.assertFalse((install / "sweep_app" / "stale.py").exists())
            self.assertTrue((home / "backup" / "removed" / "sweep_app" / "stale.py").is_file())
            self.assertFalse((install / "sweep_app" / "__pycache__").exists())
            # The old files are recoverable.
            self.assertEqual(
                (home / "backup" / "sweep_app" / "__init__.py").read_text(encoding="utf-8"),
                '__version__ = "1.0.0"\n',
            )
            status = json.loads(
                (paths.UPDATES / "update-status.json").read_text(encoding="utf-8")
            )
            self.assertTrue(status["ok"])
            self.assertEqual(status["version"], "2.0.0")

    def test_restore_brings_the_old_tree_back(self):
        with temp_home() as home:
            plan_path, install = self._plan(home)
            log = updater.Log(home / "helper.log")
            try:
                updater.apply_plan(plan_path, log)
                code = updater.restore(install, home / "backup", log)
            finally:
                log.close()
            self.assertEqual(code, 0)
            self.assertEqual((install / "main.py").read_text(encoding="utf-8"), "old launcher")
            self.assertIn('"1.0.0"', (install / "sweep_app" / "__init__.py").read_text())
            self.assertTrue((install / "sweep_app" / "stale.py").is_file())
            self.assertFalse((install / "sweep_app" / "engine.py").exists())

    def test_wait_for_exit(self):
        self.assertTrue(updater.wait_for_exit(0, timeout=0.1))
        self.assertFalse(updater.wait_for_exit(os.getpid(), timeout=0.2))


class HelperRuntimeTests(unittest.TestCase):
    """A portable build's own python.exe must not be locked during an update."""

    def test_bundled_interpreter_is_copied_outside_the_app(self):
        with temp_home() as home:
            app = home / "app"
            runtime = app / "runtime"
            runtime.mkdir(parents=True)
            (runtime / "python.exe").write_bytes(b"fake exe")
            (runtime / "python312.zip").write_bytes(b"fake stdlib")
            (runtime / "python312.dll").write_bytes(b"fake dll")

            old_root = updates.app_root
            old_updates = updates.updates_dir
            old_exe = sys.executable
            updates.app_root = lambda: app
            updates.updates_dir = lambda: home / "updates"
            sys.executable = str(runtime / "python.exe")
            try:
                helper = Path(updates._helper_interpreter())
            finally:
                updates.app_root = old_root
                updates.updates_dir = old_updates
                sys.executable = old_exe

            self.assertNotEqual(helper.parent, runtime)
            self.assertNotIn(str(app), str(helper))
            self.assertTrue((helper.parent / "python.exe").is_file())
            pth = (helper.parent / "python312._pth").read_text(encoding="ascii")
            # The copied stdlib zip is referenced relatively, not from the app.
            self.assertIn("python312.zip", pth.splitlines())
            self.assertNotIn(str(runtime), pth)

    def test_system_interpreter_is_used_as_is(self):
        with temp_home() as home:
            old_root = updates.app_root
            updates.app_root = lambda: home / "app"
            try:
                self.assertEqual(Path(updates._helper_interpreter()), Path(sys.executable).resolve())
            finally:
                updates.app_root = old_root


# --------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------- #
class StateTests(unittest.TestCase):
    def test_state_shape(self):
        with temp_home():
            data = updates.state()
            for key in (
                "current",
                "install",
                "enabled",
                "channel",
                "configured",
                "last_result",
                "can_apply",
            ):
                self.assertIn(key, data)
            self.assertEqual(data["current"], updates.__version__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
