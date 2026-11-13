"""Process inventory with a conservative "is this safe to kill?" verdict.

The rule set is deliberately biased towards keeping things alive:

* anything owned by Windows (image under %WINDIR% / WindowsApps) is untouchable;
* session 0 services are listed but locked;
* anything with a visible window is in use;
* anything with a hidden titled window, or a known tray app, is "tray" and kept
  by default;
* only windowless third-party user processes end up as "idle" (kill candidates).
"""
from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes as w
from dataclasses import dataclass
from typing import Callable, Iterable

import psutil

from . import paths, util

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, w.LPARAM]
user32.EnumWindows.restype = w.BOOL
user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
user32.GetWindowThreadProcessId.restype = w.DWORD
user32.IsWindowVisible.argtypes = [w.HWND]
user32.IsWindowVisible.restype = w.BOOL
user32.GetWindowTextLengthW.argtypes = [w.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
kernel32.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
kernel32.ProcessIdToSessionId.restype = w.BOOL

NOISE_CLASSES = {
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "Progman",
    "WorkerW",
    "IME",
    "MSCTFIME UI",
    "Default IME",
    "GDI+ Hook Window Class",
    "tooltips_class32",
    "SysShadow",
    "TaskListThumbnailWnd",
    "ForegroundStaging",
}

CORE_PROTECTED = {
    "system",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "dwm.exe",
    "fontdrvhost.exe",
    "explorer.exe",
    "sihost.exe",
    "taskhostw.exe",
    "ctfmon.exe",
    "runtimebroker.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "searchhost.exe",
    "searchapp.exe",
    "textinputhost.exe",
    "applicationframehost.exe",
    "systemsettings.exe",
    "lockapp.exe",
    "logonui.exe",
    "userinit.exe",
    "spoolsv.exe",
    "audiodg.exe",
    "wudfhost.exe",
    "dllhost.exe",
    "wmiprvse.exe",
    "msmpeng.exe",
    "nissrv.exe",
    "securityhealthservice.exe",
    "securityhealthsystray.exe",
    "smartscreen.exe",
    "searchindexer.exe",
    "trustedinstaller.exe",
    "tiworker.exe",
    "mousocoreworker.exe",
    "usocoreworker.exe",
    "backgroundtaskhost.exe",
    "systemsettingsbroker.exe",
    "memcompression",
    "secure system",
    "registry",
    "system idle process",
    "interrupts",
    "windowsterminal.exe",
    "openconsole.exe",
    "conhost.exe",
    "widgets.exe",
    "widgetservice.exe",
    "phoneexperiencehost.exe",
    "crossdeviceservice.exe",
    "yourphone.exe",
    "gamebar.exe",
    "gamebarftserver.exe",
    "xboxgamebarwidgets.exe",
    "shellexperiencehost",
    "startmenuexperiencehost",
    "searchhost",
}

# Windowless helpers that are still part of "the stuff I want running".
TRAY_HINTS = {
    "onedrive.exe",
    "dropbox.exe",
    "discord.exe",
    "steam.exe",
    "steamwebhelper.exe",
    "spotify.exe",
    "telegram.exe",
    "whatsapp.exe",
    "slack.exe",
    "teams.exe",
    "ms-teams.exe",
    "zoom.exe",
    "qbittorrent.exe",
    "utorrent.exe",
    "nvcontainer.exe",
    "nvtray.exe",
    "radeonsoftware.exe",
    "igfxem.exe",
    "rtkngui64.exe",
    "rtkauduservice64.exe",
    "lghub.exe",
    "logioptionsplus.exe",
    "synapse.exe",
    "icue.exe",
    "armourycrate.exe",
    "msiafterburner.exe",
    "rtss.exe",
    "sharex.exe",
    "greenshot.exe",
    "everything.exe",
    "powertoys.exe",
    "quicklook.exe",
    "pcloud.exe",
    "megasync.exe",
    "nextcloud.exe",
    "syncthing.exe",
    "tailscale-ipn.exe",
    "wireguard.exe",
    "openvpn-gui.exe",
    "expressvpn.exe",
    "nordvpn.exe",
    "protonvpn.exe",
    "malwarebytes.exe",
    "mbamtray.exe",
    "egui.exe",
    "avp.exe",
    "nortonsecurity.exe",
    "mcafee.exe",
    "avastui.exe",
    "avgui.exe",
    "bitdefender.exe",
    "glasswire.exe",
    "hwinfo64.exe",
    "obs64.exe",
    "voicemeeter.exe",
    "voicemeeter8.exe",
    "f.lux.exe",
    "flux.exe",
    "lightshot.exe",
    "snipaste.exe",
    "processhacker.exe",
    "systeminformer.exe",
    "autoruns64.exe",
    "rustdesk.exe",
    "anydesk.exe",
    "teamviewer.exe",
    # A browser with no window is still a browser the user expects to keep.
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "vivaldi.exe",
    "chromium.exe",
    "librewolf.exe",
    "waterfox.exe",
}

HOST_EXE_HINTS = ("deepseek harness", "dsh.exe", "deepseek-harness")

STATE_LABELS = {
    "active": "Active",
    "tray": "Tray",
    "idle": "Idle",
    "system": "Windows",
    "service": "Service",
    "locked": "Locked",
    "linked": "In use",
}

GROUP_ORDER = {
    "idle": 0,
    "linked": 1,
    "tray": 2,
    "active": 3,
    "service": 4,
    "system": 5,
    "locked": 6,
}


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    exe: str
    cmdline: str
    user: str
    session: int
    status: str
    rss: int
    cpu: float
    created: float
    visible_windows: int
    hidden_windows: int
    window_title: str
    group: str
    reason: str
    protected: bool = False

    @property
    def state(self) -> str:
        return STATE_LABELS.get(self.group, self.group.title())

    @property
    def killable(self) -> bool:
        return self.group in ("idle", "tray", "active") and not self.protected

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.created) if self.created else 0.0

    @property
    def age_label(self) -> str:
        return util.human_age(self.created)


@dataclass
class WindowInfo:
    visible: int = 0
    hidden: int = 0
    title: str = ""


EMPTY_WINDOW = WindowInfo()


def collect_windows() -> dict[int, WindowInfo]:
    """pid -> window counts, via one EnumWindows pass."""
    found: dict[int, WindowInfo] = {}

    def _text(hwnd: w.HWND, getter) -> str:  # noqa: ANN001
        buf = ctypes.create_unicode_buffer(512)
        try:
            getter(hwnd, buf, 512)
        except Exception:  # noqa: BLE001
            return ""
        return buf.value

    def _callback(hwnd, _lparam):  # noqa: ANN001
        pid = w.DWORD(0)
        try:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        except Exception:  # noqa: BLE001
            return True
        if not pid.value:
            return True
        try:
            cls = _text(hwnd, user32.GetClassNameW)
            if cls in NOISE_CLASSES:
                return True
            title = _text(hwnd, user32.GetWindowTextW)
            visible = bool(user32.IsWindowVisible(hwnd))
        except Exception:  # noqa: BLE001
            return True
        info = found.setdefault(pid.value, WindowInfo())
        if visible:
            info.visible += 1
            if title and not info.title:
                info.title = title
        elif title:
            info.hidden += 1
            if not info.title:
                info.title = title
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_callback), 0)
    except Exception:  # noqa: BLE001
        pass
    return found


def _session_id(pid: int) -> int:
    sid = w.DWORD(0)
    try:
        if kernel32.ProcessIdToSessionId(w.DWORD(pid), ctypes.byref(sid)):
            return int(sid.value)
    except Exception:  # noqa: BLE001
        pass
    # Access denied almost always means a SYSTEM/session-0 process; assume the
    # safest answer so it is never treated as a killable user app.
    return 0


def _is_windows_image(exe: str | None) -> bool:
    if not exe:
        return False
    e = os.path.normcase(exe)
    windir = os.path.normcase(str(paths.WINDIR))
    if e.startswith(windir + os.sep):
        return True
    pf = os.path.normcase(str(paths.PROGRAM_FILES))
    if e.startswith(pf + os.sep + "windowsapps" + os.sep):
        return True
    if e.startswith(pf + os.sep + "windows defender" + os.sep):
        return True
    return False


def _protected_pids() -> set[int]:
    """Our own tree + every shell/terminal ancestor we run inside."""
    pids: set[int] = {0, 4}
    try:
        me = psutil.Process()
        pids.add(me.pid)
        for parent in me.parents():
            pids.add(parent.pid)
        for child in me.children(recursive=True):
            pids.add(child.pid)
    except (psutil.Error, OSError):
        pids.add(os.getpid())
    return pids


def _classify(
    *,
    pid: int,
    name: str,
    exe: str,
    session: int,
    windows: WindowInfo,
    age: float,
    protected: bool,
) -> tuple[str, str]:
    lname = (name or "").lower()
    if protected:
        return "locked", "this session or shell"
    if pid in (0, 4):
        return "system", "kernel"
    if any(hint in lname for hint in HOST_EXE_HINTS):
        return "locked", "host application"
    if exe and any(hint in exe.lower() for hint in HOST_EXE_HINTS):
        return "locked", "host application"
    if lname in CORE_PROTECTED:
        return "locked", "Windows shell component"
    if session == 0:
        return "service", "background service (session 0)"
    if _is_windows_image(exe):
        return "system", "signed Windows image"
    if windows.visible:
        return "active", "window on screen"
    if windows.hidden or lname in TRAY_HINTS:
        return "tray", "tray / background helper"
    if not exe:
        return "locked", "path not accessible"
    if age and age < 120:
        return "locked", "just started"
    return "idle", "no window, not a Windows process"


_CPU_SEEN: dict[int, float] = {}


def collect(cancel: threading.Event | None = None) -> list[ProcessInfo]:
    windows = collect_windows()
    protected = _protected_pids()
    now = time.time()
    result: list[ProcessInfo] = []

    attrs = [
        "pid",
        "ppid",
        "name",
        "exe",
        "cmdline",
        "username",
        "create_time",
        "memory_info",
        "status",
    ]
    iterator = psutil.process_iter(attrs)
    while True:
        if cancel is not None and cancel.is_set():
            break
        try:
            proc = next(iterator)
        except StopIteration:
            break
        except (psutil.Error, OSError):
            continue
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            name = info.get("name") or ""
            exe = info.get("exe") or ""
            created = float(info.get("create_time") or 0.0)
            mem = info.get("memory_info")
            rss = int(getattr(mem, "rss", 0) or 0)
            cmdline = info.get("cmdline") or []
            try:
                cpu = float(proc.cpu_percent(None))
            except (psutil.Error, OSError):
                cpu = 0.0
            win = windows.get(pid, EMPTY_WINDOW)
            session = _session_id(pid)
            group, reason = _classify(
                pid=pid,
                name=name,
                exe=exe,
                session=session,
                windows=win,
                age=now - created if created else 0.0,
                protected=pid in protected,
            )
            result.append(
                ProcessInfo(
                    pid=pid,
                    ppid=int(info.get("ppid") or 0),
                    name=name,
                    exe=exe,
                    cmdline=" ".join(cmdline)[:400],
                    user=info.get("username") or "",
                    session=session,
                    status=info.get("status") or "",
                    rss=rss,
                    cpu=cpu,
                    created=created,
                    visible_windows=win.visible,
                    hidden_windows=win.hidden,
                    window_title=win.title,
                    group=group,
                    reason=reason,
                    protected=pid in protected,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue

    # Children inherit "keep" from the nearest non-idle ancestor (stopping at
    # explorer, which is the parent of far too many unrelated things). This is
    # what keeps browser renderers and Electron helpers out of the kill list.
    by_pid = {p.pid: p for p in result}
    memo: dict[int, ProcessInfo | None] = {}

    def keep_ancestor(pid: int, depth: int = 0) -> ProcessInfo | None:
        if pid in memo:
            return memo[pid]
        proc = by_pid.get(pid)
        if proc is None or depth > 16:
            return None
        parent = by_pid.get(proc.ppid)
        if parent is None or parent.name.lower() == "explorer.exe":
            memo[pid] = None
            return None
        if parent.group != "idle":
            memo[pid] = parent
            return parent
        found = keep_ancestor(parent.pid, depth + 1)
        memo[pid] = found
        return found

    for info in result:
        # A renderer/helper sharing its parent's image name is not a tray app.
        if info.group == "tray" and info.visible_windows == 0 and info.hidden_windows == 0:
            parent = by_pid.get(info.ppid)
            if parent is not None and parent.name.lower() == info.name.lower():
                info.group = "linked"
                info.reason = f"child of {parent.name}"
                continue
        if info.group != "idle":
            continue
        keeper = keep_ancestor(info.pid)
        if keeper is not None:
            info.group = "linked"
            info.reason = f"child of {keeper.name}"

    result.sort(key=lambda p: (GROUP_ORDER.get(p.group, 9), -p.rss, p.name.lower()))
    return result


@dataclass
class KillResult:
    pid: int
    name: str
    ok: bool
    message: str = ""


def kill_processes(
    processes: Iterable[ProcessInfo],
    cancel: threading.Event | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[KillResult]:
    """Terminate windowless helpers, children first. Never touches protected pids."""
    targets = [p for p in processes if p.killable and p.pid > 4]
    results: list[KillResult] = []
    total = len(targets)
    protected = _protected_pids()

    for index, target in enumerate(targets, start=1):
        if cancel is not None and cancel.is_set():
            break
        if target.pid in protected:
            results.append(KillResult(target.pid, target.name, False, "protected"))
            continue
        try:
            proc = psutil.Process(target.pid)
        except psutil.NoSuchProcess:
            results.append(KillResult(target.pid, target.name, True, "already gone"))
            continue
        except psutil.AccessDenied:
            results.append(KillResult(target.pid, target.name, False, "access denied"))
            continue

        victims: list[psutil.Process] = []
        try:
            victims = proc.children(recursive=True)
        except psutil.Error:
            victims = []
        for victim in reversed(victims):
            if victim.pid in protected:
                continue
            try:
                victim.terminate()
            except psutil.Error:
                pass
        try:
            proc.terminate()
            _gone, alive = psutil.wait_procs([proc], timeout=2.0)
            if alive:
                for victim in alive:
                    victim.kill()
                psutil.wait_procs(alive, timeout=1.0)
            results.append(KillResult(target.pid, target.name, True, "terminated"))
        except psutil.AccessDenied:
            results.append(KillResult(target.pid, target.name, False, "access denied"))
        except psutil.NoSuchProcess:
            results.append(KillResult(target.pid, target.name, True, "already gone"))
        except psutil.Error as exc:
            results.append(KillResult(target.pid, target.name, False, str(exc)))
        if progress:
            progress(index, total, target.name)
    return results


def summary(processes: list[ProcessInfo]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for proc in processes:
        counts[proc.group] = counts.get(proc.group, 0) + 1
    counts["total"] = len(processes)
    return counts
