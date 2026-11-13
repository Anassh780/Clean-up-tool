"""Known Windows locations and drive information."""
from __future__ import annotations

import os
from pathlib import Path

import psutil

LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
APPDATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
PROGRAMDATA = Path(os.environ.get("ProgramData") or r"C:\ProgramData")
USERPROFILE = Path(os.environ.get("USERPROFILE") or Path.home())
WINDIR = Path(os.environ.get("SystemRoot") or r"C:\Windows")
SYSTEM_DRIVE = Path(os.environ.get("SystemDrive", "C:") + "\\")

PROGRAM_FILES = Path(os.environ.get("ProgramFiles") or r"C:\Program Files")
PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)")
PROGRAM_FILES_ARM = Path(os.environ.get("ProgramW6432") or r"C:\Program Files")

TEMP = Path(os.environ.get("TEMP") or (LOCALAPPDATA / "Temp"))
TMP = Path(os.environ.get("TMP") or TEMP)

START_MENU_ALL = PROGRAMDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs"
START_MENU_USER = APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs"

SWEEP_HOME = LOCALAPPDATA / "Sweep"
QUARANTINE = SWEEP_HOME / "quarantine"
LOGS = SWEEP_HOME / "logs"
CONFIG_FILE = SWEEP_HOME / "config.json"
UPDATES = SWEEP_HOME / "updates"


def expand(raw: str | os.PathLike[str]) -> Path:
    """Expand %VARS% and ~ in a configured path."""
    return Path(os.path.expandvars(os.path.expanduser(str(raw))))


def user_data_dirs() -> list[Path]:
    return [
        USERPROFILE / "Desktop",
        USERPROFILE / "Documents",
        USERPROFILE / "Downloads",
        USERPROFILE / "Pictures",
        USERPROFILE / "Music",
        USERPROFILE / "Videos",
        USERPROFILE / "OneDrive",
        USERPROFILE / "Saved Games",
        USERPROFILE / "Favorites",
        USERPROFILE / "Links",
        USERPROFILE / "Contacts",
        USERPROFILE / "Searches",
        USERPROFILE / "3D Objects",
        USERPROFILE / "AppData",
    ]


def fixed_drives() -> list[Path]:
    """Local fixed disks that are currently mounted."""
    drives: list[Path] = []
    for part in psutil.disk_partitions(all=False):
        opts = part.opts.lower()
        if "cdrom" in opts or not part.fstype:
            continue
        root = Path(part.mountpoint)
        if not root.exists():
            continue
        if str(root) not in {str(d) for d in drives}:
            drives.append(root)
    # Ensure the system drive is always present and first.
    if not any(str(d).lower().startswith(str(SYSTEM_DRIVE).lower()[:2]) for d in drives):
        drives.insert(0, SYSTEM_DRIVE)
    drives.sort(key=lambda p: (str(p)[:2].lower() != str(SYSTEM_DRIVE)[:2].lower(), str(p)))
    return drives


def drive_usage() -> list[dict]:
    """[{letter, total, used, free, percent}] for each fixed drive."""
    out: list[dict] = []
    for drive in fixed_drives():
        try:
            usage = psutil.disk_usage(str(drive))
        except OSError:
            continue
        out.append(
            {
                "letter": str(drive)[:2],
                "mount": str(drive),
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            }
        )
    return out


def quarantine_root_for(path: str | os.PathLike[str]) -> Path:
    """Quarantine lives on the same volume as the file, so moves are instant."""
    drive = os.path.splitdrive(os.path.abspath(str(path)))[0]
    home_drive = os.path.splitdrive(str(QUARANTINE))[0]
    if drive.lower() == home_drive.lower() or not drive:
        return QUARANTINE
    return Path(drive + "\\") / "$SweepQuarantine"


def windows_dir(*parts: str) -> Path:
    return WINDIR.joinpath(*parts)
