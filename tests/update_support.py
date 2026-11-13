"""Shared, hermetic helpers for the update integration tests.

This module is deliberately *not* named ``test_*.py``: ``unittest discover``
must not collect it. The three update test modules import it instead, so the
temporary-home and tiny-HTTP-server plumbing lives in one place.

Nothing here reaches the internet or the real Sweep data folder. ``temp_home``
redirects every writable path, removes ``SWEEP_UPDATE_URL`` from the
environment, and replaces the built-in manifest URL with the source-checkout
placeholder so even a stray background check resolves to "unconfigured".
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _entry in (str(ROOT), str(ROOT / "vendor")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from sweep_app import paths, updates  # noqa: E402

# Same string ``updates.resolve_source`` looks for when deciding that a build
# has no real release feed.
PLACEHOLDER_MANIFEST = (
    "https://github.com/OWNER/REPO/releases/latest/download/latest.json"
)

_PATH_NAMES = ("SWEEP_HOME", "QUARANTINE", "LOGS", "CONFIG_FILE", "UPDATES")
_ENV_NAMES = ("LOCALAPPDATA", "SWEEP_UPDATE_URL")


@contextmanager
def temp_home():
    """Point every writable Sweep path at a throwaway folder.

    Yields the temporary ``Sweep`` data folder (the equivalent of
    ``%LOCALAPPDATA%\\Sweep``). Everything is restored on the way out, even if
    the test body raises.
    """
    with tempfile.TemporaryDirectory(prefix="sweep-test-") as raw:
        home = Path(raw)
        sweep_home = home / "Sweep"
        old_paths = {name: getattr(paths, name) for name in _PATH_NAMES}
        old_env = {name: os.environ.get(name) for name in _ENV_NAMES}
        old_default = updates.DEFAULT_MANIFEST_URL

        paths.SWEEP_HOME = sweep_home
        paths.QUARANTINE = sweep_home / "quarantine"
        paths.LOGS = sweep_home / "logs"
        paths.CONFIG_FILE = sweep_home / "config.json"
        paths.UPDATES = sweep_home / "updates"
        sweep_home.mkdir(parents=True, exist_ok=True)

        # The standalone updater helper reads LOCALAPPDATA itself, so redirect
        # that too. A developer's SWEEP_UPDATE_URL must not leak into a test.
        os.environ["LOCALAPPDATA"] = str(home)
        os.environ.pop("SWEEP_UPDATE_URL", None)
        updates.DEFAULT_MANIFEST_URL = PLACEHOLDER_MANIFEST
        try:
            yield sweep_home
        finally:
            for name, value in old_paths.items():
                setattr(paths, name, value)
            updates.DEFAULT_MANIFEST_URL = old_default
            for name, value in old_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@contextmanager
def served(routes: dict[str, tuple[int, bytes, str]]):
    """Serve a tiny fixed map of ``path -> (status, body, content-type)``.

    Only 127.0.0.1 is used, which is also the one plain-http host the update
    engine accepts, so the tests exercise the real URL validation.
    """

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # noqa: D401, ANN002 - keep test output clean
            return

        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler contract
            status, body, ctype = routes.get(self.path, (404, b"not found", "text/plain"))
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # A failed assertion can abandon a download; daemon request threads keep
    # teardown from blocking on them.
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def make_zip(version: str = "9.9.9") -> bytes:
    """A minimal archive that passes ``updates.stage``'s shape/version checks."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main.py", '"""fake launcher"""\nprint("hello")\n')
        archive.writestr("sweep_app/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr("sweep_app/engine.py", "VALUE = 1\n")
    return buffer.getvalue()
