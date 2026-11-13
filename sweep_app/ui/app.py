"""The Sweep application shell: top bar, sidebar, panes, status bar."""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, ContentSwitcher, Input, RichLog, Static

from .. import __version__, admin, config, paths, procs, safety, updates, util
from .common import (
    ACCENT,
    BAD,
    DIM,
    GOOD,
    MUTED,
    TEXT,
    WARN,
    ConfirmScreen,
    HelpScreen,
    SettingsScreen,
    StatCard,
)
from .junk_pane import JunkPane
from .leftovers_pane import LeftoversPane
from .procs_pane import ProcsPane
from .quarantine_pane import QuarantinePane
from .remover_pane import RemoverPane

LOGO_LINES = [
    " ███████╗██╗    ██╗███████╗███████╗██████╗ ",
    " ██╔════╝██║    ██║██╔════╝██╔════╝██╔══██╗",
    " ███████╗██║ █╗ ██║█████╗  █████╗  ██████╔╝",
    " ╚════██║██║███╗██║██╔══╝  ██╔══╝  ██╔═══╝ ",
    " ███████║╚███╔███╔╝███████╗███████╗██║     ",
    " ╚══════╝ ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝     ",
]
LOGO_COLORS = ["#22d3ee", "#3fc9e8", "#5fb9e6", "#7fa9e4", "#a78bfa", "#c084fc"]

NAV_ITEMS = [
    ("dashboard", "01", "Dashboard"),
    ("junk", "02", "Junk files"),
    ("procs", "03", "Processes"),
    ("leftovers", "04", "Leftovers"),
    ("remover", "05", "Program remover"),
    ("quarantine", "06", "Quarantine"),
]

HINTS = {
    "dashboard": [
        ("1-6", "panes"),
        ("s", "settings"),
        ("u", "updates"),
        ("?", "help"),
        ("q", "quit"),
    ],
    "junk": [("space", "toggle"), ("a", "all"), ("n", "none"), ("x", "clean"), ("r", "rescan")],
    "procs": [("space", "select"), ("i", "idle"), ("x", "kill"), ("r", "refresh")],
    "leftovers": [("space", "select"), ("a", "all"), ("x", "remove"), ("o", "open"), ("r", "scan")],
    "remover": [("enter", "search"), ("space", "select"), ("x", "remove"), ("r", "search")],
    "quarantine": [("space", "select"), ("x", "restore"), ("r", "refresh")],
}


@dataclass
class AppState:
    junk_size: int = 0
    junk_files: int = 0
    junk_scanned: bool = False
    idle_count: int = 0
    proc_total: int = 0
    quarantine_size: int = 0
    quarantine_items: int = 0


class TopBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static("", id="top-brand")
        yield Static("", id="top-info")

    def update_bar(
        self,
        mode: str,
        elevated: bool,
        clock: str,
        update_latest: str = "",
    ) -> None:
        brand = Text()
        brand.append(" SWEEP ", style=f"bold #04121a on {ACCENT}")
        # Below ~90 columns the tagline crowds the clock and the update badge,
        # so drop the adjective rather than clipping the badge off-screen.
        tagline = (
            "  cleanup console"
            if self.size.width < 90
            else "  windows cleanup console"
        )
        brand.append(tagline, style=DIM)
        brand.append(f"   v{__version__}", style=MUTED)
        if update_latest:
            brand.append(f"  ↑ v{update_latest}", style=f"bold {ACCENT}")
        self.query_one("#top-brand", Static).update(brand)

        info = Text()
        info.append("ADMIN " if elevated else "LIMITED ", style=f"bold {GOOD if elevated else WARN}")
        info.append("│ ", style=MUTED)
        info.append(
            "QUARANTINE" if mode == "quarantine" else "PERMANENT",
            style=f"bold {GOOD if mode == 'quarantine' else BAD}",
        )
        info.append("  │ ", style=MUTED)
        info.append(clock, style=DIM)
        info.append("  ", style=DIM)
        self.query_one("#top-info", Static).update(info)

    def on_resize(self, _event) -> None:
        # The tagline/badge choice depends on width, so re-render when the
        # terminal is resized instead of waiting for the next clock tick.
        update = getattr(self.app, "_update_chrome", None)
        if callable(update):
            update()


class NavItem(Static):
    class Selected(Message):
        def __init__(self, view: str) -> None:
            self.view = view
            super().__init__()

    def __init__(self, view: str, number: str, label: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.view = view
        self.number = number
        self.label = label
        self.add_class("nav-item")

    def on_mount(self) -> None:
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        self.set_class(active, "active")
        color = ACCENT if active else DIM
        text = Text()
        text.append("▌ " if active else "  ", style=ACCENT)
        text.append(f"{self.number}  ", style=f"bold {color}")
        text.append(self.label, style=f"bold {TEXT}" if active else DIM)
        self.update(text)

    def on_click(self) -> None:
        self.post_message(self.Selected(self.view))


class SafetyCard(Static):
    def on_mount(self) -> None:
        self.set_mode("quarantine")

    def set_mode(self, mode: str) -> None:
        text = Text()
        if mode == "quarantine":
            text.append("● QUARANTINE\n", style=f"bold {GOOD}")
            text.append("removals are restorable\n", style=DIM)
            text.append("per-volume holding area", style=MUTED)
        else:
            text.append("● PERMANENT\n", style=f"bold {BAD}")
            text.append("removals cannot be undone\n", style=DIM)
            text.append("space is freed immediately", style=MUTED)
        self.update(text)


class StatusBar(Static):
    def show(self, view: str, mode: str) -> None:
        text = Text()
        for index, (key, label) in enumerate(HINTS.get(view, [])):
            if index:
                text.append("   ", style=MUTED)
            text.append(f" {key} ", style="bold #dbeafe on #1e2a36")
            text.append(f" {label}", style=DIM)
        text.append("     ", style=MUTED)
        text.append(
            "quarantine" if mode == "quarantine" else "permanent",
            style=f"{GOOD if mode == 'quarantine' else BAD}",
        )
        self.update(text)


class DashboardPane(VerticalScroll):
    def compose(self) -> ComposeResult:
        with Horizontal(id="hero"):
            yield Static(self._logo(), id="logo")
            with Vertical(id="hero-text"):
                yield Static("WINDOWS CLEANUP CONSOLE", id="hero-title")
                yield Static(
                    "Reclaim space. Quiet the noise. Keep what matters.",
                    id="hero-sub",
                )
                yield Static(
                    "quarantine-first   ·   process-aware   ·   admin-aware",
                    id="hero-tags",
                )
        with Horizontal(id="stat-row"):
            yield StatCard("RECLAIMABLE", "—", "run a scan", id="stat-junk")
            yield StatCard("IDLE PROCESSES", "—", "checking…", id="stat-procs")
            yield StatCard("QUARANTINE", "—", "reversible", id="stat-quar")
            yield StatCard("FREE SPACE", "—", "system drive", id="stat-free")
        yield Static("DRIVES", classes="section")
        yield Static("", id="drive-lines")
        yield Static("QUICK ACTIONS", classes="section")
        with Horizontal(id="quick-actions"):
            yield Button("Scan junk", id="qa-junk", variant="primary")
            yield Button("Review processes", id="qa-procs")
            yield Button("Find leftovers", id="qa-left")
            yield Button("Remove a program", id="qa-remove")
        yield Static("RECENT ACTIVITY", classes="section")
        yield RichLog(id="activity", max_lines=120, wrap=True)

    @staticmethod
    def _logo() -> Text:
        text = Text()
        for line, color in zip(LOGO_LINES, LOGO_COLORS):
            text.append(line + "\n", style=f"bold {color}")
        return text

    def on_mount(self) -> None:
        self._refresh_all()

    def on_show(self) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._refresh_drives()
        self._refresh_activity()
        self._refresh_quarantine()
        self._refresh_stats()
        self._refresh_stats_async()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        target = {
            "qa-junk": "junk",
            "qa-procs": "procs",
            "qa-left": "leftovers",
            "qa-remove": "remover",
        }.get(event.button.id or "")
        if target:
            self.app.action_view(target)

    # -- data ------------------------------------------------------------
    def _refresh_drives(self) -> None:
        text = Text()
        for drive in paths.drive_usage():
            percent = drive["percent"]
            width = 26
            filled = max(0, min(width, int(width * percent / 100)))
            color = GOOD if percent < 70 else WARN if percent < 90 else BAD
            text.append(f"  {drive['letter']}  ", style=f"bold {ACCENT}")
            text.append("█" * filled, style=color)
            text.append("░" * (width - filled), style="#1e2a36")
            text.append(
                f"   {util.human_size(drive['used'])} / {util.human_size(drive['total'])}",
                style=TEXT,
            )
            text.append(f"   {util.human_size(drive['free'])} free", style=DIM)
            text.append(f"   {percent:.0f}%\n", style=f"bold {color}")
        self.query_one("#drive-lines", Static).update(text or "  no fixed drives")

    def _refresh_quarantine(self) -> None:
        size, items = safety.quarantine_usage()
        state = self.app.state
        state.quarantine_size, state.quarantine_items = size, items
        self.query_one("#stat-quar", StatCard).set_value(
            util.human_size(size), f"{items:,} items held"
        )
        drives = paths.drive_usage()
        if drives:
            primary = drives[0]
            self.query_one("#stat-free", StatCard).set_value(
                util.human_size(primary["free"]),
                f"{primary['letter']} · {primary['percent']:.0f}% used",
                tone=GOOD if primary["percent"] < 80 else WARN,
            )

    def _refresh_activity(self) -> None:
        log = self.query_one("#activity", RichLog)
        log.clear()
        lines = safety.read_log_tail(40)
        if not lines:
            log.write(Text("  nothing yet — start with a scan", style=MUTED))
            return
        for line in reversed(lines):
            line = line.rstrip()
            if " ERR " in line:
                style = BAD
            elif " OK " in line:
                style = DIM
            else:
                style = TEXT
            log.write(Text(line, style=style))

    @work(thread=True, exclusive=True, group="dashboard")
    def _refresh_stats_async(self) -> None:
        infos = procs.collect()
        state = self.app.state
        state.proc_total = len(infos)
        state.idle_count = sum(1 for p in infos if p.group == "idle")
        try:
            self.app.call_from_thread(self._refresh_stats)
        except Exception:  # noqa: BLE001 - app may be shutting down
            pass

    def _refresh_stats(self) -> None:
        state = self.app.state
        if state.junk_scanned:
            self.query_one("#stat-junk", StatCard).set_value(
                util.human_size(state.junk_size),
                f"{state.junk_files:,} files scanned",
            )
        if state.proc_total:
            self.query_one("#stat-procs", StatCard).set_value(
                str(state.idle_count),
                f"of {state.proc_total} processes",
                tone=BAD if state.idle_count else GOOD,
            )
        drives = paths.drive_usage()
        if drives:
            primary = drives[0]
            self.query_one("#stat-free", StatCard).set_value(
                util.human_size(primary["free"]),
                f"{primary['letter']} · {primary['percent']:.0f}% used",
                tone=GOOD if primary["percent"] < 80 else WARN,
            )


class SweepApp(App[None]):
    CSS_PATH = "style.tcss"
    TITLE = "Sweep"
    SUB_TITLE = "Windows cleanup console"
    ENABLE_COMMAND_PALETTE = False

    mode: reactive[str] = reactive("quarantine")

    BINDINGS = [
        Binding("1", "view('dashboard')", "Dashboard", show=False),
        Binding("2", "view('junk')", "Junk", show=False),
        Binding("3", "view('procs')", "Processes", show=False),
        Binding("4", "view('leftovers')", "Leftovers", show=False),
        Binding("5", "view('remover')", "Remover", show=False),
        Binding("6", "view('quarantine')", "Quarantine", show=False),
        Binding("q", "quit", "Quit", show=False),
        Binding("question_mark", "help", "Help", show=False),
        Binding("s", "settings", "Settings", show=False),
        Binding("u", "check_updates", "Check for updates", show=False),
        Binding("r", "refresh_pane", "Rescan", show=False),
        Binding("space", "toggle_row", "Toggle", show=False),
        Binding("a", "select_all", "All", show=False),
        Binding("n", "select_none", "None", show=False),
        Binding("x", "primary", "Run", show=False),
        Binding("i", "select_idle", "Idle", show=False),
        Binding("o", "open_item", "Open", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self._active = "dashboard"
        self._clock = ""
        self._topbar: TopBar | None = None
        self._safety: SafetyCard | None = None
        self._statusbar: StatusBar | None = None
        self._last_update: updates.CheckResult | None = None
        self._update_latest = ""
        self._pending_release: updates.Release | None = None
        # The shared config store owns the file: writing only {"mode": ...}
        # here would erase the update preferences the web UI saved.
        self.mode = config.get_mode()

    # -- composition -----------------------------------------------------
    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static("", id="brand")
                for view, number, label in NAV_ITEMS:
                    yield NavItem(view, number, label, id=f"nav-{view}")
                yield Static("", id="sidebar-spacer")
                yield SafetyCard(id="safety")
            with ContentSwitcher(initial="view-dashboard", id="views"):
                yield DashboardPane(id="view-dashboard")
                yield JunkPane(id="view-junk")
                yield ProcsPane(id="view-procs")
                yield LeftoversPane(id="view-leftovers")
                yield RemoverPane(id="view-remover")
                yield QuarantinePane(id="view-quarantine")
        yield StatusBar(id="statusbar")

    def on_mount(self) -> None:
        self._topbar = self.query_one(TopBar)
        self._safety = self.query_one(SafetyCard)
        self._statusbar = self.query_one(StatusBar)
        self.query_one("#brand", Static).update(self._brand_text())
        self._update_chrome()
        self.set_interval(1.0, self._tick)
        self.query_one("#views", ContentSwitcher).focus()
        # Fire-and-forget: the worker thread does the (optional) request, so
        # startup never waits on the network. ``check`` is a no-op when checks
        # are disabled or no source is configured.
        self.check_for_updates(force=False, explicit=False)

    @staticmethod
    def _brand_text() -> Text:
        text = Text()
        text.append("SWEEP\n", style=f"bold {ACCENT}")
        text.append("cleanup console", style=MUTED)
        return text

    # -- chrome ----------------------------------------------------------
    def _update_chrome(self) -> None:
        if self._topbar is None:
            return
        elevated = admin.is_admin()
        self._topbar.update_bar(
            self.mode, elevated, self._clock, self._update_latest
        )
        if self._safety is not None:
            self._safety.set_mode(self.mode)
        if self._statusbar is not None:
            self._statusbar.show(self._active, self.mode)

    def _tick(self) -> None:
        from datetime import datetime

        clock = datetime.now().strftime("%H:%M")
        if clock != self._clock:
            self._clock = clock
            if self._topbar is not None:
                self._topbar.update_bar(
                    self.mode, admin.is_admin(), clock, self._update_latest
                )

    def watch_mode(self, _value: str) -> None:
        if self.is_mounted:
            self._update_chrome()

    # -- config ----------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        try:
            config.set_mode(mode)
        except (OSError, ValueError) as exc:
            self.notify(
                f"Delete mode changed for this session, but could not be saved: {exc}",
                severity="warning",
                timeout=6,
            )
        self._update_chrome()
        if mode == "permanent":
            self.notify(
                "Permanent delete is ON — removals cannot be undone.",
                severity="warning",
                timeout=6,
            )
        else:
            self.notify("Quarantine is ON — removals can be restored.", timeout=4)

    # -- updates ---------------------------------------------------------
    def action_check_updates(self) -> None:
        """The global ``u`` binding: an explicit check always answers."""
        self.check_for_updates(force=True, explicit=True)

    def check_for_updates(self, *, force: bool = True, explicit: bool = True) -> None:
        """Start one check on a worker thread; the interface keeps painting."""
        self._update_check_worker(force, explicit)

    @work(thread=True, exclusive=True, group="update")
    def _update_check_worker(self, force: bool, explicit: bool) -> None:
        # ``check`` never raises and returns immediately when checks are off or
        # no manifest URL is configured, so this is safe at launch.
        result = updates.check(force=force, timeout=4.0)
        try:
            self.call_from_thread(self._update_check_done, result, explicit)
        except Exception:  # noqa: BLE001 - the app may be exiting
            pass

    def _update_check_done(self, result: updates.CheckResult, explicit: bool) -> None:
        self._last_update = result
        available = result.status == updates.STATUS_AVAILABLE
        self._update_latest = result.latest if available else ""
        self._update_chrome()
        self._refresh_settings_updates()

        if available:
            self.notify(
                f"Sweep {result.latest} is available — press s to install",
                title="Update available",
                timeout=8,
            )
            return
        if not explicit:
            # Automatic checks stay quiet unless there is something to offer.
            return

        if result.status == updates.STATUS_ERROR:
            detail = f"{result.message}. {result.reason}"
            if result.hint:
                detail += f" {result.hint}"
            self.notify(
                detail, title="Update check failed", severity="warning", timeout=12
            )
        elif result.status in (updates.STATUS_UNCONFIGURED, updates.STATUS_DISABLED):
            detail = result.message
            if result.hint:
                detail += f" — {result.hint}"
            self.notify(detail, title="Updates", severity="warning", timeout=9)
        elif result.status == updates.STATUS_SKIPPED:
            detail = result.message
            if result.hint:
                detail += f" — {result.hint}"
            self.notify(detail, title="Updates", timeout=7)
        else:
            self.notify(
                result.message or "Sweep is up to date.", title="Updates", timeout=5
            )

    def last_update_result(self) -> updates.CheckResult | None:
        """The newest answer for this session, or the one saved in config."""
        if self._last_update is not None:
            return self._last_update
        try:
            state = updates.state()
        except Exception:  # noqa: BLE001 - the settings dialog must still open
            return None
        stored = state.get("last_result")
        if isinstance(stored, dict):
            try:
                self._last_update = updates.CheckResult.from_dict(stored)
            except (TypeError, ValueError):
                return None
        return self._last_update

    def _refresh_settings_updates(self) -> None:
        for screen in self.screen_stack:
            if isinstance(screen, SettingsScreen):
                try:
                    screen.refresh_updates()
                except Exception:  # noqa: BLE001 - a closing dialog is harmless
                    pass

    # -- install ---------------------------------------------------------
    def install_update(self) -> None:
        result = self.last_update_result()
        offerable = (
            result is not None
            and result.release is not None
            and result.status in (updates.STATUS_AVAILABLE, updates.STATUS_SKIPPED)
        )
        if not offerable:
            self.notify(
                "No update is ready to install — press u to check again.",
                title="Updates",
                timeout=6,
            )
            return
        release = result.release
        if release is None:
            return
        self._pending_release = release
        size = f" ({util.human_size(release.size)})" if release.size else ""
        message = Text()
        message.append(
            f"Download Sweep {release.version}{size} and install it now?\n\n",
            style=TEXT,
        )
        message.append(
            "Sweep downloads the release over HTTPS, verifies its SHA-256 "
            "checksum, replaces the program files, then restarts.\n\n",
            style=TEXT,
        )
        message.append(
            "Your quarantine, logs and settings are kept. The files being "
            "replaced are backed up first.",
            style=GOOD,
        )
        self.push_screen(
            ConfirmScreen(
                f"INSTALL SWEEP {release.version}",
                message,
                confirm_label="Download & install",
                danger=False,
                hint="Sweep closes briefly while the update helper swaps the files.",
            ),
            self._install_confirmed,
        )

    def _install_confirmed(self, confirmed: bool | None) -> None:
        release = self._pending_release
        self._pending_release = None
        if not confirmed or release is None:
            return
        self._install_worker(release)

    def _relaunch_argv(self) -> list[str]:
        """The command line that reopens this same interface after the update."""
        if getattr(sys, "frozen", False):
            return [sys.executable, *sys.argv[1:]]
        base = [sys.executable, str(updates.app_root() / "main.py")]
        # ``sweep web`` must come back as the web UI, not the terminal one.
        if "web" in sys.argv[1:]:
            return [*base, *sys.argv[sys.argv.index("web") :]]
        return base

    @work(thread=True, exclusive=True, group="update-install")
    def _install_worker(self, release: updates.Release) -> None:
        last_step = 0
        try:
            self.notify(
                f"Downloading Sweep {release.version}…", title="Update", timeout=3
            )

            def progress(done: int, total: int) -> None:
                nonlocal last_step
                if total <= 0:
                    return
                step = (min(100, int(done * 100 / total)) // 25) * 25
                # Milestones only: a toast per network chunk would be noise.
                if 0 < step < 100 and step > last_step:
                    last_step = step
                    self.notify(
                        f"Downloading Sweep {release.version}… {step}%",
                        title="Update",
                        timeout=2,
                    )

            archive = updates.download(release, progress=progress)
            self.notify(
                "Download verified — preparing the new files…",
                title="Update",
                timeout=3,
            )
            staged = updates.stage(archive, release)
            self.notify(
                "Installing — Sweep will restart in a moment.",
                title="Update",
                timeout=4,
            )
            updates.apply(staged, release, relaunch=self._relaunch_argv())
            self.call_from_thread(self._finish_install)
        except updates.UpdateError as exc:
            self.call_from_thread(self._install_failed, exc)
        except Exception as exc:  # noqa: BLE001 - report, never crash the app
            self.call_from_thread(
                self._install_failed,
                updates.UpdateError(
                    "install_failed",
                    "The update failed unexpectedly",
                    f"{type(exc).__name__}: {exc}",
                    "Try again from Settings → Updates; the current version is untouched.",
                ),
            )

    def _finish_install(self) -> None:
        # The detached helper waits for this PID, so exiting is part of the plan.
        self.exit()

    def _install_failed(self, error: updates.UpdateError) -> None:
        detail = error.message
        if error.reason:
            detail += f" — {error.reason}"
        if error.hint:
            detail += f" {error.hint}"
        self.notify(detail, title="Update failed", severity="error", timeout=12)
        self._refresh_settings_updates()

    def skip_update(self, release: updates.Release) -> None:
        try:
            config.set_updates({"skipped": release.version})
        except (OSError, ValueError) as exc:
            self.notify(
                f"Could not remember that choice: {exc}", severity="error", timeout=8
            )
            return
        result = self._last_update
        if result is not None and result.release is not None:
            skipped = updates.CheckResult(
                status=updates.STATUS_SKIPPED,
                current=result.current,
                latest=release.version,
                release=release,
                checked_at=time.time(),
                message=f"Sweep {release.version} is available (skipped)",
                reason="You chose “not now” for this version.",
                hint="Install it from Settings → Updates whenever you are ready.",
            )
            self._last_update = skipped
            try:
                config.record_check(skipped.to_dict())
            except OSError:
                pass
        self._update_latest = ""
        self._update_chrome()
        self._refresh_settings_updates()
        self.notify(
            f"Sweep {release.version} will not be offered again.",
            title="Updates",
            timeout=5,
        )

    def set_update_checks(self, enabled: bool) -> None:
        try:
            config.set_updates({"enabled": bool(enabled)})
        except (OSError, ValueError) as exc:
            self.notify(
                f"Could not save that setting: {exc}", severity="error", timeout=8
            )
            return
        if enabled:
            self._last_update = None
            self.notify("Update checks are on.", title="Updates", timeout=5)
            # Turning checks back on is an explicit request to look now.
            self.check_for_updates(force=True, explicit=False)
        else:
            self._last_update = updates.CheckResult(
                status=updates.STATUS_DISABLED,
                checked_at=time.time(),
                message="Update checks are off",
                reason="“Check for updates” is disabled in Settings.",
                hint="Turn it on here, or run “sweep update --check”.",
            )
            self._update_latest = ""
            self.notify(
                "Update checks are off — Sweep will make no update request.",
                title="Updates",
                timeout=5,
            )
        self._update_chrome()
        self._refresh_settings_updates()

    # -- pane helpers ----------------------------------------------------
    def _pane(self):
        return self.query_one(f"#view-{self._active}")

    def _typing(self) -> bool:
        return isinstance(self.focused, Input)

    def action_view(self, view: str) -> None:
        if view == self._active:
            return
        switcher = self.query_one("#views", ContentSwitcher)
        switcher.current = f"view-{view}"
        self._active = view
        for item in self.query(NavItem):
            item.set_active(item.view == view)
        self._update_chrome()
        pane = self._pane()
        if hasattr(pane, "on_show"):
            pane.on_show()
        if hasattr(pane, "focus_table"):
            pane.focus_table()

    def on_nav_item_selected(self, message: NavItem.Selected) -> None:
        self.action_view(message.view)

    def action_refresh_pane(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "rescan"):
            pane.rescan()

    def action_toggle_row(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "toggle_cursor"):
            pane.toggle_cursor()

    def action_select_all(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "select_all"):
            pane.select_all()

    def action_select_none(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "select_none"):
            pane.select_none()

    def action_primary(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "primary_action"):
            pane.primary_action()

    def action_select_idle(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "select_idle"):
            pane.select_idle()

    def action_open_item(self) -> None:
        if self._typing():
            return
        pane = self._pane()
        if hasattr(pane, "open_item"):
            pane.open_item()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())


def run() -> int:
    app = SweepApp()
    app.run()
    return 0
