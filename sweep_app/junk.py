"""Junk catalogue: every category knows exactly which folders it may empty."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import paths, safety, util
from .admin import is_admin

RISK_ORDER = {"safe": 0, "caution": 1, "risky": 2}


def _existing(candidates: list[Path]) -> list[Path]:
    out: list[Path] = []
    for c in candidates:
        try:
            if c.exists():
                out.append(c)
        except OSError:
            continue
    return out


def _children(root: Path, include_dirs: bool = True) -> list[Path]:
    """Top-level entries of *root* — the root itself is kept."""
    out: list[Path] = []
    for entry in util.safe_children(root):
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if is_dir and not include_dirs:
            continue
        out.append(Path(util.strip_long(entry.path)))
    return out


def _caches(roots: list[Path]) -> tuple[list[Path], list[Path]]:
    """(approved roots, children to delete) for cache folders."""
    roots = _existing(roots)
    items: list[Path] = []
    for root in roots:
        items.extend(_children(root))
    return roots, items


def _whole_dirs(roots: list[Path]) -> tuple[list[Path], list[Path]]:
    """Delete entire folders (roots may equal items)."""
    roots = _existing(roots)
    return roots, list(roots)


def _glob_dirs(patterns: list[str]) -> list[Path]:
    found: list[Path] = []
    for pattern in patterns:
        expanded = os.path.expandvars(pattern)
        try:
            found.extend(Path(p) for p in __import__("glob").glob(expanded))
        except OSError:
            continue
    return _existing(found)


# --------------------------------------------------------------------------- #
# category definitions
# --------------------------------------------------------------------------- #
def _user_temp() -> tuple[list[Path], list[Path]]:
    roots = _existing([paths.TEMP, paths.TMP])
    items: list[Path] = []
    for root in roots:
        for child in _children(root):
            # never touch our own holding area if someone redirects TEMP there
            if util.is_within(child, paths.SWEEP_HOME):
                continue
            items.append(child)
    return roots, items


def _win_temp() -> tuple[list[Path], list[Path]]:
    return _caches(_existing([paths.WINDIR / "Temp", paths.WINDIR / "SystemTemp"]))


def _prefetch() -> tuple[list[Path], list[Path]]:
    root = paths.WINDIR / "Prefetch"
    return _caches(_existing([root]))


def _update_cache() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.WINDIR / "SoftwareDistribution" / "Download",
                paths.WINDIR / "SoftwareDistribution" / "DeliveryOptimization",
            ]
        )
    )


def _delivery_opt() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.WINDIR
                / "ServiceProfiles"
                / "NetworkService"
                / "AppData"
                / "Local"
                / "Microsoft"
                / "Windows"
                / "DeliveryOptimization",
                paths.WINDIR / "SoftwareDistribution" / "DeliveryOptimization",
            ]
        )
    )


def _windows_old() -> tuple[list[Path], list[Path]]:
    candidates = [
        Path(str(paths.SYSTEM_DRIVE) + "Windows.old"),
        Path(str(paths.SYSTEM_DRIVE) + "$WINDOWS.~BT"),
        Path(str(paths.SYSTEM_DRIVE) + "$WINDOWS.~WS"),
        Path(str(paths.SYSTEM_DRIVE) + "$GetCurrent"),
        Path(str(paths.SYSTEM_DRIVE) + "$SysReset"),
    ]
    return _whole_dirs(candidates)


def _crash_dumps() -> tuple[list[Path], list[Path]]:
    roots = _existing(
        [
            paths.LOCALAPPDATA / "CrashDumps",
            paths.WINDIR / "Minidump",
            paths.WINDIR / "LiveKernelReports",
        ]
    )
    items: list[Path] = []
    for root in roots:
        items.extend(_children(root))
    for dump in (paths.WINDIR / "MEMORY.DMP", paths.WINDIR / "memory.dmp"):
        if dump.exists():
            items.append(dump)
    return roots, items


def _wer() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.LOCALAPPDATA / "Microsoft" / "Windows" / "WER",
                paths.PROGRAMDATA / "Microsoft" / "Windows" / "WER",
                paths.WINDIR / "WER",
            ]
        )
    )


def _thumbnails() -> tuple[list[Path], list[Path]]:
    root = paths.LOCALAPPDATA / "Microsoft" / "Windows" / "Explorer"
    if not root.exists():
        return [], []
    items: list[Path] = []
    for entry in util.safe_children(root):
        name = entry.name.lower()
        if name.startswith(("thumbcache_", "iconcache_")) and name.endswith(".db"):
            items.append(Path(util.strip_long(entry.path)))
    return [root], items


def _inetcache() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.LOCALAPPDATA / "Microsoft" / "Windows" / "INetCache",
                paths.LOCALAPPDATA / "Microsoft" / "Windows" / "INetCookies",
                paths.LOCALAPPDATA / "Microsoft" / "Windows" / "WebCache",
            ]
        )
    )


_BROWSER_CACHE_DIRS = [
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "GrShaderCache",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    "Media Cache",
]


def _browser_cache() -> tuple[list[Path], list[Path]]:
    roots: list[Path] = []
    chromium_bases = [
        paths.LOCALAPPDATA / "Google" / "Chrome" / "User Data",
        paths.LOCALAPPDATA / "Microsoft" / "Edge" / "User Data",
        paths.LOCALAPPDATA / "BraveSoftware" / "Brave-Browser" / "User Data",
        paths.LOCALAPPDATA / "Vivaldi" / "User Data",
        paths.LOCALAPPDATA / "Chromium" / "User Data",
        paths.APPDATA / "Opera Software" / "Opera Stable",
        paths.APPDATA / "Opera Software" / "Opera GX Stable",
        paths.APPDATA / "Opera Software" / "Opera Crypto Stable",
    ]
    for base in chromium_bases:
        if not base.exists():
            continue
        profiles = [base]
        try:
            profiles.extend([p for p in base.iterdir() if p.is_dir()])
        except OSError:
            pass
        for profile in profiles:
            for name in _BROWSER_CACHE_DIRS:
                candidate = profile / name
                if candidate.is_dir():
                    roots.append(candidate)
            service_worker = profile / "Service Worker" / "CacheStorage"
            if service_worker.is_dir():
                roots.append(service_worker)
    # Firefox keeps caches outside the profile folder.
    firefox = paths.LOCALAPPDATA / "Mozilla" / "Firefox" / "Profiles"
    if firefox.is_dir():
        try:
            for profile in firefox.iterdir():
                for name in ("cache2", "startupCache", "thumbnails", "shader-cache"):
                    candidate = profile / name
                    if candidate.is_dir():
                        roots.append(candidate)
        except OSError:
            pass
    return _caches(roots)


def _shader_cache() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.LOCALAPPDATA / "D3DSCache",
                paths.LOCALAPPDATA / "NVIDIA" / "DXCache",
                paths.LOCALAPPDATA / "NVIDIA" / "GLCache",
                paths.LOCALAPPDATA / "NVIDIA" / "ComputeCache",
                paths.LOCALAPPDATA / "NVIDIA" / "OptixCache",
                paths.LOCALAPPDATA / "AMD" / "DxCache",
                paths.LOCALAPPDATA / "AMD" / "DxcCache",
                paths.LOCALAPPDATA / "AMD" / "GLCache",
                paths.LOCALAPPDATA / "Intel" / "ShaderCache",
                paths.LOCALAPPDATA / "Microsoft" / "DirectX" / "ShaderCache",
            ]
        )
    )


def _windows_logs() -> tuple[list[Path], list[Path]]:
    roots = _existing(
        [
            paths.WINDIR / "Logs" / "CBS",
            paths.WINDIR / "Logs" / "DISM",
            paths.WINDIR / "Logs" / "WindowsUpdate",
            paths.WINDIR / "Logs" / "MoSetup",
            paths.WINDIR / "Logs" / "SIH",
            paths.WINDIR / "Panther",
            paths.WINDIR / "SoftwareDistribution" / "Logs",
        ]
    )
    items: list[Path] = []
    for root in roots:
        items.extend(_children(root))
    return roots, items


def _dev_caches() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.LOCALAPPDATA / "pip" / "Cache",
                paths.APPDATA / "npm-cache",
                paths.LOCALAPPDATA / "npm-cache",
                paths.LOCALAPPDATA / "NuGet" / "v3-cache",
                paths.LOCALAPPDATA / "NuGet" / "plugins-cache",
                paths.LOCALAPPDATA / "Yarn" / "Cache",
                paths.LOCALAPPDATA / "go-build",
                paths.LOCALAPPDATA / "pnpm" / "store" / "v3" / "files",
                paths.LOCALAPPDATA / "Electron" / "Cache",
                paths.LOCALAPPDATA / "Electron" / "CachedData",
            ]
        )
    )


def _build_caches() -> tuple[list[Path], list[Path]]:
    return _caches(
        _existing(
            [
                paths.USERPROFILE / ".cargo" / "registry" / "cache",
                paths.USERPROFILE / ".gradle" / "caches",
                paths.USERPROFILE / ".m2" / "repository" / ".cache",
                paths.USERPROFILE / ".nuget" / "packages",
            ]
        )
    )


def _installer_patch() -> tuple[list[Path], list[Path]]:
    return _whole_dirs(_existing([paths.WINDIR / "Installer" / "$PatchCache$"]))


def _package_cache() -> tuple[list[Path], list[Path]]:
    return _caches(_existing([paths.PROGRAMDATA / "Package Cache"]))


def _recycle() -> tuple[list[Path], list[Path]]:
    return [], []


@dataclass(frozen=True)
class Category:
    key: str
    title: str
    blurb: str
    risk: str
    admin: bool
    default: bool
    spec: Callable[[], tuple[list[Path], list[Path]]]
    note: str = ""
    kind: str = "files"  # files | recycle


CATEGORIES: tuple[Category, ...] = (
    Category(
        "user_temp",
        "User temp files",
        "%TEMP% — installer scraps, app scratch files, stale downloads",
        "safe",
        False,
        True,
        _user_temp,
        note="Files in use are skipped automatically.",
    ),
    Category(
        "win_temp",
        "Windows temp",
        "C:\\Windows\\Temp — system-level scratch space",
        "safe",
        True,
        True,
        _win_temp,
    ),
    Category(
        "prefetch",
        "Prefetch cache",
        "C:\\Windows\\Prefetch — boot/launch traces, rebuilt on demand",
        "safe",
        True,
        True,
        _prefetch,
        note="The first launch of each app is slightly slower afterwards.",
    ),
    Category(
        "update_cache",
        "Windows Update cache",
        "Downloaded update payloads that were already installed",
        "safe",
        True,
        True,
        _update_cache,
        note="Safe once updates are installed; Windows re-downloads if needed.",
    ),
    Category(
        "delivery_opt",
        "Delivery Optimization",
        "Peer-to-peer update chunks cached on this PC",
        "safe",
        True,
        True,
        _delivery_opt,
    ),
    Category(
        "windows_old",
        "Old Windows / upgrade leftovers",
        "Windows.old, $WINDOWS.~BT, $WINDOWS.~WS, $GetCurrent",
        "risky",
        True,
        False,
        _windows_old,
        note="Removes the option to roll back to the previous Windows build.",
    ),
    Category(
        "crash_dumps",
        "Crash dumps & kernel reports",
        "CrashDumps, Minidump, LiveKernelReports, MEMORY.DMP",
        "caution",
        True,
        True,
        _crash_dumps,
        note="Useful for debugging a BSOD; otherwise pure dead weight.",
    ),
    Category(
        "wer",
        "Error reporting queue",
        "Windows Error Reporting archives and queued reports",
        "safe",
        False,
        True,
        _wer,
    ),
    Category(
        "thumbnails",
        "Thumbnail & icon cache",
        "thumbcache_*.db / iconcache_*.db — regenerated by Explorer",
        "safe",
        False,
        True,
        _thumbnails,
        note="Locked by Explorer; restart Explorer to clear them completely.",
    ),
    Category(
        "inetcache",
        "Internet cache (WinINet)",
        "INetCache / cookies / WebCache used by classic Windows apps",
        "safe",
        False,
        True,
        _inetcache,
    ),
    Category(
        "browser_cache",
        "Browser caches",
        "Chrome, Edge, Brave, Vivaldi, Opera, Firefox cache folders only",
        "caution",
        False,
        True,
        _browser_cache,
        note="Bookmarks, history, passwords and profiles are untouched.",
    ),
    Category(
        "shader_cache",
        "GPU shader caches",
        "DirectX, NVIDIA, AMD and Intel compiled shader stores",
        "safe",
        False,
        True,
        _shader_cache,
    ),
    Category(
        "windows_logs",
        "Windows logs",
        "CBS, DISM, WindowsUpdate, Panther setup logs",
        "safe",
        True,
        True,
        _windows_logs,
    ),
    Category(
        "dev_caches",
        "Developer package caches",
        "pip, npm, NuGet, Yarn, Go, Electron, pnpm caches",
        "caution",
        False,
        True,
        _dev_caches,
        note="Re-downloaded automatically on the next build/install.",
    ),
    Category(
        "build_caches",
        "Compiler caches (Cargo, Gradle, Maven, NuGet)",
        "Local build caches — large, but slow to rebuild",
        "caution",
        False,
        False,
        _build_caches,
    ),
    Category(
        "installer_patch",
        "Installer patch cache",
        "C:\\Windows\\Installer\\$PatchCache$",
        "risky",
        True,
        False,
        _installer_patch,
        note="Some MSI repair/uninstall operations may need the source media.",
    ),
    Category(
        "package_cache",
        "ProgramData package cache",
        "C:\\ProgramData\\Package Cache — installers cached by Visual Studio etc.",
        "risky",
        True,
        False,
        _package_cache,
        note="Breaks repair/uninstall for the products that own these bundles.",
    ),
    Category(
        "recycle_bin",
        "Recycle Bin",
        "Emptied through the shell API, per-user and per-drive",
        "safe",
        False,
        True,
        _recycle,
        kind="recycle",
    ),
)

CATEGORY_MAP: dict[str, Category] = {c.key: c for c in CATEGORIES}


@dataclass
class CategoryScan:
    key: str
    size: int = 0
    files: int = 0
    status: str = "ok"  # ok | empty | error | needs-admin
    detail: str = ""
    items: int = 0

    @property
    def has_content(self) -> bool:
        return self.size > 0 or self.items > 0


def scan_category(
    category: Category,
    cancel: threading.Event | None = None,
) -> CategoryScan:
    result = CategoryScan(category.key)
    if category.kind == "recycle":
        size, files = safety.recycle_bin_size(cancel)
        result.size, result.files = size, files
        result.items = 1 if size else 0
        result.status = "ok" if size else "empty"
        return result

    try:
        roots, items = category.spec()
    except OSError as exc:
        result.status = "error"
        result.detail = str(exc)
        return result

    if not roots:
        result.status = "empty"
        return result

    total = 0
    files = 0
    for item in items:
        if cancel is not None and cancel.is_set():
            break
        size, count = util.path_stats(item, cancel)
        total += size
        files += count
    result.size = total
    result.files = files
    result.items = len(items)
    if category.admin and not is_admin():
        result.status = "needs-admin"
    elif not items:
        result.status = "empty"
    return result


def scan_all(
    categories: list[Category] | tuple[Category, ...] = CATEGORIES,
    cancel: threading.Event | None = None,
    on_result: Callable[[CategoryScan], None] | None = None,
) -> dict[str, CategoryScan]:
    results: dict[str, CategoryScan] = {}
    for category in categories:
        if cancel is not None and cancel.is_set():
            break
        scan = scan_category(category, cancel)
        results[category.key] = scan
        if on_result:
            on_result(scan)
    return results


def delete_targets(category: Category) -> tuple[list[Path], list[Path]]:
    """Fresh roots/items used right before deletion."""
    return category.spec()


@dataclass
class CleanOutcome:
    category: str
    stats: safety.BatchStats = field(default_factory=safety.BatchStats)
    recycle: bool = False
    message: str = ""
