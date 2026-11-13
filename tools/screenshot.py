"""Render the running TUI to PNG using Textual's compositor + Pillow.

Textual's own SVG export depends on a webfont that isn't installed here, so the
images came out clipped and grey. This draws the actual cell grid instead.

Block elements and box-drawing characters are painted as real cells rather than
as font text: a terminal gives ``█`` and ``─`` the full cell, while Pillow's
font gives them the glyph's em box, which leaves seams in the logo and bars.
"""
from __future__ import annotations

import asyncio
import glob
import os
import sys

os.environ.pop("NO_COLOR", None)
os.environ["COLORTERM"] = "truecolor"
os.environ["TERM"] = "xterm-256color"
os.environ["FORCE_COLOR"] = "3"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "vendor"))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402
from rich.cells import cell_len  # noqa: E402

from sweep_app import paths  # noqa: E402
from sweep_app.ui.app import SweepApp  # noqa: E402

OUT = os.path.join(ROOT, "screenshots")
FONT_SIZE = 16
CELL_W = 9
CELL_H = 20
PAD = 12
BG = (7, 10, 15)


def _load_fonts() -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont]:
    candidates = [
        (r"C:\Windows\Fonts\consola.ttf", r"C:\Windows\Fonts\consolab.ttf"),
        (r"C:\Windows\Fonts\CascadiaMono.ttf", r"C:\Windows\Fonts\CascadiaMono.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular):
            return (
                ImageFont.truetype(regular, FONT_SIZE),
                ImageFont.truetype(bold if os.path.exists(bold) else regular, FONT_SIZE),
            )
    return ImageFont.load_default(), ImageFont.load_default()


FONT, FONT_BOLD = _load_fonts()


def _rgb(color, default):
    if color is None:
        return default
    try:
        red, green, blue = color.get_truecolor()
        return (red, green, blue)
    except Exception:  # noqa: BLE001 - default/ansi colors
        return default


# --------------------------------------------------------------------------- #
# cell glyphs
# --------------------------------------------------------------------------- #
def _box_segments(char: str, x: int, y: int) -> list[tuple[int, int, int, int]] | None:
    """Line segments (x1, y1, x2, y2) that draw *char* edge-to-edge in a cell."""
    left, right = x, x + CELL_W - 1
    top, bottom = y, y + CELL_H - 1
    mid_x, mid_y = x + CELL_W // 2, y + CELL_H // 2

    single = {
        "─": [(left, mid_y, right, mid_y)],
        "│": [(mid_x, top, mid_x, bottom)],
        "┌": [(mid_x, mid_y, right, mid_y), (mid_x, mid_y, mid_x, bottom)],
        "╭": [(mid_x, mid_y, right, mid_y), (mid_x, mid_y, mid_x, bottom)],
        "┐": [(left, mid_y, mid_x, mid_y), (mid_x, mid_y, mid_x, bottom)],
        "╮": [(left, mid_y, mid_x, mid_y), (mid_x, mid_y, mid_x, bottom)],
        "└": [(mid_x, mid_y, right, mid_y), (mid_x, top, mid_x, mid_y)],
        "╰": [(mid_x, mid_y, right, mid_y), (mid_x, top, mid_x, mid_y)],
        "┘": [(left, mid_y, mid_x, mid_y), (mid_x, top, mid_x, mid_y)],
        "╯": [(left, mid_y, mid_x, mid_y), (mid_x, top, mid_x, mid_y)],
        "├": [(mid_x, top, mid_x, bottom), (mid_x, mid_y, right, mid_y)],
        "┤": [(mid_x, top, mid_x, bottom), (left, mid_y, mid_x, mid_y)],
        "┬": [(left, mid_y, right, mid_y), (mid_x, mid_y, mid_x, bottom)],
        "┴": [(left, mid_y, right, mid_y), (mid_x, top, mid_x, mid_y)],
        "┼": [(left, mid_y, right, mid_y), (mid_x, top, mid_x, bottom)],
        "╬": [(left, mid_y, right, mid_y), (mid_x, top, mid_x, bottom)],
    }
    if char in single:
        return single[char]

    # double-line glyphs: two parallel 1px strokes, one pixel either side of the
    # centre, meeting at the cell edges so the logo's letters stay continuous.
    lo_x, hi_x = mid_x - 1, mid_x + 1
    lo_y, hi_y = mid_y - 1, mid_y + 1
    double = {
        "═": [(left, lo_y, right, lo_y), (left, hi_y, right, hi_y)],
        "║": [(lo_x, top, lo_x, bottom), (hi_x, top, hi_x, bottom)],
        "╔": [
            (lo_x, lo_y, right, lo_y),
            (hi_x, hi_y, right, hi_y),
            (lo_x, lo_y, lo_x, bottom),
            (hi_x, hi_y, hi_x, bottom),
        ],
        "╗": [
            (left, lo_y, hi_x, lo_y),
            (left, hi_y, lo_x, hi_y),
            (hi_x, lo_y, hi_x, bottom),
            (lo_x, hi_y, lo_x, bottom),
        ],
        "╚": [
            (lo_x, lo_y, right, lo_y),
            (hi_x, hi_y, right, hi_y),
            (lo_x, top, lo_x, lo_y),
            (hi_x, top, hi_x, hi_y),
        ],
        "╝": [
            (left, lo_y, hi_x, lo_y),
            (left, hi_y, lo_x, hi_y),
            (hi_x, top, hi_x, lo_y),
            (lo_x, top, lo_x, hi_y),
        ],
    }
    return double.get(char)


# Fraction of the cell covered, as (width, height, offset_x, offset_y).
_PARTIAL_BLOCKS = {
    "▏": (0.125, 1.0, 0.0, 0.0),
    "▎": (0.25, 1.0, 0.0, 0.0),
    "▍": (0.375, 1.0, 0.0, 0.0),
    "▌": (0.5, 1.0, 0.0, 0.0),
    "▋": (0.625, 1.0, 0.0, 0.0),
    "▊": (0.75, 1.0, 0.0, 0.0),
    "▉": (0.875, 1.0, 0.0, 0.0),
    "▀": (1.0, 0.5, 0.0, 0.0),
    "▄": (1.0, 0.5, 0.0, 0.5),
    "▐": (0.5, 1.0, 0.5, 0.0),
}


def _draw_glyph(draw: ImageDraw.ImageDraw, x: int, y: int, char: str, color, font) -> None:
    if char == "█":
        draw.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], fill=color)
        return
    if char in _PARTIAL_BLOCKS:
        width, height, off_x, off_y = _PARTIAL_BLOCKS[char]
        x0 = x + round(CELL_W * off_x)
        y0 = y + round(CELL_H * off_y)
        draw.rectangle(
            [x0, y0, x0 + max(1, round(CELL_W * width)) - 1, y0 + max(1, round(CELL_H * height)) - 1],
            fill=color,
        )
        return
    if char in "░▒▓":
        # Dither density: 1, 2 or 3 dots per 4x4 tile.
        step = 2 if char == "▒" else 4
        if char == "▓":
            draw.rectangle([x, y, x + CELL_W - 1, y + CELL_H - 1], fill=color)
            return
        for yy in range(y + 1, y + CELL_H, step):
            for xx in range(x + 1, x + CELL_W, step):
                draw.point((xx, yy), fill=color)
        return
    segments = _box_segments(char, x, y)
    if segments is not None:
        for x1, y1, x2, y2 in segments:
            draw.line([(x1, y1), (x2, y2)], fill=color, width=1)
        return
    draw.text((x, y), char, font=font, fill=color)


# --------------------------------------------------------------------------- #
# frame
# --------------------------------------------------------------------------- #
def render(app: SweepApp, path: str) -> tuple[int, int]:
    screen = app.screen
    strips = screen._compositor.render_strips()
    width = screen.size.width
    height = len(strips)
    image = Image.new("RGB", (width * CELL_W + PAD * 2, height * CELL_H + PAD * 2), BG)
    draw = ImageDraw.Draw(image)

    for row, strip in enumerate(strips):
        x = 0
        for segment in strip:
            text = segment.text
            if not text:
                continue
            style = segment.style
            background = _rgb(style.bgcolor, None)
            foreground = _rgb(style.color, (201, 214, 228))
            font = FONT_BOLD if style.bold else FONT
            for char in text:
                cells = cell_len(char) or 1
                px = PAD + x * CELL_W
                py = PAD + row * CELL_H
                if background is not None and background != BG:
                    draw.rectangle(
                        [px, py, px + cells * CELL_W - 1, py + CELL_H - 1],
                        fill=background,
                    )
                if char.strip():
                    _draw_glyph(draw, px, py, char, foreground, font)
                x += cells

    image.save(path)
    return image.size


async def _settle(pilot, pane, timeout: float = 150.0) -> None:
    waited = 0.0
    while getattr(pane, "_busy", False) or getattr(pane, "_scanning", False):
        await pilot.pause(0.2)
        waited += 0.2
        if waited > timeout:
            print("  ! timeout waiting for", pane.id)
            return
    await pilot.pause(0.6)


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for stale in glob.glob(str(paths.LOGS / "sweep-*.log")):
        try:
            os.remove(stale)
        except OSError:
            pass
    app = SweepApp()
    async with app.run_test(size=(168, 50)) as pilot:
        await pilot.pause(6.0)
        for view in ("dashboard", "junk", "procs", "leftovers", "remover", "quarantine"):
            app.action_view(view)
            await pilot.pause(0.5)
            pane = app.query_one(f"#view-{view}")
            await _settle(pilot, pane)
            size = render(app, os.path.join(OUT, f"{view}.png"))
            print(f"ok   {view:<12} {size[0]}x{size[1]}")

        app.action_view("junk")
        await pilot.pause(1.0)
        pane = app.query_one("#view-junk")
        pane.select_safe()
        pane.primary_action()
        await pilot.pause(0.8)
        render(app, os.path.join(OUT, "confirm.png"))
        print("ok   confirm")

        await pilot.press("escape")
        await pilot.pause(0.3)
        app.action_settings()
        await pilot.pause(0.8)
        render(app, os.path.join(OUT, "settings.png"))
        print("ok   settings")

        await pilot.press("escape")
        await pilot.pause(0.3)
        app.action_help()
        await pilot.pause(0.8)
        render(app, os.path.join(OUT, "help.png"))
        print("ok   help")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
