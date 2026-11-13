# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the portable Sweep.exe build.

Build it with tools/build_exe.ps1 (which installs PyInstaller, runs this spec,
then proves the exe starts and serves /api/health), or directly:

    python -m PyInstaller --noconfirm --clean Sweep.spec

The build is intentionally **onedir**: the folder can be replaced or overlaid
in place, a console window is required for the Textual UI, and it starts faster
than a one-file archive. ``dist/Sweep/`` is the whole application; ship that
folder.

The spec adds vendor/ to the analysis path so the same pinned libraries the
portable zip uses are the ones frozen into the exe. It also collects Textual's
data files and the widget/driver submodules: Textual resolves widgets lazily by
name, which static import analysis cannot see.
"""
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()
VENDOR = ROOT / "vendor"
if VENDOR.is_dir() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

datas = [
    # The web UI is served from disk, and the TUI loads its theme by path.
    # Use a glob here: a directory source would copy the *contents* of assets/
    # into sweep_app/web instead of creating sweep_app/web/assets/.
    (str(ROOT / "sweep_app" / "web" / "assets" / "*"), "sweep_app/web/assets"),
    (str(ROOT / "sweep_app" / "ui" / "style.tcss"), "sweep_app/ui"),
]
# Textual ships tree-sitter highlight queries and typing markers as package data.
datas += collect_data_files("textual")

# Textual resolves widgets lazily by name, so static analysis cannot see them.
# Collect widgets and drivers only: collecting all of textual also drags in its
# demo app, which imports Pillow and numpy (tens of MB the real UI never uses).
hiddenimports = collect_submodules("textual.widgets") + collect_submodules("textual.drivers")

icon = ROOT / "sweep.ico"
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(VENDOR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "_pytest", "PIL", "numpy", "textual.demo"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Sweep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Sweep",
)
