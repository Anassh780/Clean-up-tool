"""Shared widgets and styling helpers for the Sweep interface."""
from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from .. import __version__, admin, paths, updates, util

ACCENT = "#22d3ee"
ACCENT_SOFT = "#67e8f9"
VIOLET = "#a78bfa"
GOOD = "#34d399"
WARN = "#fbbf24"
BAD = "#fb7185"
DIM = "#64748b"
MUTED = "#475569"
TEXT = "#c9d6e4"
PANEL = "#0b1119"

STATE_COLORS = {
    "idle": BAD,
    "linked": "#7dd3fc",
    "tray": WARN,
    "active": GOOD,
    "service": "#94a3b8",
    "system": MUTED,
    "locked": MUTED,
}

RISK_COLORS = {"safe": GOOD, "caution": WARN, "risky": BAD}

UPDATE_TONES = {
    updates.STATUS_AVAILABLE: GOOD,
    updates.STATUS_UP_TO_DATE: DIM,
    updates.STATUS_SKIPPED: WARN,
    updates.STATUS_ERROR: BAD,
    updates.STATUS_UNCONFIGURED: WARN,
    updates.STATUS_DISABLED: MUTED,
}


def risk_text(risk: str) -> Text:
    return Text(risk.upper(), style=f"bold {RISK_COLORS.get(risk, DIM)}")


def dot(color: str) -> Text:
    return Text("●", style=color)


def badge(label: str, color: str) -> Text:
    return Text(f" {label} ", style=f"bold #06121a on {color}")


def keycap(key: str) -> Text:
    return Text(f" {key} ", style="bold #dbeafe on #1e2a36")


class StatCard(Static):
    """A single number with a label and a quiet sub-line."""

    def __init__(
        self,
        label: str,
        value: str = "—",
        sub: str = "",
        tone: str = ACCENT,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._value = value
        self._sub = sub
        self._tone = tone
        self.add_class("stat-card")

    def on_mount(self) -> None:
        self.set_value(self._value, self._sub)

    def set_value(self, value: str, sub: str | None = None, tone: str | None = None) -> None:
        self._value = value
        if sub is not None:
            self._sub = sub
        if tone is not None:
            self._tone = tone
        text = Text()
        text.append(self._label + "\n", style=f"bold {DIM}")
        text.append(str(value) + "\n", style=f"bold {self._tone}")
        text.append(self._sub, style=f"{MUTED}")
        self.update(text)


class ConfirmScreen(ModalScreen[bool]):
    """Blocking confirmation dialog with optional type-to-confirm."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        message: str | Text,
        confirm_label: str = "Confirm",
        danger: bool = True,
        require_text: str | None = None,
        hint: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._danger = danger
        self._require_text = require_text
        self._hint = hint

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static(self._title, id="dialog-title")
            yield Static(self._message, id="dialog-body")
            if self._hint:
                yield Static(self._hint, id="dialog-hint")
            if self._require_text:
                yield Input(
                    placeholder=f'type "{self._require_text}" to unlock',
                    id="dialog-input",
                )
            with Horizontal(id="dialog-buttons"):
                yield Button("Cancel", id="dialog-cancel")
                yield Button(
                    self._confirm_label,
                    id="dialog-confirm",
                    variant="error" if self._danger else "primary",
                )

    def on_mount(self) -> None:
        if self._require_text:
            self.query_one("#dialog-confirm", Button).disabled = True
            self.query_one("#dialog-input", Input).focus()
        else:
            self.query_one("#dialog-confirm", Button).focus()

    def _unlocked(self) -> bool:
        if not self._require_text:
            return True
        return (
            self.query_one("#dialog-input", Input).value.strip().lower()
            == self._require_text.lower()
        )

    @on(Input.Changed, "#dialog-input")
    def _on_changed(self, event: Input.Changed) -> None:
        self.query_one("#dialog-confirm", Button).disabled = not self._unlocked()

    @on(Input.Submitted, "#dialog-input")
    def _on_submitted(self, _event: Input.Submitted) -> None:
        if self._unlocked():
            self.dismiss(True)

    @on(Button.Pressed, "#dialog-confirm")
    def _on_confirm(self, _event: Button.Pressed) -> None:
        if self._unlocked():
            self.dismiss(True)

    @on(Button.Pressed, "#dialog-cancel")
    def _on_cancel(self, _event: Button.Pressed) -> None:
        self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("question_mark", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        rows = [
            ("1 – 6", "switch between panes"),
            ("r", "rescan / refresh the current pane"),
            ("space", "toggle the highlighted row"),
            ("a / n", "select all / select none"),
            ("x", "run the pane's main action (clean, kill, remove, restore)"),
            ("i", "processes: select every idle process"),
            ("o", "leftovers: open the highlighted folder"),
            ("s", "settings"),
            ("u", "check for updates"),
            ("?", "this help"),
            ("q", "quit"),
        ]
        body = Text()
        for key, description in rows:
            body.append(f"  {key:<8}", style=f"bold {ACCENT}")
            body.append(f"{description}\n", style=TEXT)
        with Container(id="dialog", classes="wide"):
            yield Static("KEYS", id="dialog-title")
            yield Static(body, id="dialog-body")
            yield Static(
                "Deletions are quarantined; Windows-critical paths are refused.\n"
                "Update checks live in Settings → Updates.",
                id="dialog-hint",
            )
            with Horizontal(id="dialog-buttons"):
                yield Button("Close", id="dialog-cancel", variant="primary")

    def on_mount(self) -> None:
        # Close is the only focusable widget. On a 24-row terminal focusing it
        # scrolls the dialog to the bottom, so start at the first key instead.
        self.call_after_refresh(self._scroll_home)

    def _scroll_home(self) -> None:
        try:
            self.query_one("#dialog").scroll_home(animate=False)
        except Exception:  # noqa: BLE001 - the dialog may already be closed
            pass

    @on(Button.Pressed, "#dialog-cancel")
    def _close(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class SettingsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        app = self.app
        mode = getattr(app, "mode", "quarantine")
        with Container(id="dialog", classes="wide settings"):
            yield Static("SETTINGS", id="dialog-title")
            # The dialog grows as update information arrives. A scroll body
            # keeps it usable on an 80x24 terminal while Close stays pinned.
            with VerticalScroll(id="settings-scroll"):
                yield Static(
                    "Quarantine keeps every removal restorable. Permanent delete skips the "
                    "holding area and frees the space immediately.",
                    id="dialog-hint",
                )
                with Horizontal(classes="setting-row"):
                    yield Static("Permanent delete", classes="setting-label")
                    yield Button(
                        "OFF",
                        id="perm-toggle",
                        variant="success" if mode != "permanent" else "error",
                    )
                yield Static("", id="perm-state", classes="setting-note")
                yield Static("UPDATES", classes="settings-section")
                yield Static("", id="updates-status")
                # Two short rows so all four buttons fit an 80-column dialog.
                with Vertical(id="updates-actions"):
                    with Horizontal(classes="updates-row"):
                        yield Button("Check now", id="updates-check")
                        yield Button(
                            "Install update",
                            id="updates-install",
                            variant="primary",
                        )
                    with Horizontal(classes="updates-row"):
                        yield Button("Skip version", id="updates-skip")
                        yield Button("Turn checks off", id="updates-toggle")
                yield Static("", id="updates-url", classes="setting-note")
                yield Static("", id="updates-note", classes="setting-note")
                with Horizontal(id="settings-actions"):
                    yield Button("Open quarantine", id="open-quarantine")
                    yield Button("Open logs", id="open-logs")
                    if not admin.is_admin():
                        yield Button(
                            "Relaunch as admin", id="relaunch", variant="warning"
                        )
                yield Static(
                    f"Data folder   {paths.SWEEP_HOME}\n"
                    f"Log file      {paths.LOGS / 'sweep-<date>.log'}\n"
                    f"Elevation     {'Administrator' if admin.is_admin() else 'Standard user (some categories need admin)'}\n"
                    f"Version       {__version__}",
                    id="settings-info",
                )
            with Horizontal(id="dialog-buttons"):
                yield Button("Close", id="dialog-cancel", variant="primary")

    def on_mount(self) -> None:
        self._sync_note()
        self.refresh_updates()

    # -- update card -----------------------------------------------------
    def _state(self) -> dict:
        try:
            return updates.state()
        except Exception:  # noqa: BLE001 - a broken config must not close settings
            return {}

    def _result(self, state: dict) -> updates.CheckResult | None:
        getter = getattr(self.app, "last_update_result", None)
        if callable(getter):
            try:
                result = getter()
            except Exception:  # noqa: BLE001
                result = None
            if isinstance(result, updates.CheckResult):
                return result
        stored = state.get("last_result")
        if isinstance(stored, dict):
            try:
                return updates.CheckResult.from_dict(stored)
            except (TypeError, ValueError):
                return None
        return None

    def _inner_width(self) -> int:
        """How many cells the dialog body has, for truncating long URLs."""
        size = getattr(self.app, "size", None)
        screen_width = int(getattr(size, "width", 100) or 100)
        dialog = min(88, int(screen_width * 0.92))
        return max(24, dialog - 8)

    def refresh_updates(self) -> None:
        """Re-render the Updates block from config + the last check result."""
        state = self._state()
        result = self._result(state)
        current = str(state.get("current") or __version__)
        enabled = bool(state.get("enabled", True))
        configured = bool(state.get("configured", False))
        url = str(state.get("manifest_url") or "")
        checked = float(state.get("last_check") or 0.0)
        if result is not None and result.checked_at:
            checked = result.checked_at

        status = Text()
        status.append(f"Version {current}", style=TEXT)
        status.append("  ·  ", style=MUTED)
        status.append(
            "checks on" if enabled else "checks off", style=GOOD if enabled else WARN
        )
        status.append("  ·  ", style=MUTED)
        status.append(
            f"checked {util.human_age(checked)}" if checked else "not checked yet",
            style=DIM,
        )
        if result is not None:
            tone = UPDATE_TONES.get(result.status, TEXT)
            status.append("\n")
            status.append(
                result.message or result.status.replace("_", " "), style=f"bold {tone}"
            )
            if result.status == updates.STATUS_ERROR and result.hint:
                status.append(f"\n{result.hint}", style=MUTED)
        elif not enabled:
            status.append("\nUpdate checks are off.", style=MUTED)
        else:
            status.append("\nNo check has run yet.", style=MUTED)
        self.query_one("#updates-status", Static).update(status)

        if configured and url:
            source = util.middle_truncate(url, self._inner_width())
            self.query_one("#updates-url", Static).update(
                Text(f"Source  {source}", style=DIM)
            )
        elif configured:
            self.query_one("#updates-url", Static).update(
                Text("Source  built into this release", style=DIM)
            )
        else:
            self.query_one("#updates-url", Static).update(
                Text("No update source configured.", style=WARN)
            )

        if not configured:
            note = (
                "Set it in the web Settings page, or in "
                "%LOCALAPPDATA%\\Sweep\\config.json — see docs/RELEASING.md."
            )
        elif not enabled:
            note = "Sweep makes no update request while checks are off."
        else:
            note = ""
        self.query_one("#updates-note", Static).update(
            Text(note, style=MUTED) if note else ""
        )

        offer = (
            result is not None
            and result.release is not None
            and result.status in (updates.STATUS_AVAILABLE, updates.STATUS_SKIPPED)
        )
        install = self.query_one("#updates-install", Button)
        install.display = offer
        self.query_one("#updates-skip", Button).display = (
            result is not None and result.status == updates.STATUS_AVAILABLE
        )
        self.query_one("#updates-toggle", Button).label = (
            "Turn checks off" if enabled else "Turn checks on"
        )

    def _sync_note(self) -> None:
        note = self.query_one("#perm-state", Static)
        toggle = self.query_one("#perm-toggle", Button)
        permanent = getattr(self.app, "mode", "quarantine") == "permanent"
        toggle.label = "ON" if permanent else "OFF"
        toggle.variant = "error" if permanent else "success"
        if permanent:
            note.update(
                Text(
                    "Permanent delete is ON — removals cannot be undone.",
                    style=f"bold {BAD}",
                )
            )
        else:
            note.update(
                Text(
                    "Quarantine is ON — removals can be restored later.",
                    style=f"bold {GOOD}",
                )
            )

    @on(Button.Pressed, "#perm-toggle")
    def _mode_changed(self, _event: Button.Pressed) -> None:
        app = self.app
        if hasattr(app, "set_mode"):
            current = getattr(app, "mode", "quarantine")
            app.set_mode("quarantine" if current == "permanent" else "permanent")
        self._sync_note()

    @on(Button.Pressed, "#updates-check")
    def _check_updates(self, _event: Button.Pressed) -> None:
        self.app.notify("Checking for updates…", timeout=2)
        checker = getattr(self.app, "check_for_updates", None)
        if callable(checker):
            checker(force=True, explicit=True)
        else:
            self.app.notify(
                "Update checking is unavailable in this build.", severity="warning"
            )

    @on(Button.Pressed, "#updates-install")
    def _install_update(self, _event: Button.Pressed) -> None:
        installer = getattr(self.app, "install_update", None)
        if callable(installer):
            installer()
        else:
            self.app.notify(
                "Installing updates is unavailable in this build.", severity="warning"
            )

    @on(Button.Pressed, "#updates-skip")
    def _skip_update(self, _event: Button.Pressed) -> None:
        result = self._result(self._state())
        if result is not None and result.release is not None:
            skipper = getattr(self.app, "skip_update", None)
            if callable(skipper):
                skipper(result.release)

    @on(Button.Pressed, "#updates-toggle")
    def _toggle_checks(self, _event: Button.Pressed) -> None:
        state = self._state()
        setter = getattr(self.app, "set_update_checks", None)
        if callable(setter):
            setter(not bool(state.get("enabled", True)))
        else:
            self.app.notify(
                "Update settings are unavailable in this build.", severity="warning"
            )

    @on(Button.Pressed, "#open-quarantine")
    def _open_quarantine(self, _event: Button.Pressed) -> None:
        util.open_in_explorer(paths.QUARANTINE)

    @on(Button.Pressed, "#open-logs")
    def _open_logs(self, _event: Button.Pressed) -> None:
        util.open_in_explorer(paths.LOGS)

    @on(Button.Pressed, "#relaunch")
    def _relaunch(self, _event: Button.Pressed) -> None:
        launched, error = admin.relaunch_as_admin()
        if launched:
            self.app.exit()
        else:
            self.app.notify(f"Could not elevate: {error}", severity="error")

    @on(Button.Pressed, "#dialog-cancel")
    def _close(self, _event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class PaneHeader(Horizontal):
    """Title + subtitle on the left, live meta text on the right."""

    def __init__(self, title: str, subtitle: str, meta_id: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._subtitle = subtitle
        self._meta_id = meta_id
        self.add_class("pane-head")

    def compose(self) -> ComposeResult:
        with Vertical(classes="pane-title-wrap"):
            yield Static(self._title, classes="pane-title")
            yield Static(self._subtitle, classes="pane-sub")
        yield Static("", id=self._meta_id or None, classes="pane-meta")


class ConfirmableMixin:
    """Tiny helper so panes can call the shared confirmation dialog."""

    app: object

    def confirm(
        self,
        title: str,
        message: str,
        callback,
        confirm_label: str = "Confirm",
        danger: bool = True,
        require_text: str | None = None,
        hint: str = "",
    ) -> None:
        self.app.push_screen(
            ConfirmScreen(
                title,
                message,
                confirm_label=confirm_label,
                danger=danger,
                require_text=require_text,
                hint=hint,
            ),
            callback,
        )
