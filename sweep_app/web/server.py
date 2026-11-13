"""Local HTTP server for the Sweep web interface.

Design notes
------------
* Binds to 127.0.0.1 by default: this is a local tool, not a hosted service.
* Every API call needs the per-process token embedded in the page, and the
  ``Origin``/``Host`` headers must be local. That blocks drive-by requests from
  other sites (CSRF) and DNS-rebinding tricks.
* The UI never invents paths: destructive endpoints only accept ids or paths
  that the engine itself produced in the current session.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import re
import secrets
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from .. import __version__, paths, updates
from . import service
from .errors import ApiError, explain
from .jobs import JobManager

ASSETS = Path(__file__).with_name("assets")
DEFAULT_PORT = 8765
PORT_TRIES = 24
MAX_BODY = 8 * 1024 * 1024
EXIT_DELAY = 1.5

log = logging.getLogger("sweep.web")

Route = Callable[[Any, dict[str, str]], Any]


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    log.setLevel(logging.INFO)
    if log.handlers:
        return
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(paths.LOGS / "web.log", encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    log.addHandler(handler)


# --------------------------------------------------------------------------- #
# updates: startup check + orderly exit for the apply helper
# --------------------------------------------------------------------------- #
_UPDATE_CHECK_LOCK = threading.Lock()
_UPDATE_CHECK_STARTED = False


def _start_update_check() -> None:
    """Kick off exactly one background check; startup never waits on the network."""
    global _UPDATE_CHECK_STARTED
    with _UPDATE_CHECK_LOCK:
        if _UPDATE_CHECK_STARTED:
            return
        _UPDATE_CHECK_STARTED = True
    threading.Thread(
        target=_run_update_check,
        name="sweep-update-check",
        daemon=True,
    ).start()


def _run_update_check() -> None:
    try:
        result = updates.check(timeout=4.0)
    except Exception:  # noqa: BLE001 - check() promises not to raise; stay safe
        return
    if result.status == updates.STATUS_AVAILABLE:
        print(
            f"  update: Sweep {result.latest} is available — "
            "open Settings → Updates to install it"
        )
    elif result.status == updates.STATUS_ERROR:
        # A plain network failure is normal on an offline laptop and the UI
        # already says so; a broken manifest or HTTP answer is worth a line.
        network_only = result.details.get("url") and not result.details.get("status")
        if not network_only:
            print(f"  update check: {result.message} — {result.reason}")


def _apply_update(handler: Any) -> dict[str, Any]:
    """Apply, then arrange to stop so the helper can replace the files."""
    result = service.apply_update(
        handler.body.get("confirm"), handler.body.get("version")
    )
    if result.get("applying"):
        _schedule_exit()
    return result


def _schedule_exit(delay: float = EXIT_DELAY) -> None:
    """Stop the process shortly after the HTTP response has been written.

    ``updates.apply`` launches a detached helper that waits for this PID and
    then replaces Sweep's program files. A normal interpreter shutdown can run
    arbitrary teardown and wait on request threads, which either races the
    helper or keeps the files locked. ``os._exit`` ends the process at once
    after the log handlers are flushed, so the helper can replace every file.
    The timer gives ``_send_json`` time to put the response on the wire first.
    """
    timer = threading.Timer(delay, _exit_now)
    timer.daemon = True
    timer.start()
    log.info("update applied; stopping the web server in %.1fs for the helper", delay)


def _exit_now() -> None:
    try:
        logging.shutdown()  # flush and close every handler before the hard exit
    finally:
        os._exit(0)


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
def _routes() -> list[tuple[str, str, Route]]:
    """(method, regex, handler). Regex groups become path params."""
    return [
        ("GET", r"^/api/health$", lambda h, m: {"status": "ok", "version": __version__}),
        ("GET", r"^/api/meta$", lambda h, m: service.meta()),
        ("POST", r"^/api/mode$", lambda h, m: service.set_mode(h.body.get("mode"))),
        ("GET", r"^/api/update$", lambda h, m: service.update_state()),
        ("POST", r"^/api/update/check$", lambda h, m: service.check_updates(
            h.body.get("force")
        )),
        ("POST", r"^/api/update/settings$", lambda h, m: service.save_update_settings(h.body)),
        ("POST", r"^/api/update/download$", lambda h, m: service.start_update_download(
            h.body.get("version")
        ).to_dict(False)),
        ("POST", r"^/api/update/apply$", lambda h, m: _apply_update(h)),
        ("POST", r"^/api/update/skip$", lambda h, m: service.skip_update(
            h.body.get("version")
        )),
        ("POST", r"^/api/update/cleanup$", lambda h, m: service.cleanup_updates()),
        ("GET", r"^/api/junk$", lambda h, m: service.junk_state()),
        ("POST", r"^/api/junk/scan$", lambda h, m: service.start_junk_scan().to_dict(False)),
        ("POST", r"^/api/junk/clean$", lambda h, m: service.start_clean(
            h.body.get("keys"), h.body.get("permanent"), h.body.get("confirm")
        ).to_dict(False)),
        ("GET", r"^/api/procs$", lambda h, m: service.procs_state()),
        ("POST", r"^/api/procs/refresh$", lambda h, m: service.start_procs_refresh().to_dict(False)),
        ("POST", r"^/api/procs/kill$", lambda h, m: service.start_kill(
            h.body.get("pids"), h.body.get("confirm")
        ).to_dict(False)),
        ("GET", r"^/api/leftovers$", lambda h, m: service.leftovers_state()),
        ("POST", r"^/api/leftovers/scan$", lambda h, m: service.start_leftovers_scan().to_dict(False)),
        ("POST", r"^/api/leftovers/remove$", lambda h, m: service.start_leftovers_remove(
            h.body.get("paths"), h.body.get("permanent"), h.body.get("confirm")
        ).to_dict(False)),
        ("GET", r"^/api/search$", lambda h, m: service.search_state()),
        ("POST", r"^/api/search$", lambda h, m: service.start_search(
            h.body.get("query"), h.body.get("registry"), h.body.get("services")
        ).to_dict(False)),
        ("POST", r"^/api/search/remove$", lambda h, m: service.start_remove_hits(
            h.body.get("ids"), h.body.get("permanent"), h.body.get("confirm")
        ).to_dict(False)),
        ("GET", r"^/api/quarantine$", lambda h, m: service.quarantine_state()),
        ("POST", r"^/api/quarantine/restore$", lambda h, m: service.start_restore(
            h.body.get("ids")
        ).to_dict(False)),
        ("POST", r"^/api/quarantine/purge$", lambda h, m: service.start_purge(
            h.body.get("ids"), h.body.get("confirm")
        ).to_dict(False)),
        ("POST", r"^/api/quarantine/purge-all$", lambda h, m: service.start_purge_all(
            h.body.get("confirm")
        ).to_dict(False)),
        ("GET", r"^/api/activity$", lambda h, m: service.activity(int(h.query.get("limit", 40)))),
        ("POST", r"^/api/open$", lambda h, m: service.open_path(h.body.get("path"))),
        ("POST", r"^/api/admin/relaunch$", lambda h, m: service.relaunch_admin()),
        ("GET", r"^/api/jobs$", lambda h, m: {
            "active": [j.to_dict(False) for j in service.manager().active()],
            "recent": [j.to_dict(False) for j in service.manager().recent(10)],
        }),
        ("GET", r"^/api/jobs/(?P<job_id>[0-9a-f]+)$", lambda h, m: _job_json(m["job_id"])),
        ("POST", r"^/api/jobs/(?P<job_id>[0-9a-f]+)/cancel$", lambda h, m: _cancel_job(m["job_id"])),
    ]


def _job_json(job_id: str) -> dict[str, Any]:
    job = service.manager().get(job_id)
    if job is None:
        raise ApiError(
            "job_not_found",
            "That job no longer exists",
            f"Job id {job_id!r} is not in this server's job list. Jobs are kept in "
            "memory only, so a server restart clears them.",
            "Reload the page and start the action again.",
            404,
        )
    return job.to_dict(True)


def _cancel_job(job_id: str) -> dict[str, Any]:
    job = service.manager().cancel(job_id)
    if job is None:
        raise ApiError(
            "job_not_found",
            "That job no longer exists",
            f"Job id {job_id!r} is not in this server's job list.",
            "Reload the page and start the action again.",
            404,
        )
    if job.status not in ("queued", "running"):
        raise ApiError(
            "job_finished",
            "That job already finished",
            f"The job is in state “{job.status}”, so there is nothing to cancel.",
            "Nothing changed; check the result in the interface.",
            409,
        )
    return job.to_dict(False)


ROUTES = _routes()


# --------------------------------------------------------------------------- #
# handler
# --------------------------------------------------------------------------- #
def make_handler(token: str, index_html: str) -> type[BaseHTTPRequestHandler]:
    class SweepHandler(BaseHTTPRequestHandler):
        server_version = f"Sweep/{__version__}"
        protocol_version = "HTTP/1.1"
        body: dict[str, Any]
        query: dict[str, str]

        # -- plumbing --------------------------------------------------- #
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401
            return  # quiet: API errors are logged with detail below

        def handle(self) -> None:
            # A tab closing mid-request is normal on a local app; don't let the
            # socket reset escape into a traceback on the console.
            try:
                super().handle()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._handle("POST")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._send(204, b"", "text/plain")

        def _handle(self, method: str) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            self.query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            self.body = {}
            try:
                if path == "/" or path == "/index.html":
                    return self._send_index()
                if path == "/favicon.ico":
                    return self._send_favicon()
                if path.startswith("/assets/"):
                    return self._send_asset(path[len("/assets/"):])
                if path.startswith("/api/"):
                    return self._handle_api(method, path)
                raise ApiError(
                    "not_found",
                    "No such page",
                    f"{path} is not a route in this server.",
                    "Go back to http://127.0.0.1:%d/." % self.server.server_address[1],
                    404,
                )
            except ApiError as exc:
                self._send_api_error(exc)
            except (BrokenPipeError, ConnectionResetError):
                return
            except BaseException as exc:  # noqa: BLE001
                error = explain(exc)
                log.error("unhandled %s %s:\n%s", method, path, traceback.format_exc())
                self._send_api_error(error)

        # -- api -------------------------------------------------------- #
        def _handle_api(self, method: str, path: str) -> None:
            self._check_origin()
            if path != "/api/health":
                self._check_token()
            if method == "POST":
                self._read_body()
            path_verbs = {verb for verb, pattern, _ in ROUTES if re.match(pattern, path)}
            for verb, pattern, handler in ROUTES:
                match = re.match(pattern, path)
                if not match or verb != method:
                    continue
                result = handler(self, match.groupdict())
                return self._send_json(200, {"ok": True, "data": result})
            if path_verbs:
                allowed = ", ".join(sorted(path_verbs))
                raise ApiError(
                    "method_not_allowed",
                    "Wrong HTTP method",
                    f"{path} accepts {allowed}, not {method}.",
                    "The interface uses the correct method; if you are calling the "
                    "API directly, check the verb.",
                    405,
                )
            raise ApiError(
                "not_found",
                "No such API endpoint",
                f"{path} does not exist on this server.",
                "Reload the page; the front end may be newer than the server.",
                404,
            )

        def _check_token(self) -> None:
            supplied = self.headers.get("X-Sweep-Token", "")
            if not secrets.compare_digest(supplied, token):
                raise ApiError(
                    "unauthorized",
                    "This request did not come from the Sweep page",
                    "The API requires the per-session token that the interface embeds "
                    "in the page. Requests from other sites, or with a stale token "
                    "after a server restart, are refused.",
                    "Reload http://127.0.0.1:%d/ — the page picks up the current token."
                    % self.server.server_address[1],
                    401,
                )

        def _check_origin(self) -> None:
            port = self.server.server_address[1]
            allowed = {
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
                f"http://[::1]:{port}",
            }
            host = (self.headers.get("Host") or "").lower()
            if host and host not in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}:
                raise ApiError(
                    "forbidden_host",
                    "Unexpected Host header",
                    f"Host “{host}” is not localhost. This blocks DNS-rebinding attacks "
                    "against a local cleanup tool.",
                    f"Open http://127.0.0.1:{port}/ directly.",
                    403,
                )
            origin = self.headers.get("Origin")
            if origin and origin.lower() not in allowed:
                raise ApiError(
                    "forbidden_origin",
                    "This request came from another site",
                    f"Origin “{origin}” is not this server. A page on the internet must "
                    "not be able to trigger local deletions.",
                    "Use the Sweep tab itself.",
                    403,
                )

        def _read_body(self) -> None:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                raise ApiError(
                    "invalid_request",
                    "Invalid Content-Length",
                    f"“{raw_length}” is not a number.",
                    "Send a JSON body with a correct Content-Length.",
                    400,
                )
            if length > MAX_BODY:
                raise ApiError(
                    "payload_too_large",
                    "The request body is too large",
                    f"{length} bytes exceeds the {MAX_BODY} byte limit.",
                    "Send a smaller selection.",
                    413,
                )
            if length <= 0:
                self.body = {}
                return
            raw = self.rfile.read(length)
            if not raw.strip():
                self.body = {}
                return
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(
                    "invalid_json",
                    "The request body is not valid JSON",
                    f"{type(exc).__name__}: {exc}",
                    "Send an object such as {\"keys\": [\"user_temp\"]}.",
                    400,
                )
            if not isinstance(parsed, dict):
                raise ApiError(
                    "invalid_request",
                    "The request body must be a JSON object",
                    f"Got {type(parsed).__name__} instead of an object.",
                    "Wrap the fields in { }.",
                    400,
                )
            self.body = parsed

        # -- responses -------------------------------------------------- #
        def _send_index(self) -> None:
            html = index_html.replace("__SWEEP_TOKEN__", token).replace(
                "__SWEEP_VERSION__", __version__
            )
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8", no_store=True)

        def _send_favicon(self) -> None:
            icon = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                '<rect width="64" height="64" rx="14" fill="#0b1119"/>'
                '<path d="M20 40c4 6 24 6 24-2 0-9-22-4-22-14 0-7 18-8 24-2" '
                'fill="none" stroke="#22d3ee" stroke-width="6" stroke-linecap="round"/>'
                "</svg>"
            ).encode("utf-8")
            self._send(200, icon, "image/svg+xml")

        def _send_asset(self, name: str) -> None:
            name = urllib.parse.unquote(name)
            target = (ASSETS / name).resolve()
            try:
                target.relative_to(ASSETS.resolve())
            except ValueError:
                raise ApiError(
                    "not_found",
                    "No such asset",
                    f"“{name}” escapes the asset folder.",
                    "Reload the page.",
                    404,
                )
            if not target.is_file():
                raise ApiError(
                    "not_found",
                    "No such asset",
                    f"{name} is not in the assets folder.",
                    "Reload the page; the front end may be out of date.",
                    404,
                )
            mime, _ = mimetypes.guess_type(str(target))
            mime = {
                ".js": "text/javascript",
                ".mjs": "text/javascript",
                ".css": "text/css",
                ".html": "text/html",
                ".svg": "image/svg+xml",
                ".json": "application/json",
                ".png": "image/png",
                ".woff2": "font/woff2",
            }.get(target.suffix.lower(), mime or "application/octet-stream")
            if mime.startswith("text/") or mime in ("application/json", "image/svg+xml"):
                mime += "; charset=utf-8"
            self._send(200, target.read_bytes(), mime)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", no_store=True)

        def _send_api_error(self, error: ApiError) -> None:
            log.info("api error %s: %s (%s)", error.code, error.message, error.reason)
            self._send_json(error.status, {"ok": False, "error": error.to_dict()})

        def _send(self, status: int, body: bytes, content_type: str, no_store: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
            )
            self.send_header("Cache-Control", "no-store" if no_store else "no-cache")
            self.end_headers()
            if body:
                self.wfile.write(body)

    return SweepHandler


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def create_server(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> tuple[ThreadingHTTPServer, str, int]:
    setup_logging()
    index_path = ASSETS / "index.html"
    if not index_path.is_file():
        raise SystemExit(
            f"Sweep web assets are missing: {index_path}\n"
            "Reinstall Sweep or restore the sweep_app/web/assets folder."
        )
    index_html = index_path.read_text(encoding="utf-8")
    token = secrets.token_urlsafe(24)

    manager = JobManager()
    service.configure(manager)
    _start_update_check()

    handler = make_handler(token, index_html)
    last_error: OSError | None = None
    for offset in range(PORT_TRIES):
        candidate = port + offset
        try:
            httpd = ThreadingHTTPServer((host, candidate), handler)
            httpd.daemon_threads = True
            return httpd, token, candidate
        except OSError as exc:
            last_error = exc
            if exc.errno in (48, 98, 10048):  # address in use
                continue
            raise
    raise SystemExit(
        f"Sweep could not find a free port in {port}..{port + PORT_TRIES - 1}.\n"
        f"Last error: {last_error}\n"
        "Close the program using the port, or start with --port <number>."
    )


def serve(port: int = DEFAULT_PORT, open_browser: bool = True, host: str = "127.0.0.1") -> int:
    httpd, _token, actual_port = create_server(host, port)
    url = f"http://127.0.0.1:{actual_port}/"
    print()
    print("  Sweep web interface")
    print(f"  → {url}")
    print(f"  data: {paths.SWEEP_HOME}")
    print("  Press Ctrl+C to stop.")
    print()
    if open_browser:
        threading.Timer(0.9, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\n  stopping…")
    finally:
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve())
