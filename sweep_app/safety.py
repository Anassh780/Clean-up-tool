"""The blast-radius limiter.

Every destructive action in Sweep goes through :class:`Deleter`, which enforces
three rules before touching the filesystem:

1. the target must live inside a folder set the caller explicitly approved;
2. the target must not be a Windows / profile / credential critical path;
3. files are moved to a per-volume quarantine (restorable) unless the user
   deliberately switched the app into permanent-delete mode.

Nothing else in the codebase calls ``os.remove`` / ``shutil.rmtree``.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from . import paths, util

# --------------------------------------------------------------------------- #
# protected locations
# --------------------------------------------------------------------------- #
_W = paths.WINDIR
_UP = paths.USERPROFILE
_LA = paths.LOCALAPPDATA
_RA = paths.APPDATA
_PD = paths.PROGRAMDATA
_PF = paths.PROGRAM_FILES
_PF86 = paths.PROGRAM_FILES_X86


def _p(*parts: str | os.PathLike[str]) -> str:
    return os.path.abspath(os.path.join(str(parts[0]), *map(str, parts[1:])))


# Whole trees that must never lose files, no matter which feature asks.
PROTECTED_TREES: tuple[str, ...] = tuple(
    _p(*parts)
    for parts in (
        (_W, "System32"),
        (_W, "SysWOW64"),
        (_W, "WinSxS"),
        (_W, "Fonts"),
        (_W, "assembly"),
        (_W, "servicing"),
        (_W, "Installer"),
        (_W, "Boot"),
        (_W, "security"),
        (_W, "SystemApps"),
        (_W, "SystemResources"),
        (_W, "Microsoft.NET"),
        (_W, "PolicyDefinitions"),
        (_W, "Resources"),
        (_W, "Globalization"),
        (_W, "IME"),
        (_W, "Speech"),
        (_W, "Speech_OneCore"),
        (_W, "Web"),
        (_W, "WinMetadata"),
        (_W, "Branding"),
        (_W, "Media"),
        (_W, "System32", "config"),
        (_W, "System32", "drivers"),
        (_W, "System32", "DriverStore"),
        (_W, "System32", "CatRoot"),
        (_W, "System32", "CatRoot2"),
        (_PF, "WindowsApps"),
        (_UP, "Desktop"),
        (_UP, "Documents"),
        (_UP, "Downloads"),
        (_UP, "Pictures"),
        (_UP, "Music"),
        (_UP, "Videos"),
        (_UP, "OneDrive"),
        (_UP, "Saved Games"),
        (_UP, "Contacts"),
        (_UP, "Favorites"),
        (_UP, "Links"),
        (_UP, "Searches"),
        (_UP, "3D Objects"),
        (_UP, ".ssh"),
        (_UP, ".gnupg"),
        (_UP, ".aws"),
        (_RA, "Microsoft", "Crypto"),
        (_RA, "Microsoft", "Protect"),
        (_RA, "Microsoft", "Credentials"),
        (_LA, "Microsoft", "Credentials"),
        (_LA, "Microsoft", "Vault"),
        (_PD, "Microsoft", "Windows", "System32"),
    )
)

# Only the exact path is protected; children are fair game.
PROTECTED_EXACT: tuple[str, ...] = tuple(
    _p(*parts)
    for parts in (
        (_UP,),
        (_LA,),
        (_RA,),
        (_PD,),
        (_PF,),
        (_PF86,),
        (_W,),
        (_W, "Logs"),
        (_LA, "Microsoft"),
        (_RA, "Microsoft"),
        (_PD, "Microsoft"),
    )
)

PROTECTED_NAMES: frozenset[str] = frozenset(
    {
        "pagefile.sys",
        "hiberfil.sys",
        "swapfile.sys",
        "bootmgr",
        "bootnxt",
        "ntldr",
        "boot.ini",
        "ntuser.dat",
        "ntuser.ini",
        "usrclass.dat",
        "sam",
        "security",
        "software",
        "system",
        "desktop.ini",
    }
)

PROTECTED_PARTS_ANYWHERE: frozenset[str] = frozenset(
    {"system volume information", "$recycle.bin", "$extend"}
)
PROTECTED_DRIVE_CHILDREN: frozenset[str] = frozenset({"recovery", "efi", "boot", "bootmgr"})


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def blocked_reason(path: str | os.PathLike[str]) -> str | None:
    """Return a human reason when *path* must never be deleted."""
    raw = os.path.abspath(str(path))
    p = _norm(raw)
    drive, tail = os.path.splitdrive(p)
    if tail.strip("\\/") == "":
        return "drive roots are never touched"
    try:
        parts = [part.lower() for part in Path(raw).parts]
    except (ValueError, OSError):
        return "unparseable path"
    if any(part in PROTECTED_PARTS_ANYWHERE for part in parts[1:]):
        return "protected system area"
    if len(parts) > 1 and parts[1] in PROTECTED_DRIVE_CHILDREN:
        return "protected boot area"
    name = os.path.basename(raw).lower()
    if name in PROTECTED_NAMES:
        return "protected system file"
    if name.endswith((".dat", ".dit")) and any(p in ("config", "system32") for p in parts):
        return "registry hive"
    for root in PROTECTED_EXACT:
        if p == _norm(root):
            return "protected root folder"
    for root in PROTECTED_TREES:
        if util.is_within(p, root):
            return "protected system folder"
    return None


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
@dataclass
class DeleteResult:
    path: str
    status: str  # moved | deleted | skipped | failed | missing
    size: int = 0
    reason: str = ""
    # One {"path", "reason"} entry per file that could not be moved, so the
    # interface can name every locked file instead of one opaque message.
    failures: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in ("moved", "deleted")


@dataclass
class BatchStats:
    moved: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    bytes: int = 0
    errors: list[str] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)

    def add(self, result: DeleteResult) -> None:
        if result.status == "moved":
            self.moved += 1
            self.bytes += result.size
        elif result.status == "deleted":
            self.deleted += 1
            self.bytes += result.size
        elif result.status == "failed":
            self.failed += 1
            self.bytes += result.size
            for failure in result.failures:
                entry = dict(failure)
                entry.setdefault("parent", result.path)
                self.failures.append(entry)
            if result.reason and len(self.errors) < 40:
                self.errors.append(
                    f"{util.middle_truncate(result.path, 70)} — {result.reason}"
                )
        else:
            self.skipped += 1


# --------------------------------------------------------------------------- #
# quarantine batches
# --------------------------------------------------------------------------- #
def _batch_dir(batch_id: str) -> Path:
    return paths.QUARANTINE / batch_id


def _manifest_path(batch_id: str) -> Path:
    return _batch_dir(batch_id) / "_batch.json"


def quarantine_batches() -> list[dict]:
    """Newest first. Each entry is the batch manifest plus ``dir``."""
    out: list[dict] = []
    root = paths.QUARANTINE
    if not root.exists():
        return out
    try:
        entries = list(root.iterdir())
    except OSError:
        return out
    for entry in entries:
        manifest = entry / "_batch.json"
        if not manifest.is_file():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data["dir"] = str(entry)
        data.setdefault("items", [])
        out.append(data)
    out.sort(key=lambda b: b.get("created", ""), reverse=True)
    return out


def quarantine_usage() -> tuple[int, int]:
    total = 0
    items = 0
    for batch in quarantine_batches():
        for item in batch.get("items", []):
            total += int(item.get("size") or 0)
            items += 1
    return total, items


def restore_batch(
    batch_id: str,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[int, int]:
    """Move a batch back where it came from. Returns (restored, failed)."""
    manifest = _manifest_path(batch_id)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, 0
    items = sorted(data.get("items", []), key=lambda it: len(it.get("src", "")))
    restored = failed = 0
    total = len(items)
    for index, item in enumerate(items, start=1):
        src = item.get("src")
        dst = item.get("dst")
        if not src or not dst:
            failed += 1
            continue
        try:
            if util.path_exists(src):
                failed += 1
            elif not util.path_exists(dst):
                failed += 1
            else:
                util.ensure_parent(src)
                util.move_path(dst, src)
                restored += 1
                log_event("restore", f"{src}")
        except OSError as exc:
            failed += 1
            log_event("restore-failed", f"{src} :: {exc}", ok=False)
        if progress:
            progress(index, total, src)
    # Drop restored entries from the manifest so the batch shrinks.
    remaining = []
    for item in data.get("items", []):
        if util.path_exists(item.get("dst", "")):
            remaining.append(item)
    data["items"] = remaining
    try:
        if remaining:
            manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            util.force_remove(str(_batch_dir(batch_id)))
    except OSError:
        pass
    return restored, failed


def purge_batch(batch_id: str) -> bool:
    try:
        util.force_remove(str(_batch_dir(batch_id)))
        log_event("purge-quarantine", batch_id)
        return True
    except OSError as exc:
        log_event("purge-failed", f"{batch_id} :: {exc}", ok=False)
        return False


def purge_all() -> tuple[int, int]:
    ok = bad = 0
    for batch in quarantine_batches():
        if purge_batch(batch["id"]):
            ok += 1
        else:
            bad += 1
    return ok, bad


# --------------------------------------------------------------------------- #
# logging
# --------------------------------------------------------------------------- #
def _log_file() -> Path:
    return paths.LOGS / f"sweep-{datetime.now():%Y%m%d}.log"


def log_event(action: str, detail: str, ok: bool = True) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {'OK ' if ok else 'ERR'} {action}: {detail}\n"
    try:
        util.open_text(_log_file(), line)
    except OSError:
        pass


def read_log_tail(limit: int = 120) -> list[str]:
    try:
        with open(_log_file(), "r", encoding="utf-8", errors="replace") as fh:
            return fh.readlines()[-limit:]
    except OSError:
        return []


# --------------------------------------------------------------------------- #
# deleter
# --------------------------------------------------------------------------- #
class Deleter:
    """Executes approved deletions for one cleaning session."""

    def __init__(self, mode: str = "quarantine", note: str = "") -> None:
        self.mode = mode if mode in ("quarantine", "permanent") else "quarantine"
        self.note = note
        self.batch_id = util.stamp()
        self.stats = BatchStats()
        self.items: list[dict] = []
        self._lock = threading.Lock()

    # -- guards ---------------------------------------------------------- #
    def prepare_roots(self, roots: Iterable[str | os.PathLike[str]]) -> tuple[str, ...]:
        """Normalise approved roots once per cleaning pass."""
        return tuple(_norm(r) for r in roots)

    def _guard(
        self,
        path: str,
        allowed: Sequence[str] | tuple[str, ...],
        allow_equal_root: bool,
    ) -> str | None:
        p = _norm(path)
        if allowed:
            if allow_equal_root:
                inside = any(p == root or util.is_within(p, root) for root in allowed)
            else:
                inside = any(util.is_within(p, root) and p != root for root in allowed)
            if not inside:
                return "outside the approved folder set"
        return blocked_reason(path)

    # -- main entry point ------------------------------------------------ #
    def delete(
        self,
        path: str | os.PathLike[str],
        allowed_roots: Iterable[str | os.PathLike[str]] = (),
        category: str = "",
        allow_equal_root: bool = True,
        cancel: threading.Event | None = None,
    ) -> DeleteResult:
        target = os.path.abspath(str(path))
        roots = self.prepare_roots(list(allowed_roots))
        reason = self._guard(target, roots, allow_equal_root)
        if reason:
            result = DeleteResult(target, "skipped", 0, reason)
            with self._lock:
                self.stats.add(result)
            log_event("skip", f"{target} :: {reason}", ok=False)
            return result

        if not util.path_exists(target):
            return DeleteResult(target, "missing", 0, "already gone")

        size, _files = util.path_stats(target, cancel)

        if self.mode == "permanent":
            try:
                util.force_remove(target)
                result = DeleteResult(target, "deleted", size)
                log_event("delete", f"{target} ({util.human_size(size)})")
            except OSError as exc:
                result = DeleteResult(target, "failed", size, str(exc))
                log_event("delete-failed", f"{target} :: {exc}", ok=False)
            with self._lock:
                self.stats.add(result)
            return result

        # quarantine: move to a per-volume holding area, preserve relative path
        dest = self._quarantine_target(target)
        try:
            util.move_path(target, dest)
            result = DeleteResult(target, "moved", size)
            with self._lock:
                self.items.append(
                    {"src": target, "dst": dest, "size": size, "category": category}
                )
                self.stats.add(result)
            log_event("quarantine", f"{target} -> {dest}")
            return result
        except util.MoveFailure as exc:
            # Some files were renamed into quarantine, some were locked. Record
            # the ones that moved (restorable) and name every one that did not.
            moved_bytes = sum(int(item.get("size") or 0) for item in exc.moved)
            result = DeleteResult(
                target,
                "failed",
                moved_bytes,
                exc.summary,
                failures=exc.failures,
            )
            with self._lock:
                for item in exc.moved:
                    self.items.append(
                        {
                            "src": item["src"],
                            "dst": item["dst"],
                            "size": int(item.get("size") or 0),
                            "category": category,
                        }
                    )
                self.stats.add(result)
            log_event("quarantine-partial", f"{target} :: {exc.summary}", ok=False)
            for failure in exc.failures:
                log_event(
                    "quarantine-locked",
                    f"{failure.get('path')} :: {util.short_reason(failure.get('reason', ''))}",
                    ok=False,
                )
            return result
        except OSError as exc:
            # Locked files are normal (browsers, search index, AV scanners).
            result = DeleteResult(target, "failed", 0, str(exc))
            with self._lock:
                self.stats.add(result)
            log_event("quarantine-failed", f"{target} :: {exc}", ok=False)
            return result

    # -- helpers --------------------------------------------------------- #
    def _quarantine_target(self, src: str) -> str:
        root = paths.quarantine_root_for(src)
        drive, tail = os.path.splitdrive(os.path.abspath(src))
        rel = tail.lstrip("\\/")
        return str(Path(root) / self.batch_id / rel)

    def finish(self) -> BatchStats:
        """Persist the manifest when anything was quarantined."""
        if self.mode != "quarantine":
            return self.stats
        if not self.items:
            # Nothing moved: drop the empty folder skeleton a failed move may
            # have created, so no phantom batch shows up in Quarantine.
            batch = _batch_dir(self.batch_id)
            try:
                if batch.exists() and not any(p.is_file() for p in batch.rglob("*")):
                    util.force_remove(str(batch))
            except OSError:
                pass
            return self.stats
        manifest = {
            "id": self.batch_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "mode": self.mode,
            "note": self.note,
            "items": self.items,
            "stats": {
                "moved": self.stats.moved,
                "skipped": self.stats.skipped,
                "failed": self.stats.failed,
                "bytes": self.stats.bytes,
            },
        }
        try:
            util.ensure_parent(_manifest_path(self.batch_id))
            _manifest_path(self.batch_id).write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            log_event("manifest-failed", str(exc), ok=False)
        return self.stats


# --------------------------------------------------------------------------- #
# recycle bin
# --------------------------------------------------------------------------- #
def empty_recycle_bin() -> tuple[bool, str]:
    """Use the shell API instead of deleting $Recycle.Bin by hand."""
    import ctypes

    flags = 0x1 | 0x2 | 0x4  # no sound, no confirmation, no progress UI
    try:
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    except Exception as exc:  # noqa: BLE001 - ctypes failures are opaque
        return False, str(exc)
    if result == 0:
        log_event("recycle-bin", "emptied")
        return True, "Recycle Bin emptied"
    return False, f"shell error 0x{result & 0xFFFFFFFF:08X}"


def recycle_bin_size(cancel: threading.Event | None = None) -> tuple[int, int]:
    total = 0
    count = 0
    for drive in paths.fixed_drives():
        root = Path(str(drive)[:2] + "\\$Recycle.Bin")
        if not root.exists():
            continue
        size, files = util.dir_stats(root, cancel)
        total += size
        count += files
    return total, count
