"""Tests for ``sweep update`` as a scriptable command.

``cli.main(argv)`` is called in-process with stdout/stderr redirected, so the
tests assert the exit codes and the JSON contract a caller would rely on. The
temporary-home helper keeps every config write out of the real profile, and the
only network traffic is to a loopback manifest server.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from update_support import make_zip, served, temp_home  # noqa: E402

from sweep_app import __version__, cli, config  # noqa: E402


def manifest_for(base: str, version: str, payload: bytes) -> dict:
    return {
        "version": version,
        "url": f"{base}/Sweep-{version}.zip",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
        "notes": "cli integration test release",
    }


class CliUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._home_ctx = temp_home()
        self.home = self._home_ctx.__enter__()
        self.addCleanup(self._home_ctx.__exit__, None, None, None)

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        """Run ``cli.main`` and return (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as exc:  # argparse --version / usage errors
                code = int(exc.code or 0)
        return code, out.getvalue(), err.getvalue()

    # -- version -------------------------------------------------------- #
    def test_version_flag(self):
        code, out, err = self.run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(f"Sweep {__version__}", out)
        self.assertEqual(err, "")

    # -- unconfigured JSON ---------------------------------------------- #
    def test_update_json_when_unconfigured(self):
        code, out, err = self.run_cli(["update", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)  # must be exactly one valid JSON document
        self.assertEqual(data["status"], "unconfigured")
        self.assertEqual(data["current"], __version__)
        self.assertEqual(data["release"], None)
        self.assertTrue(data["reason"])
        self.assertTrue(data["hint"])

    # -- settings validation -------------------------------------------- #
    def test_source_rejects_bad_url(self):
        # --json keeps prose on stderr so stdout stays machine-readable.
        code, out, err = self.run_cli(
            ["update", "--source", "ftp://example.com/latest.json", "--json"]
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("Update settings were not saved", err)
        # The rejected value was not written.
        self.assertEqual(config.updates()["manifest_url"], "")
        self.assertFalse((self.home / "config.json").exists())

    # -- local check ---------------------------------------------------- #
    def test_check_against_local_manifest_returns_10_and_available(self):
        routes: dict[str, tuple[int, bytes, str]] = {}
        with served(routes) as base:
            payload = make_zip("99.0.0")
            release = manifest_for(base, "99.0.0", payload)
            routes["/latest.json"] = (
                200,
                json.dumps(release).encode(),
                "application/json",
            )
            routes["/Sweep-99.0.0.zip"] = (200, payload, "application/zip")
            code, out, err = self.run_cli(
                [
                    "update",
                    "--source",
                    f"{base}/latest.json",
                    "--check",
                    "--json",
                ]
            )
        self.assertEqual(code, 10, err)
        data = json.loads(out)
        self.assertEqual(data["status"], "available")
        self.assertEqual(data["latest"], "99.0.0")
        self.assertEqual(data["release"]["url"], f"{base}/Sweep-99.0.0.zip")
        # The source was persisted by the same invocation.
        self.assertEqual(config.updates()["manifest_url"], f"{base}/latest.json")

    # -- enable / disable ----------------------------------------------- #
    def test_disable_and_enable_persist(self):
        code, out, err = self.run_cli(["update", "--disable", "--json"])
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertTrue(summary["ok"])
        self.assertFalse(summary["settings"]["enabled"])
        self.assertFalse(config.updates()["enabled"])

        code, out, err = self.run_cli(["update", "--enable", "--json"])
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertTrue(summary["settings"]["enabled"])
        self.assertTrue(config.updates()["enabled"])

    # -- skip ----------------------------------------------------------- #
    def test_skip_persists(self):
        code, out, err = self.run_cli(["update", "--skip", "9.9.9", "--json"])
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["ok"], True)
        self.assertEqual(data["action"], "skip")
        self.assertEqual(data["skipped"], "9.9.9")
        self.assertEqual(config.updates()["skipped"], "9.9.9")


if __name__ == "__main__":
    unittest.main(verbosity=2)
