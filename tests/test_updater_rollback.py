"""Rollback tests for the standalone apply helper.

``sweep_app.updater`` runs as a separate process in production, but its
``apply_plan`` is a plain function. These tests drive it against a temporary
install tree and simulate a disk failure in the *middle of the overlay* (after
at least one new file has already replaced an old one). The helper must put the
old tree back and record ``rolled_back`` in ``update-status.json``.

No real install folder is touched: the plan, the install tree, the backup and
the status file all live under the temporary home.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from update_support import temp_home  # noqa: E402

from sweep_app import paths, updater  # noqa: E402


class FailedOverlayTests(unittest.TestCase):
    def _plan(self, home: Path, version: str = "2.0.0") -> tuple[Path, Path, Path]:
        """Build an old install tree, a staged new tree, and an apply plan."""
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

        plan_path = home / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "version": version,
                    "from_version": "1.0.0",
                    "app_root": str(install.resolve()),
                    "staged": str(staged.resolve()),
                    "backup": str((home / "backup").resolve()),
                    "keep_backup": True,
                    "relaunch": [],
                    "pid": 0,
                }
            ),
            encoding="utf-8",
        )
        return plan_path, install, staged

    def test_failed_overlay_restores_old_tree_and_records_rollback(self):
        with temp_home() as home:
            plan_path, install, staged = self._plan(home)
            staged_root = staged.resolve()
            real_copy2 = updater.shutil.copy2
            overlay_calls = {"count": 0}

            def failing_copy2(src, dst, *args, **kwargs):
                """Let backups/restores through; fail on the second overlay file."""
                source = Path(src)
                resolved = source.resolve()
                under_staged = (
                    resolved == staged_root or staged_root in resolved.parents
                )
                if not under_staged:
                    return real_copy2(src, dst, *args, **kwargs)
                overlay_calls["count"] += 1
                if overlay_calls["count"] == 2:
                    raise OSError(28, "No space left on device (simulated)")
                return real_copy2(src, dst, *args, **kwargs)

            log = updater.Log(home / "helper.log")
            # updater.shutil is the shutil module itself, so the patch is
            # process-wide; restore it no matter how the call ends.
            updater.shutil.copy2 = failing_copy2
            try:
                code = updater.apply_plan(plan_path, log)
            finally:
                updater.shutil.copy2 = real_copy2
                log.close()

            self.assertEqual(code, 1)
            self.assertEqual(overlay_calls["count"], 2)

            # The first overlay copy had already replaced main.py; the rollback
            # must have put the old content back.
            self.assertEqual(
                (install / "main.py").read_text(encoding="utf-8"), "old launcher"
            )
            self.assertIn(
                '"1.0.0"',
                (install / "sweep_app" / "__init__.py").read_text(encoding="utf-8"),
            )
            # Stale modules were never moved away because the failure happened
            # before that step; the pycache is still purged by restore().
            self.assertTrue((install / "sweep_app" / "stale.py").is_file())
            self.assertFalse((install / "sweep_app" / "engine.py").exists())
            self.assertFalse((install / "sweep_app" / "__pycache__").exists())

            status_path = paths.UPDATES / "update-status.json"
            self.assertTrue(status_path.is_file())
            status = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertFalse(status["ok"])
            self.assertTrue(status["rolled_back"])
            self.assertEqual(status["version"], "2.0.0")
            self.assertEqual(status["from_version"], "1.0.0")
            self.assertIn("simulated", status["error"])
            # The backup is kept so a person can roll back manually too.
            self.assertTrue(Path(status["backup"]).is_dir())
            self.assertTrue((Path(status["backup"]) / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
