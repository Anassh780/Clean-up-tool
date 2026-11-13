"""Apply a staged Sweep update after the running copy exits.

This file is started as a plain script by :func:`sweep_app.updates.apply`. It
imports **only the standard library** on purpose: the folder it is about to
rewrite contains the ``sweep_app`` package, so importing that package here
would mean running code from a tree that is changing underneath us.

The sequence is:

1. wait (bounded) for the old PID to exit;
2. copy every file that will be replaced into ``backup-<version>-<stamp>``;
3. overlay the staged tree onto the install folder;
4. drop ``__pycache__`` and Python modules the new release no longer ships;
5. write ``update-status.json`` and start the same interface again.

Any failure after step 2 restores the backup and relaunches the old version,
so a bad release cannot leave a half-updated app.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

SCHEMA = 1
WAIT_SECONDS = 180
STATUS_FILE = "update-status.json"


# --------------------------------------------------------------------------- #
# small utilities
# --------------------------------------------------------------------------- #
def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _log_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    folder = Path(base) / "Sweep" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"update-{time.strftime('%Y%m%d-%H%M%S')}.log"


class Log:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _log_path()
        self._handle = None
        try:
            self._handle = self.path.open("a", encoding="utf-8")
        except OSError:
            self._handle = None

    def write(self, message: str) -> None:
        line = f"[{_stamp()}] {message}"
        if self._handle is not None:
            try:
                self._handle.write(line + "\n")
                self._handle.flush()
            except OSError:
                pass

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass


def _status_path(app_root: Path) -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Sweep" / "updates" / STATUS_FILE


def write_status(app_root: Path, payload: dict[str, Any]) -> None:
    target = _status_path(app_root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": SCHEMA, "at": time.time(), **payload}
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# waiting for the old process
# --------------------------------------------------------------------------- #
def wait_for_exit(pid: int, timeout: float = WAIT_SECONDS) -> bool:
    """Block until ``pid`` is gone. Returns False on timeout."""
    if pid <= 0:
        return True
    if os.name != "nt":
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.25)
        return False

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    synchronize = 0x00100000
    handle = kernel32.OpenProcess(synchronize, False, int(pid))
    if not handle:
        return True  # already gone, or no access: either way, nothing to wait for
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
        return result == 0  # WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


# --------------------------------------------------------------------------- #
# relaunching
# --------------------------------------------------------------------------- #
def _quote(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def relaunch(argv: list[str], app_root: Path, log: Log) -> None:
    """Start Sweep again in a fresh console window (Windows) or directly."""
    if not argv:
        log.write("no relaunch command; the update is applied but Sweep stays closed")
        return
    if os.name == "nt":
        script = Path(os.environ.get("TEMP", str(app_root))) / f"sweep-relaunch-{os.getpid()}.bat"
        lines = [
            "@echo off",
            "setlocal",
            f"cd /d {_quote(str(app_root))}",
            "start \"Sweep\" " + " ".join(_quote(part) for part in argv),
        ]
        try:
            script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
            subprocess.Popen(  # noqa: S603 - fixed argv, generated batch
                ["cmd", "/c", str(script)],
                cwd=str(app_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log.write(f"relaunched via {script.name}: {argv}")
        except OSError as exc:
            log.write(f"relaunch failed: {type(exc).__name__}: {exc}")
        return
    try:
        subprocess.Popen(  # noqa: S603 - fixed argv
            argv,
            cwd=str(app_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        log.write(f"relaunched: {argv}")
    except OSError as exc:
        log.write(f"relaunch failed: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# file plan
# --------------------------------------------------------------------------- #
def _collect(staged: Path) -> list[str]:
    files: list[str] = []
    for path in staged.rglob("*"):
        if path.is_file():
            files.append(path.relative_to(staged).as_posix())
    files.sort()
    return files


def _backup_existing(app_root: Path, backup: Path, rel: str, log: Log) -> bool:
    source = app_root / rel
    if not source.is_file():
        return False
    target = backup / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def _remove_stale_modules(app_root: Path, staged: Path, backup: Path, log: Log) -> None:
    """Move Python modules the new release dropped out of the way."""
    new_files = {
        path.relative_to(staged).as_posix() for path in staged.rglob("*.py") if path.is_file()
    }
    removed_dir = backup / "removed"
    for package in ("sweep_app",):
        folder = app_root / package
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.py"):
            rel = path.relative_to(app_root).as_posix()
            if rel in new_files:
                continue
            target = removed_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(path), str(target))
                log.write(f"removed stale module {rel}")
            except OSError as exc:
                log.write(f"could not remove stale module {rel}: {exc}")


def _purge_pycache(app_root: Path) -> None:
    for path in app_root.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def apply_plan(plan_path: Path, log: Log) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    app_root = Path(plan["app_root"]).resolve()
    staged = Path(plan["staged"]).resolve()
    backup = Path(plan["backup"]).resolve()
    version = str(plan.get("version") or "")
    from_version = str(plan.get("from_version") or "")
    pid = int(plan.get("pid") or 0)

    log.write(
        f"update {from_version} -> {version}; app_root={app_root}; staged={staged}; pid={pid}"
    )
    if not staged.is_dir():
        log.write("staged folder is missing")
        write_status(app_root, {"ok": False, "version": version, "error": "staged folder missing"})
        return 1

    if not wait_for_exit(pid):
        log.write(f"process {pid} is still running after {WAIT_SECONDS}s; not touching files")
        write_status(
            app_root,
            {
                "ok": False,
                "version": version,
                "error": f"process {pid} did not exit within {WAIT_SECONDS}s",
            },
        )
        return 1

    files = _collect(staged)
    backup.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    backed_up: list[str] = []
    log.write(f"{len(files)} files to install")

    try:
        for rel in files:
            if _backup_existing(app_root, backup, rel, log):
                backed_up.append(rel)
            else:
                created.append(rel)
        manifest = {
            "schema": SCHEMA,
            "version": version,
            "from_version": from_version,
            "app_root": str(app_root),
            "staged": str(staged),
            "backed_up": backed_up,
            "created": created,
            "created_at": time.time(),
            "relaunch": plan.get("relaunch") or [],
        }
        (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        for rel in files:
            source = staged / rel
            target = app_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        _remove_stale_modules(app_root, staged, backup, log)
        _purge_pycache(app_root)
        log.write("files installed")
    except BaseException as exc:  # noqa: BLE001 - rollback must catch everything
        log.write(f"install failed: {type(exc).__name__}: {exc}")
        log.write(traceback.format_exc())
        restore(app_root, backup, log, relaunch_cmd=plan.get("relaunch") or [])
        write_status(
            app_root,
            {
                "ok": False,
                "version": version,
                "from_version": from_version,
                "error": f"{type(exc).__name__}: {exc}",
                "backup": str(backup),
                "rolled_back": True,
            },
        )
        return 1

    write_status(
        app_root,
        {
            "ok": True,
            "version": version,
            "from_version": from_version,
            "backup": str(backup),
            "log": str(log.path),
            "installed": len(files),
        },
    )
    log.write("update complete")
    if not plan.get("keep_backup"):
        shutil.rmtree(backup, ignore_errors=True)
        log.write("backup removed (keep_backup was false)")

    relaunch(list(plan.get("relaunch") or []), app_root, log)
    try:
        plan_path.unlink(missing_ok=True)
    except OSError:
        pass
    return 0


# --------------------------------------------------------------------------- #
# restore / rollback
# --------------------------------------------------------------------------- #
def restore(app_root: Path, backup: Path, log: Log, relaunch_cmd: list[str] | None = None) -> int:
    manifest_path = backup / "manifest.json"
    if not manifest_path.is_file():
        log.write(f"no manifest in {backup}")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    restored = 0
    for rel in manifest.get("backed_up") or []:
        source = backup / rel
        target = app_root / rel
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored += 1
    for rel in manifest.get("created") or []:
        target = app_root / rel
        try:
            if target.is_file():
                target.unlink()
        except OSError:
            pass
    removed_dir = backup / "removed"
    if removed_dir.is_dir():
        for path in removed_dir.rglob("*.py"):
            rel = path.relative_to(removed_dir)
            target = app_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(path, target)
            except OSError:
                pass
    _purge_pycache(app_root)
    log.write(f"restored {restored} files from {backup}")
    if relaunch_cmd:
        relaunch(relaunch_cmd, app_root, log)
    return 0


def list_backups(app_root: Path) -> list[dict[str, Any]]:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    root = Path(base) / "Sweep" / "updates"
    rows: list[dict[str, Any]] = []
    for folder in sorted(root.glob("backup-*"), reverse=True):
        if not folder.is_dir():
            continue
        manifest = folder / "manifest.json"
        info: dict[str, Any] = {"name": folder.name, "path": str(folder)}
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                info.update(
                    {
                        "version": data.get("version"),
                        "from_version": data.get("from_version"),
                        "created_at": data.get("created_at"),
                        "files": len(data.get("backed_up") or []),
                    }
                )
            except (OSError, ValueError):
                pass
        rows.append(info)
    return rows


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sweep-updater")
    parser.add_argument("--plan", help="path to the apply plan written by Sweep")
    parser.add_argument("--restore", help="backup folder to restore")
    parser.add_argument("--app-root", help="install folder (with --restore)")
    parser.add_argument("--relaunch", action="store_true", help="start Sweep after restoring")
    parser.add_argument("--list", action="store_true", help="list backups")
    args = parser.parse_args(argv)

    log = Log()
    try:
        if args.list:
            app_root = Path(args.app_root or Path(__file__).resolve().parent.parent)
            for row in list_backups(app_root):
                print(json.dumps(row, indent=2))
            return 0
        if args.restore:
            app_root = Path(args.app_root or Path(__file__).resolve().parent.parent).resolve()
            backup = Path(args.restore).resolve()
            relaunch_cmd = None
            if args.relaunch:
                manifest = backup / "manifest.json"
                if manifest.is_file():
                    try:
                        relaunch_cmd = json.loads(manifest.read_text(encoding="utf-8")).get(
                            "relaunch"
                        )
                    except (OSError, ValueError):
                        relaunch_cmd = None
            return restore(app_root, backup, log, relaunch_cmd=relaunch_cmd)
        if args.plan:
            return apply_plan(Path(args.plan), log)
        parser.print_help()
        return 2
    except BaseException as exc:  # noqa: BLE001 - never leave a silent failure
        log.write(f"fatal: {type(exc).__name__}: {exc}")
        log.write(traceback.format_exc())
        return 1
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
