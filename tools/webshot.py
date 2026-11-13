"""Visual QA harness for the local web UI.

Renders each route at a set of viewports with headless Chrome (Playwright),
saves PNGs, and reports console errors and horizontal overflow.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from playwright.async_api import async_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_ROUTES = ["dashboard", "junk", "processes", "leftovers", "remover", "quarantine", "settings"]
DEFAULT_WIDTHS = [1920, 1440, 1280, 1024, 768, 480, 390, 360]


async def capture(
    base: str, out: str, routes: list[str], sizes: list[tuple[int, int]], wait: float
) -> dict:
    os.makedirs(out, exist_ok=True)
    report: dict = {"errors": [], "overflow": [], "shots": 0}
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=CHROME, headless=True, args=["--force-device-scale-factor=1"])
        for width, height in sizes:
            context = await browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            page = await context.new_page()
            page.on("console", lambda m: report["errors"].append(f"console[{m.type}] {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: report["errors"].append(f"pageerror {e}"))
            for route in routes:
                url = f"{base}/#/{route}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_selector("#view .page-head, #view .banner, #view .empty, #view .skeleton", timeout=15000)
                await page.wait_for_timeout(int(wait * 1000))
                await page.screenshot(path=os.path.join(out, f"{route}-{width}.png"))
                report["shots"] += 1
                metrics = await page.evaluate(
                    """() => ({
                        scrollW: document.documentElement.scrollWidth,
                        innerW: window.innerWidth,
                        bodyW: document.body.scrollWidth,
                    })"""
                )
                if metrics["scrollW"] > metrics["innerW"] + 1 or metrics["bodyW"] > metrics["innerW"] + 1:
                    report["overflow"].append({"route": route, "width": width, **metrics})
            await context.close()
        await browser.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8766")
    ap.add_argument("--out", default="qa")
    ap.add_argument("--routes", default=",".join(DEFAULT_ROUTES))
    ap.add_argument(
        "--widths",
        default=",".join(map(str, DEFAULT_WIDTHS)),
        help="widths to shoot; height is chosen from the width (legacy mode)",
    )
    ap.add_argument(
        "--sizes",
        default="",
        help="exact WxH viewports, comma separated (overrides --widths), "
        "for example 1366x768,1280x720,390x844",
    )
    ap.add_argument("--wait", type=float, default=1.4)
    args = ap.parse_args()

    routes = [r for r in args.routes.split(",") if r]
    if args.sizes:
        sizes = []
        for item in args.sizes.split(","):
            if not item:
                continue
            width, _, height = item.lower().partition("x")
            sizes.append((int(width), int(height)))
    else:
        sizes = [
            (int(w), 1080 if int(w) >= 1200 else (900 if int(w) >= 900 else 844))
            for w in args.widths.split(",")
            if w
        ]
    report = asyncio.run(capture(args.base, args.out, routes, sizes, args.wait))
    print(json.dumps(report, indent=2))
    return 1 if report["errors"] or report["overflow"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
