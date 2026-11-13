"""Headless smoke test: boot the TUI, visit every pane, save screenshots."""
from __future__ import annotations

import asyncio
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
sys.path.insert(0, ROOT)

from sweep_app.ui.app import SweepApp  # noqa: E402

OUT = os.path.join(ROOT, "screenshots")


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = SweepApp()
    failures = 0
    async with app.run_test(size=(168, 50)) as pilot:
        await pilot.pause(1.5)
        for view in ("dashboard", "junk", "procs", "leftovers", "remover", "quarantine"):
            try:
                app.action_view(view)
                await pilot.pause(2.0)
                svg = app.export_screenshot()
                with open(os.path.join(OUT, f"{view}.svg"), "w", encoding="utf-8") as fh:
                    fh.write(svg)
                print(f"ok   {view:<12} {len(svg):>7} bytes svg")
            except Exception:  # noqa: BLE001
                failures += 1
                print(f"FAIL {view}")
                traceback.print_exc()

        # exercise a dialog and the settings screen
        try:
            app.action_help()
            await pilot.pause(0.5)
            app.export_screenshot()
            await pilot.press("escape")
            await pilot.pause(0.5)
            app.action_settings()
            await pilot.pause(0.5)
            await pilot.press("escape")
            await pilot.pause(0.5)
            print("ok   modals")
        except Exception:  # noqa: BLE001
            failures += 1
            traceback.print_exc()

        # exercise selection + confirmation on the junk pane
        try:
            app.action_view("junk")
            await pilot.pause(2.0)
            pane = app.query_one("#view-junk")
            pane.select_safe()
            pane.primary_action()
            await pilot.pause(0.8)
            svg = app.export_screenshot()
            with open(os.path.join(OUT, "confirm.svg"), "w", encoding="utf-8") as fh:
                fh.write(svg)
            await pilot.press("escape")
            await pilot.pause(0.4)
            print("ok   junk confirm dialog")
        except Exception:  # noqa: BLE001
            failures += 1
            traceback.print_exc()

    print("failures:", failures)
    return failures


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
