"""Search the whole PC for a program's files, then remove what was found.

Used by the "Remove a program" tab: type a name, get every matching folder,
file, registry entry and service, then quarantine the selection.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

import psutil

from . import paths, procs, safety, util

CREATE_NO_WINDOW = 0x08000000

# Folders that never contain useful user-facing program files, and are huge.
PRUNE_NAMES = {
    "windows",
    "winsxs",
    "system32",
    "syswow64",
    "$recycle.bin",
    "system volume information",
    "driverstore",
    "drivers",
    "assembly",
    "servicing",
    "installer",
    "windowsapps",
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "site-packages",
    "$sweepquarantine",
    "$windows.~bt",
    "$windows.~ws",
    "windows.old",
    "prefetch",
    "softwaredistribution",
    "panther",
    "minidump",
    "livekernelreports",
    "catroot",
    "catroot2",
    "config",
    "winsxs",
    "temp",
    "tmp",
    "cache",
    "code cache",
    "gpucache",
}

MAX_DEPTH = 12
MAX_HITS = 400


@dataclass
class Hit:
    kind: str  # folder | file | registry | service
    name: str
    path: str
    size: int = 0
    mtime: float = 0.0
    extra: str = ""
    key: str = ""

    @property
    def kind_label(self) -> str:
        return {
            "folder": "Folder",
            "file": "File",
            "registry": "Registry",
            "service": "Service",
        }.get(self.kind, self.kind.title())

    @property
    def age_label(self) -> str:
        return util.human_age(self.mtime) if self.mtime else "—"


@dataclass
class SearchOutcome:
    hits: list[Hit] = field(default_factory=list)
    scanned: int = 0
    elapsed: float = 0.0
    cancelled: bool = False


def _norm_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _drive_roots() -> list[Path]:
    return paths.fixed_drives()


def search_files(
    query: str,
    cancel: threading.Event | None = None,
    progress: Callable[[str, float], None] | None = None,
) -> SearchOutcome:
    started = time.perf_counter()
    outcome = SearchOutcome()
    query = (query or "").strip()
    if len(util.norm(query)) < 2:
        return outcome

    drives = _drive_roots()
    if not drives:
        return outcome

    for drive_index, drive in enumerate(drives):
        if cancel is not None and cancel.is_set():
            outcome.cancelled = True
            break
        base_depth = str(drive).rstrip("\\/").count(os.sep)
        for dirpath, dirnames, filenames in os.walk(util.long_path(drive)):
            if cancel is not None and cancel.is_set():
                outcome.cancelled = True
                break
            if len(outcome.hits) >= MAX_HITS:
                break
            clean = util.strip_long(dirpath)
            depth = clean.rstrip("\\/").count(os.sep) - base_depth
            if depth >= MAX_DEPTH:
                dirnames[:] = []
                continue
            if progress and outcome.scanned % 250 == 0:
                progress(
                    f"Scanning {clean}",
                    (drive_index + (depth / MAX_DEPTH)) / max(1, len(drives)),
                )
            outcome.scanned += 1

            keep_dirs: list[str] = []
            for dirname in dirnames:
                lowered = dirname.lower()
                if lowered in PRUNE_NAMES or lowered.startswith("$"):
                    continue
                child = os.path.join(clean, dirname)
                if util.looks_like_name(query, dirname):
                    size, files = util.dir_stats(child, cancel)
                    outcome.hits.append(
                        Hit(
                            kind="folder",
                            name=dirname,
                            path=child,
                            size=size,
                            mtime=_mtime(child),
                            extra=f"{files:,} file" + ("" if files == 1 else "s"),
                        )
                    )
                    continue  # matched folder: don't list every child
                keep_dirs.append(dirname)
            dirnames[:] = keep_dirs

            if depth >= MAX_DEPTH - 1:
                continue
            for filename in filenames:
                if len(outcome.hits) >= MAX_HITS:
                    break
                if util.looks_like_name(query, filename):
                    child = os.path.join(clean, filename)
                    outcome.hits.append(
                        Hit(
                            kind="file",
                            name=filename,
                            path=child,
                            size=util.file_size(child),
                            mtime=_mtime(child),
                        )
                    )

    outcome.elapsed = time.perf_counter() - started
    return outcome


def _mtime(path: str) -> float:
    try:
        return os.stat(util.long_path(path)).st_mtime
    except OSError:
        return 0.0


def registry_hits(query: str) -> list[Hit]:
    from .leftovers import installed_programs

    hits: list[Hit] = []
    for program in installed_programs():
        if util.looks_like_name(query, program.name) or util.looks_like_name(
            query, program.publisher
        ):
            hits.append(
                Hit(
                    kind="registry",
                    name=program.name,
                    path=program.source,
                    extra=program.location or program.publisher,
                )
            )
    return hits


def service_hits(query: str) -> list[Hit]:
    hits: list[Hit] = []
    try:
        services = psutil.win_service_iter()
    except (psutil.Error, OSError, AttributeError):
        return hits
    for service in services:
        try:
            name = service.name()
            display = service.display_name()
        except (psutil.Error, OSError):
            continue
        if util.looks_like_name(query, display) or util.looks_like_name(query, name):
            try:
                status = service.status()
            except (psutil.Error, OSError):
                status = ""
            hits.append(
                Hit(kind="service", name=display or name, path=name, extra=status)
            )
    return hits


def matching_processes(query: str) -> list[procs.ProcessInfo]:
    matches: list[procs.ProcessInfo] = []
    for info in procs.collect():
        if info.protected:
            continue
        haystack = f"{info.name} {info.exe} {info.cmdline}"
        if util.looks_like_name(query, info.name) or util.looks_like_name(query, haystack):
            matches.append(info)
    return matches


# --------------------------------------------------------------------------- #
# registry / service removal
# --------------------------------------------------------------------------- #
HIVES = {
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
}


def _split_key(keypath: str) -> tuple[int, str]:
    for prefix, hive in HIVES.items():
        if keypath.upper().startswith(prefix + "\\"):
            return hive, keypath[len(prefix) + 1 :]
    raise ValueError(f"unsupported registry path: {keypath}")


def export_registry_key(keypath: str, destination: Path) -> tuple[bool, str]:
    util.ensure_parent(destination)
    try:
        result = subprocess.run(
            ["reg", "export", keypath, str(destination), "/y"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:200]
    return True, ""


def delete_registry_key(keypath: str) -> tuple[bool, str]:
    try:
        hive, subkey = _split_key(keypath)
    except ValueError as exc:
        return False, str(exc)

    def _recurse(root: int, path: str) -> None:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _recurse(root, path + "\\" + child)
        winreg.DeleteKey(root, path)

    try:
        _recurse(hive, subkey)
        return True, ""
    except OSError as exc:
        return False, str(exc)


def delete_service(name: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["sc", "delete", name],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:200]
    return True, ""


def stop_service(name: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["sc", "stop", name],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:200]
    return True, ""


# --------------------------------------------------------------------------- #
# removal
# --------------------------------------------------------------------------- #
@dataclass
class RemovalReport:
    moved: int = 0
    deleted: int = 0
    failed: int = 0
    skipped: int = 0
    bytes: int = 0
    registry: int = 0
    services: int = 0
    errors: list[str] = field(default_factory=list)
    batch_id: str = ""


def remove_hits(
    hits: Iterable[Hit],
    mode: str = "quarantine",
    cancel: threading.Event | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    backup_registry: bool = True,
) -> RemovalReport:
    hits = list(hits)
    report = RemovalReport()
    deleter = safety.Deleter(mode=mode, note="program removal")
    report.batch_id = deleter.batch_id
    total = len(hits)

    for index, hit in enumerate(hits, start=1):
        if cancel is not None and cancel.is_set():
            break
        if hit.kind in ("folder", "file"):
            allowed = [hit.path]
            result = deleter.delete(
                hit.path,
                allowed_roots=allowed,
                category="app-remover",
                allow_equal_root=True,
                cancel=cancel,
            )
            if result.status in ("moved", "deleted"):
                if result.status == "moved":
                    report.moved += 1
                else:
                    report.deleted += 1
                report.bytes += result.size
            elif result.status == "failed":
                report.failed += 1
                if result.reason and len(report.errors) < 10:
                    report.errors.append(f"{hit.name}: {result.reason}")
            else:
                report.skipped += 1
        elif hit.kind == "registry":
            if backup_registry:
                filename = (util.norm(hit.name)[:40] or "key") + ".reg"
                backup = paths.QUARANTINE / deleter.batch_id / "registry" / filename
                ok, error = export_registry_key(hit.path, backup)
                if not ok:
                    report.failed += 1
                    if len(report.errors) < 10:
                        report.errors.append(f"registry backup failed: {error}")
                    continue
            ok, error = delete_registry_key(hit.path)
            if ok:
                report.registry += 1
                safety.log_event("registry-delete", hit.path)
            else:
                report.failed += 1
                if len(report.errors) < 10:
                    report.errors.append(f"registry: {error}")
        elif hit.kind == "service":
            _stop_ok, stop_error = stop_service(hit.path)
            ok, error = delete_service(hit.path)
            if ok:
                report.services += 1
                safety.log_event("service-delete", hit.path)
            else:
                report.failed += 1
                if len(report.errors) < 10:
                    report.errors.append(f"service {hit.path}: {error or stop_error}")
        if progress:
            progress(index, total, hit.name)

    deleter.finish()
    return report
