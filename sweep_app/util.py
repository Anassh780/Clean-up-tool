"""Small, dependency-free helpers used across Sweep."""
from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import threading
import time
from datetime import datetime
from typing import Iterable, Iterator

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4

LONG_PREFIX = "\\\\?\\"


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def human_size(num: float | int | None) -> str:
    """1234567 -> '1.2 MB'."""
    try:
        n = float(num or 0)
    except (TypeError, ValueError):
        return "0 B"
    if n <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return f"{int(n)} B"
    if n >= 100:
        return f"{n:,.0f} {units[i]}"
    if n >= 10:
        return f"{n:.1f} {units[i]}"
    return f"{n:.2f} {units[i]}"


def human_count(num: int | None) -> str:
    return f"{int(num or 0):,}"


def human_age(ts: float | None) -> str:
    """Unix timestamp -> 'just now' / '4h ago' / '12d ago'."""
    if not ts:
        return "—"
    delta = max(0.0, time.time() - float(ts))
    if delta < 90:
        return "just now"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    if delta < 86400 * 30:
        return f"{int(delta // 86400)}d ago"
    if delta < 86400 * 365:
        return f"{int(delta // (86400 * 30))}mo ago"
    return f"{int(delta // (86400 * 365))}y ago"


def short_time(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time()).strftime("%H:%M:%S")


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    text = str(text or "")
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(ellipsis):
        return text[:width]
    return text[: width - len(ellipsis)] + ellipsis


def middle_truncate(text: str, width: int) -> str:
    """Keep both ends of a long path visible: C:\\Users\\…\\Temp\\file.tmp"""
    text = str(text or "")
    if len(text) <= width or width < 8:
        return truncate(text, width)
    head = max(3, width // 3)
    tail = width - head - 1
    return text[:head] + "…" + text[-tail:]


# --------------------------------------------------------------------------- #
# names
# --------------------------------------------------------------------------- #
def norm(text: str | None) -> str:
    """Normalise for fuzzy comparison: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def words(text: str | None) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def looks_like_name(query: str, name: str) -> bool:
    """Loose match used by the program-name remover."""
    q, n = norm(query), norm(name)
    if not q:
        return False
    if q in n:
        return True
    qw = [w for w in words(query) if len(w) > 1]
    nw = set(words(name))
    return bool(qw) and all(w in nw for w in qw)


# --------------------------------------------------------------------------- #
# windows paths
# --------------------------------------------------------------------------- #
def long_path(path: str | os.PathLike[str]) -> str:
    """Prefix a path with \\\\?\\ so MAX_PATH stops mattering."""
    p = os.path.abspath(str(path))
    if p.startswith(LONG_PREFIX):
        return p
    if p.startswith("\\\\"):
        return LONG_PREFIX + "UNC\\" + p[2:]
    return LONG_PREFIX + p


def strip_long(path: str) -> str:
    if path.startswith(LONG_PREFIX + "UNC\\"):
        return "\\\\" + path[len(LONG_PREFIX) + 4 :]
    if path.startswith(LONG_PREFIX):
        return path[len(LONG_PREFIX) :]
    return path


def is_reparse(path: str | os.PathLike[str]) -> bool:
    try:
        st = os.lstat(long_path(path))
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def path_exists(path: str | os.PathLike[str]) -> bool:
    try:
        os.lstat(long_path(path))
        return True
    except OSError:
        return False


def file_size(path: str | os.PathLike[str]) -> int:
    try:
        st = os.stat(long_path(path))
    except OSError:
        return 0
    return int(st.st_size)


def safe_children(path: str | os.PathLike[str]) -> list[os.DirEntry]:
    try:
        with os.scandir(long_path(path)) as it:
            return list(it)
    except OSError:
        return []


def ensure_parent(path: str | os.PathLike[str]) -> None:
    parent = os.path.dirname(os.path.abspath(str(path)))
    if parent and not os.path.isdir(long_path(parent)):
        os.makedirs(long_path(parent), exist_ok=True)


def open_in_explorer(path: str | os.PathLike[str]) -> None:
    """Reveal a file/folder in Explorer without blocking."""
    p = os.path.abspath(str(path))
    try:
        if os.path.isdir(long_path(p)):
            os.startfile(p)  # noqa: S606 - intentional shell open
        else:
            os.startfile(os.path.dirname(p))
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# walking
# --------------------------------------------------------------------------- #
def _is_reparse_entry(entry: os.DirEntry) -> bool:
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def walk_tree(
    root: str | os.PathLike[str],
    cancel: threading.Event | None = None,
    skip_reparse: bool = True,
) -> Iterator[tuple[str, bool, int]]:
    """Yield (path, is_dir, size) depth-first. Never follows junctions."""
    stack = [os.path.abspath(str(root))]
    while stack:
        if cancel is not None and cancel.is_set():
            return
        current = stack.pop()
        try:
            with os.scandir(long_path(current)) as entries:
                for entry in entries:
                    if cancel is not None and cancel.is_set():
                        return
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if skip_reparse and _is_reparse_entry(entry):
                                continue
                            stack.append(strip_long(entry.path))
                            yield strip_long(entry.path), True, 0
                        else:
                            st = entry.stat(follow_symlinks=False)
                            yield strip_long(entry.path), False, int(st.st_size)
                    except OSError:
                        continue
        except OSError:
            continue


def dir_stats(
    root: str | os.PathLike[str], cancel: threading.Event | None = None
) -> tuple[int, int]:
    """(bytes, file_count) for a tree. Best effort, never raises."""
    total = 0
    count = 0
    for _path, is_dir, size in walk_tree(root, cancel):
        if not is_dir:
            total += size
            count += 1
    return total, count


def path_stats(path: str | os.PathLike[str], cancel: threading.Event | None = None) -> tuple[int, int]:
    """(bytes, file_count) for a file or folder."""
    p = os.path.abspath(str(path))
    try:
        st = os.lstat(long_path(p))
    except OSError:
        return 0, 0
    if stat.S_ISDIR(st.st_mode) and not (getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT):
        return dir_stats(p, cancel)
    return int(st.st_size), 1


# --------------------------------------------------------------------------- #
# destructive primitives (guarded by safety.py before they are ever called)
# --------------------------------------------------------------------------- #
def clear_readonly(path: str | os.PathLike[str]) -> None:
    try:
        os.chmod(long_path(path), stat.S_IWRITE)
    except OSError:
        pass


def _rmtree(path: str) -> None:
    """shutil.rmtree that clears read-only attributes and retries once."""
    lp = long_path(path)

    def _retry(func, p, exc):  # noqa: ANN001 - shutil callback signature
        clear_readonly(p)
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                os.rmdir(p)
            else:
                os.remove(p)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(lp, onexc=_retry)
    else:  # pragma: no cover - older interpreters
        shutil.rmtree(lp, onerror=_retry)


def force_remove(path: str | os.PathLike[str]) -> None:
    """Delete a file or tree, clearing attributes and retrying locks."""
    p = os.path.abspath(str(path))
    lp = long_path(p)
    try:
        st = os.lstat(lp)
    except FileNotFoundError:
        return
    is_dir = stat.S_ISDIR(st.st_mode) and not (
        getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
    )

    last_error: OSError | None = None
    for attempt in range(3):
        try:
            if is_dir:
                _rmtree(p)
            else:
                clear_readonly(p)
                os.remove(lp)
            if not path_exists(p):
                return
        except OSError as exc:  # locked / in use
            last_error = exc
            time.sleep(0.15 * (attempt + 1))
    if path_exists(p):
        raise last_error or OSError(f"could not remove {p}")


class MoveFailure(OSError):
    """A move that could not finish, with one entry per file that failed.

    ``moved`` lists the files that were renamed before the failure (so the
    caller can record them in the quarantine manifest), and ``failures`` holds
    ``{"path", "reason"}`` for every file left behind.
    """

    def __init__(
        self,
        src: str,
        dst: str,
        moved: list[dict] | None = None,
        failures: list[dict] | None = None,
    ) -> None:
        self.src = str(src)
        self.dst = str(dst)
        self.moved = list(moved or [])
        self.failures = list(failures or [])
        super().__init__(self.summary)

    @property
    def summary(self) -> str:
        if not self.failures:
            return f"could not move {self.src}"
        first = self.failures[0]
        name = os.path.basename(first.get("path", "")) or first.get("path", "file")
        count = len(self.failures)
        tail = f" (and {count - 1} more file{'s' if count > 2 else ''})" if count > 1 else ""
        return f"{name} — {short_reason(first.get('reason', ''))}{tail}"


def short_reason(text: str) -> str:
    """Turn a WinError string into the sentence a person needs."""
    low = (text or "").lower()
    if "winerror 32" in low or "being used by another process" in low or "sharing violation" in low:
        return "in use by another process"
    if "winerror 5" in low or "access is denied" in low:
        return "access denied"
    if "winerror 2" in low or "cannot find the file" in low or "no such file" in low:
        return "no longer exists"
    if "winerror 112" in low or "not enough space" in low or "disk full" in low:
        return "not enough disk space"
    if "winerror 145" in low or "directory is not empty" in low:
        return "folder is not empty"
    first = (text or "").splitlines()[0].strip()
    return first[:140] if first else "unknown error"


def _move_dir_contents(src: str, dst: str) -> tuple[list[dict], list[dict]]:
    """Rename every file below *src* into *dst*; never copy.

    A copy-then-delete fallback (``shutil.move``) is what produced a 13 GB
    duplicate and an unreadable ``shutil.Error`` tuple list. Renaming keeps the
    operation atomic per file, so a locked file leaves its neighbours moved and
    itself untouched, and every failure can be named.
    """
    moved: list[dict] = []
    failures: list[dict] = []
    for root, dirs, files in os.walk(src, topdown=True, followlinks=False):
        rel = os.path.relpath(root, src)
        target = dst if rel == "." else os.path.join(dst, rel)
        for name in list(dirs):
            if os.path.islink(os.path.join(root, name)):
                files.append(name)
                dirs.remove(name)
        for name in files:
            source = os.path.join(root, name)
            destination = os.path.join(target, name)
            try:
                size = os.path.getsize(long_path(source))
            except OSError:
                size = 0
            try:
                ensure_parent(destination)
                os.replace(long_path(source), long_path(destination))
            except OSError as exc:
                failures.append({"path": source, "reason": str(exc)})
            else:
                moved.append({"src": source, "dst": destination, "size": size})
    return moved, failures


def _prune_empty_dirs(src: str) -> None:
    for root, _dirs, _files in os.walk(src, topdown=False):
        try:
            os.rmdir(long_path(root))
        except OSError:
            pass


def move_path(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """Move a file or directory, long-path safe and rename-only.

    Raises :class:`MoveFailure` when some files could not be renamed, with one
    reason per file. Files that did move are reported in ``failure.moved``.
    """
    s = os.path.abspath(str(src))
    d = os.path.abspath(str(dst))
    ensure_parent(d)
    if os.path.exists(long_path(d)):
        raise FileExistsError(f"destination already exists: {d}")
    try:
        os.replace(long_path(s), long_path(d))
        return
    except OSError as first:
        if not os.path.isdir(s):
            raise
        moved, failures = _move_dir_contents(s, d)
        _prune_empty_dirs(s)
        if failures:
            raise MoveFailure(s, d, moved, failures) from first


# --------------------------------------------------------------------------- #
# misc
# --------------------------------------------------------------------------- #
def dedupe(paths: Iterable[str | os.PathLike[str]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        key = os.path.normcase(os.path.abspath(str(p)))
        if key in seen:
            continue
        seen.add(key)
        out.append(os.path.abspath(str(p)))
    return out


def is_within(path: str | os.PathLike[str], root: str | os.PathLike[str]) -> bool:
    """True when path is root or lives underneath it (case-insensitive)."""
    p = os.path.normcase(os.path.abspath(str(path)))
    r = os.path.normcase(os.path.abspath(str(root)))
    if p == r:
        return True
    if not r.endswith(os.sep):
        r += os.sep
    return p.startswith(r)


def open_text(path: str | os.PathLike[str], text: str, mode: str = "a") -> None:
    ensure_parent(path)
    with open(long_path(path), mode, encoding="utf-8", errors="replace") as fh:
        fh.write(text)


class Clock:
    """Tiny stopwatch for the UI status bar."""

    def __init__(self) -> None:
        self.started = time.perf_counter()

    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    def label(self) -> str:
        secs = self.elapsed()
        if secs < 60:
            return f"{secs:.1f}s"
        return f"{int(secs // 60)}m {int(secs % 60)}s"
