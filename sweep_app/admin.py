"""Elevation helpers."""
from __future__ import annotations

import ctypes
import os
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - shell32 is always present, but be safe
        return False


def relaunch_as_admin() -> tuple[bool, str]:
    """Start a second, elevated copy of Sweep. Returns (launched, error)."""
    script = os.path.abspath(sys.argv[0])
    args = " ".join(f'"{a}"' for a in sys.argv[1:])
    params = f'"{script}" {args}'.strip()
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, os.getcwd(), 1
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if result > 32:
        return True, ""
    return False, f"ShellExecute returned {result} (cancelled?)"


def open_folder(path: str) -> None:
    try:
        os.startfile(path)  # noqa: S606 - intentional
    except OSError:
        pass
