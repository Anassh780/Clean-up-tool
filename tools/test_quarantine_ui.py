"""Headless test: seed a quarantine batch, list it in the pane, restore it."""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile

os.environ.pop("NO_COLOR", None)
os.environ["COLORTERM"] = "truecolor"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
sys.path.insert(0, ROOT)

from sweep_app import paths, safety  # noqa: E402
from sweep_app.ui.app import SweepApp  # noqa: E402


async def main() -> int:
    base = pathlib.Path(tempfile.mkdtemp(prefix="sweep-uitest-"))
    (base / "one.txt").write_text("a" * 4096)
    (base / "two.bin").write_bytes(b"b" * 8192)

    deleter = safety.Deleter(mode="quarantine", note="ui-test")
    result = deleter.delete(str(base), allowed_roots=[paths.TEMP], category="user_temp")
    deleter.finish()
    print("seeded:", result.status, "batch:", deleter.batch_id)
    if result.status != "moved":
        print("FAIL: could not seed quarantine")
        return 1

    app = SweepApp()
    failures = 0
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.5)
        app.action_view("quarantine")
        await pilot.pause(0.5)
        pane = app.query_one("#view-quarantine")
        rows = pane.query_one("#quarantine-table").row_count
        print("rows in pane:", rows)
        if rows != 1:
            print("FAIL: expected 1 batch row")
            failures += 1
        else:
            batch_id = pane.batches[0]["id"]
            pane.checked.add(batch_id)
            pane._do_restore(True)
            for _ in range(100):
                if not pane._busy:
                    break
                await pilot.pause(0.2)
            await pilot.pause(0.5)
            restored = (base / "one.txt").exists() and (base / "two.bin").exists()
            print("restored on disk:", restored)
            if not restored:
                print("FAIL: files were not restored")
                failures += 1
            print("rows after restore:", pane.query_one("#quarantine-table").row_count)
            if pane.query_one("#quarantine-table").row_count != 0:
                print("FAIL: batch still listed after restore")
                failures += 1
        await pilot.pause(0.3)
        app.export_screenshot()

    try:
        import shutil

        shutil.rmtree(base, ignore_errors=True)
    except OSError:
        pass
    print("failures:", failures)
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
