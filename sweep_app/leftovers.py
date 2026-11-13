"""Find AppData / ProgramData / Program Files folders that belong to nothing.

Uninstallers routinely leave a 200 MB folder behind. Sweep builds an index of
everything that *is* installed (registry uninstall entries, Program Files
folders, Start Menu shortcuts) and then flags candidate folders that match no
program name, publisher, product string or shortcut.
"""
from __future__ import annotations

import ctypes
import os
import struct
import threading
import time
import winreg
from ctypes import wintypes as w
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import paths, util

try:
    _version = ctypes.WinDLL("version", use_last_error=True)
except OSError:  # pragma: no cover
    _version = None

if _version is not None:
    _version.GetFileVersionInfoSizeW.argtypes = [w.LPCWSTR, ctypes.POINTER(w.DWORD)]
    _version.GetFileVersionInfoSizeW.restype = w.DWORD
    _version.GetFileVersionInfoW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID]
    _version.GetFileVersionInfoW.restype = w.BOOL
    _version.VerQueryValueW.argtypes = [
        w.LPCVOID,
        w.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(w.UINT),
    ]
    _version.VerQueryValueW.restype = w.BOOL

STOPWORDS = {
    "inc",
    "llc",
    "ltd",
    "corp",
    "corporation",
    "co",
    "company",
    "software",
    "technologies",
    "technology",
    "tech",
    "the",
    "and",
    "for",
    "app",
    "apps",
    "application",
    "suite",
    "pro",
    "premium",
    "free",
    "trial",
    "edition",
    "version",
    "x64",
    "x86",
    "win32",
    "win64",
    "update",
    "updater",
    "setup",
    "installer",
    "package",
    "packages",
    "service",
    "services",
    "driver",
    "drivers",
    "runtime",
    "library",
    "libraries",
    "tool",
    "tools",
    "utility",
    "utilities",
    "manager",
    "client",
    "server",
    "desktop",
    "player",
    "studio",
    "code",
    "editor",
    "browser",
    "helper",
    "host",
    "common",
    "shared",
    "components",
    "resources",
    "data",
    "files",
    "bin",
    "lib",
    "libs",
    "plugins",
    "config",
    "settings",
    "cache",
    "temp",
    "tmp",
}

# Never propose these, whatever the index says.
EXCLUDED_NAMES = {
    "microsoft",
    "windows",
    "packages",
    "temp",
    "tmp",
    "connecteddevicesplatform",
    "comms",
    "elevateddiagnostics",
    "placeholdertilelogofolder",
    "publish",
    "virtualstore",
    "programcompatibilityassistant",
    "history",
    "iconcache",
    "crashdumps",
    "d3dscache",
    "nvidia",
    "amd",
    "intel",
    "realtek",
    "pip",
    "nuget",
    "yarn",
    "go-build",
    "npm-cache",
    "sweep",
    "$sweepquarantine",
    "package cache",
    "common files",
    "internet explorer",
    "windowsapps",
    "windows defender",
    "windows nt",
    "windows mail",
    "windows media player",
    "windows portable devices",
    "windows sidebar",
    "windows journal",
    "windows photo viewer",
    "modifiablewindowsapps",
    "uninstall information",
    "msbuild",
    "reference assemblies",
    "dotnet",
    "microsoft.net",
    "windows powershell",
    "windows security",
    "windows kits",
    "windows software development kit",
    "windowsapps",
    "temp",
    "squirreltemp",
    "usoshared",
    "usoprivate",
    "usoclient",
    "uiu",
    "publishers",
    "toastnotificationmanagercompat",
    "soundresearch",
    "hpqlog",
    "pnpm",
    "pnpm-cache",
    "pnpm-state",
    "node-addon-native-custom-loader",
    "regid",
    "diagnostics",
    "whesvc",
    "tempstate",
    "programs",
    "local",
    "roaming",
    "low",
    "default",
    "public",
    "all users",
    "desktop",
    "documents",
    "downloads",
    "links",
    "start menu",
    "templates",
    "application data",
    "cookies",
    "netcache",
    "recent",
    "sendto",
    "start menu",
    "favorites",
    "my documents",
    # actively used developer / vendor folders that are not install leftovers
    "openai",
    "codex",
    "anthropic",
    "claude",
    "claude-code",
    "github",
    "git",
    "node",
    "nodejs",
    "npm",
    "cursor",
    "vscode",
    "code",
    "jetbrains",
    "docker",
    "wsl",
    "electron",
    "squirrel",
}

# A folder touched this recently is in use, whatever the index says.
FRESH_DAYS = 21

UNINSTALL_KEYS = (
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


@dataclass(frozen=True)
class Program:
    name: str
    publisher: str
    location: str
    source: str


@dataclass
class ProgramIndex:
    full_names: set[str]
    name_words: set[str]
    locations: set[str]
    publishers: set[str]

    @property
    def size(self) -> int:
        return len(self.full_names)


@dataclass
class Orphan:
    path: str
    name: str
    root_label: str
    size: int
    files: int
    mtime: float
    confidence: str  # orphan | suspect
    reason: str

    @property
    def last_used(self) -> str:
        return util.human_age(self.mtime)


def _read_value(key, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value or "").strip()


def installed_programs() -> list[Program]:
    programs: list[Program] = []
    seen: set[str] = set()
    for hive, subkey in UNINSTALL_KEYS:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as root:
                count = winreg.QueryInfoKey(root)[0]
                for index in range(count):
                    try:
                        child_name = winreg.EnumKey(root, index)
                        with winreg.OpenKey(root, child_name) as child:
                            display = _read_value(child, "DisplayName")
                            if not display:
                                continue
                            location = _read_value(child, "InstallLocation")
                            publisher = _read_value(child, "Publisher")
                    except OSError:
                        continue
                    key = util.norm(display) + "|" + util.norm(location)
                    if key in seen:
                        continue
                    seen.add(key)
                    programs.append(
                        Program(display, publisher, location, f"{hive}\\{subkey}\\{child_name}")
                    )
        except OSError:
            continue
    return programs


def _program_files_dirs() -> list[Path]:
    found: list[Path] = []
    for root in (paths.PROGRAM_FILES, paths.PROGRAM_FILES_X86, paths.LOCALAPPDATA / "Programs"):
        if not root.is_dir():
            continue
        for entry in util.safe_children(root):
            try:
                if entry.is_dir(follow_symlinks=False):
                    found.append(Path(util.strip_long(entry.path)))
            except OSError:
                continue
    return found


def _node_global_names() -> list[str]:
    """Globally installed npm/pnpm/bun/yarn packages are installed programs too."""
    bases: list[Path] = [
        paths.APPDATA / "npm" / "node_modules",
        paths.USERPROFILE / ".bun" / "install" / "global" / "node_modules",
        paths.LOCALAPPDATA / "Yarn" / "Data" / "global" / "node_modules",
    ]
    try:
        bases.extend((paths.LOCALAPPDATA / "pnpm" / "global").glob("*/node_modules"))
    except OSError:
        pass
    names: list[str] = []
    for base in bases:
        if not base.is_dir():
            continue
        for entry in util.safe_children(base):
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            names.append(entry.name.lstrip("@"))
            if entry.name.startswith("@"):
                for scoped in util.safe_children(entry.path):
                    try:
                        if scoped.is_dir(follow_symlinks=False):
                            names.append(scoped.name)
                    except OSError:
                        continue
    return names


def _start_menu_names() -> list[str]:
    names: list[str] = []
    for root in (paths.START_MENU_ALL, paths.START_MENU_USER):
        if not root.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(str(root)):
            for filename in filenames:
                if filename.lower().endswith(".lnk"):
                    names.append(os.path.splitext(filename)[0])
    return names


def build_index() -> ProgramIndex:
    full_names: set[str] = set()
    name_words: set[str] = set()
    locations: set[str] = set()
    publishers: set[str] = set()

    def add_name(text: str) -> None:
        normalized = util.norm(text)
        if len(normalized) >= 3:
            full_names.add(normalized)
        for word in util.words(text):
            if len(word) >= 3 and word not in STOPWORDS:
                name_words.add(word)

    for program in installed_programs():
        add_name(program.name)
        add_name(program.publisher)
        if program.publisher:
            publishers.add(util.norm(program.publisher))
        if program.location:
            base = os.path.basename(program.location.rstrip("\\/"))
            if base:
                add_name(base)
                locations.add(util.norm(program.location))
    for directory in _program_files_dirs():
        add_name(directory.name)
    for name in _start_menu_names():
        add_name(name)
    for name in _node_global_names():
        add_name(name)
    return ProgramIndex(full_names, name_words, locations, publishers)


def _version_string(path: str, key: str) -> str:
    if _version is None:
        return ""
    try:
        size = _version.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not _version.GetFileVersionInfoW(path, 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p()
        length = w.UINT()
        if not _version.VerQueryValueW(
            buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)
        ):
            return ""
        if length.value < 4 or not pointer.value:
            return ""
        language, codepage = struct.unpack("<HH", ctypes.string_at(pointer.value, 4))
        sub = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}"
        if not _version.VerQueryValueW(
            buffer, sub, ctypes.byref(pointer), ctypes.byref(length)
        ):
            return ""
        if not pointer.value:
            return ""
        return ctypes.wstring_at(pointer.value).rstrip("\x00")
    except (OSError, ValueError):
        return ""


def folder_company(path: Path) -> str:
    """CompanyName / ProductName from the first executable we can find."""
    try:
        entries = util.safe_children(path)
    except OSError:
        return ""
    candidates = [e for e in entries if e.name.lower().endswith((".exe", ".dll"))]
    for entry in candidates[:6]:
        company = _version_string(util.strip_long(entry.path), "CompanyName")
        product = _version_string(util.strip_long(entry.path), "ProductName")
        if company or product:
            return f"{company} {product}".strip()
    return ""


def _match_strength(
    name: str, index: ProgramIndex, company: str
) -> str:
    normalized = util.norm(name)
    if not normalized:
        return "strong"
    if normalized in index.full_names:
        return "strong"
    if len(normalized) >= 4:
        for candidate in index.full_names:
            if len(candidate) >= 4 and (
                candidate.startswith(normalized) or normalized.startswith(candidate)
            ):
                return "strong"
    folder_words = {w for w in util.words(name) if len(w) >= 3 and w not in STOPWORDS}
    if folder_words & index.name_words:
        if any(len(w) >= 5 for w in folder_words & index.name_words):
            return "strong"
        return "weak"
    if company:
        company_words = {w for w in util.words(company) if len(w) >= 3 and w not in STOPWORDS}
        if company_words & index.name_words:
            return "strong"
        if company_words & index.publishers:
            return "strong"
        if util.norm(company) in index.publishers:
            return "strong"
    return "none"


SCAN_ROOTS: tuple[tuple[Path, str], ...] = (
    (paths.LOCALAPPDATA, "LocalAppData"),
    (paths.APPDATA, "Roaming"),
    (paths.LOCALAPPDATA / "Programs", "Local Programs"),
    (paths.PROGRAMDATA, "ProgramData"),
    (paths.PROGRAM_FILES, "Program Files"),
    (paths.PROGRAM_FILES_X86, "Program Files (x86)"),
)


def scan_orphans(
    cancel: threading.Event | None = None,
    progress: Callable[[str, float], None] | None = None,
    index: ProgramIndex | None = None,
) -> list[Orphan]:
    index = index or build_index()
    roots = [(root, label) for root, label in SCAN_ROOTS if root.is_dir()]
    total_roots = max(1, len(roots))
    found: list[Orphan] = []

    for root_index, (root, label) in enumerate(roots):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(f"Checking {label}", root_index / total_roots)
        try:
            entries = util.safe_children(root)
        except OSError:
            continue
        for entry in entries:
            if cancel is not None and cancel.is_set():
                break
            try:
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            name = entry.name
            lowered = name.lower()
            if lowered.startswith(".") or lowered in EXCLUDED_NAMES:
                continue
            if lowered.endswith((".log", ".tmp", ".ini", ".dat")):
                continue
            path = Path(util.strip_long(entry.path))
            if util.is_within(path, paths.SWEEP_HOME):
                continue
            strength = _match_strength(name, index, "")
            if strength == "strong":
                continue
            # Only pay for version-info reads on folders that already look odd.
            company = folder_company(path)
            if company:
                strength = _match_strength(name, index, company)
                if strength == "strong":
                    continue
            try:
                stat = entry.stat(follow_symlinks=False)
                mtime = stat.st_mtime
            except OSError:
                mtime = 0.0
            if mtime and (time.time() - mtime) < FRESH_DAYS * 86400:
                continue
            size, files = util.dir_stats(path, cancel)
            if files == 0 and size == 0:
                continue
            confidence = "orphan" if strength == "none" else "suspect"
            reason = (
                "no installed program, shortcut or publisher matches this folder"
                if confidence == "orphan"
                else "only a weak name match; verify before removing"
            )
            found.append(
                Orphan(
                    path=str(path),
                    name=name,
                    root_label=label,
                    size=size,
                    files=files,
                    mtime=mtime,
                    confidence=confidence,
                    reason=reason,
                )
            )
        if progress:
            progress(f"Checked {label}", (root_index + 1) / total_roots)

    found.sort(key=lambda o: (-o.size, o.name.lower()))
    return found


def open_hit(path: str) -> None:
    util.open_in_explorer(path)


def folder_count() -> int:
    return sum(1 for root, _ in SCAN_ROOTS if root.is_dir())
