"""Processes pane: keep what is in use, terminate windowless leftovers."""
from __future__ import annotations

import threading

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, ProgressBar, Static

from .. import procs, safety, util
from .common import (
    ACCENT,
    BAD,
    DIM,
    GOOD,
    MUTED,
    STATE_COLORS,
    TEXT,
    WARN,
    ConfirmableMixin, PaneHeader,
)

FILTERS = {
    "all": ("All", lambda p: True),
    "active": ("Active", lambda p: p.group == "active"),
    "tray": ("Tray", lambda p: p.group == "tray"),
    "idle": ("Idle", lambda p: p.group == "idle"),
    "system": ("System", lambda p: p.group in ("system", "service", "locked", "linked")),
}


class ProcsPane(ConfirmableMixin, Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.infos: list[procs.ProcessInfo] = []
        self.checked: set[int] = set()
        self._filter = "all"
        self._visible: list[procs.ProcessInfo] = []
        self._cancel = threading.Event()
        self._loaded = False
        self._busy = False
        self._cols = []

    def compose(self) -> ComposeResult:
        yield PaneHeader(
            "PROCESSES",
            "Windows images, visible windows and tray apps are never auto-killed.",
            "procs-meta",
        )
        with Horizontal(id="procs-filters", classes="actions"):
            for key, (label, _fn) in FILTERS.items():
                yield Button(label, id=f"filter-{key}", classes="filter")
            yield Static("", id="procs-spacer")
            yield Button("Refresh", id="procs-refresh")
            yield Button("Select idle", id="procs-select-idle")
            yield Button("Clear", id="procs-clear")
            yield Button("Kill selected", id="procs-kill", variant="error")
        yield ProgressBar(total=100, show_eta=False, id="procs-progress")
        yield DataTable(id="procs-table", cursor_type="row", zebra_stripes=True)
        yield Static(
            "Reading processes…",
            id="procs-empty",
            classes="empty-state",
        )
        yield Static("", id="procs-detail", classes="detail")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._cols = table.add_columns("", "PID", "PROCESS", "STATE", "WIN", "RAM", "CPU", "PATH")
        self.query_one("#procs-progress", ProgressBar).display = False
        self.query_one("#procs-table", DataTable).display = False
        self._set_filter_button("all")

    def focus_table(self) -> None:
        self.query_one(DataTable).focus()

    # -- data ------------------------------------------------------------
    def on_show(self) -> None:
        if not self._loaded:
            self.reload()

    def rescan(self) -> None:
        self.reload()

    def reload(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.query_one("#procs-progress", ProgressBar).display = True
        self.query_one("#procs-progress", ProgressBar).update(total=1, progress=0)
        self._load_worker(self._cancel)

    @work(thread=True, exclusive=True, group="procs")
    def _load_worker(self, cancel: threading.Event) -> None:
        try:
            infos = procs.collect(cancel)
        except Exception as exc:  # noqa: BLE001
            safety.log_event("procs-crash", str(exc), ok=False)
            infos = []
        try:
            self.app.call_from_thread(self._loaded_infos, infos)
        except Exception:  # noqa: BLE001
            pass

    def _loaded_infos(self, infos: list[procs.ProcessInfo]) -> None:
        self.infos = infos
        self._loaded = True
        self._busy = False
        self.query_one("#procs-progress", ProgressBar).display = False
        alive = {info.pid for info in infos}
        self.checked &= alive
        self._refresh_table()
        state = self.app.state
        state.proc_total = len(infos)
        state.idle_count = sum(1 for p in infos if p.group == "idle")

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        predicate = FILTERS[self._filter][1]
        self._visible = [info for info in self.infos if predicate(info)]
        table.display = bool(self._visible)
        empty = self.query_one("#procs-empty", Static)
        empty.display = not self._visible
        if not self._visible:
            empty.update(
                "No processes in this filter.\n\n"
                "Idle means a third-party app with no window, no tray presence\n"
                "and no protected parent. That is what Sweep can safely stop."
                if self._filter == "idle"
                else "No processes in this filter."
            )
        for info in self._visible:
            table.add_row(
                self._marker(info.pid),
                str(info.pid),
                Text(info.name or "?", style=f"bold {TEXT}" if info.group == "idle" else TEXT),
                Text(info.state, style=f"bold {STATE_COLORS.get(info.group, DIM)}"),
                f"{info.visible_windows}/{info.hidden_windows}" if (info.visible_windows or info.hidden_windows) else "—",
                util.human_size(info.rss),
                f"{info.cpu:.1f}%",
                Text(util.middle_truncate(info.exe or "—", 56), style=MUTED),
                key=str(info.pid),
            )
        self._update_meta()
        self._update_detail()

    def _marker(self, pid: int) -> Text:
        return Text("●", style=ACCENT) if pid in self.checked else Text("○", style=MUTED)

    def _update_meta(self) -> None:
        counts: dict[str, int] = {}
        for info in self.infos:
            counts[info.group] = counts.get(info.group, 0) + 1
        text = Text()
        text.append(f"{counts.get('idle', 0)} idle", style=f"bold {BAD}")
        text.append(f"  ·  {counts.get('tray', 0)} tray", style=WARN)
        text.append(f"  ·  {counts.get('active', 0)} active", style=GOOD)
        text.append(f"  ·  {len(self.infos)} total", style=MUTED)
        self.query_one("#procs-meta", Static).update(text)

    def _update_detail(self) -> None:
        detail = self.query_one("#procs-detail", Static)
        table = self.query_one(DataTable)
        index = table.cursor_row
        if not (0 <= index < len(self._visible)):
            detail.update("")
            return
        info = self._visible[index]
        text = Text()
        text.append(f"{info.reason}", style=TEXT)
        if info.exe:
            text.append(f"   {info.exe}", style=MUTED)
        detail.update(text)

    def _set_filter_button(self, key: str) -> None:
        self._filter = key
        for candidate in FILTERS:
            button = self.query_one(f"#filter-{candidate}", Button)
            button.set_class(candidate == key, "active")

    # -- selection -------------------------------------------------------
    def _toggle(self, pid: int) -> None:
        if pid in self.checked:
            self.checked.discard(pid)
        else:
            info = next((i for i in self._visible if i.pid == pid), None)
            if info is None or not info.killable:
                self.app.notify(
                    f"{info.name if info else 'Process'} is protected — Sweep will not kill it.",
                    severity="warning",
                    timeout=3,
                )
                return
            self.checked.add(pid)
        self.query_one(DataTable).update_cell(str(pid), self._cols[0], self._marker(pid))

    def toggle_cursor(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self._visible):
            self._toggle(self._visible[table.cursor_row].pid)

    def select_all(self) -> None:
        for info in self._visible:
            if info.killable:
                self.checked.add(info.pid)
        self._refresh_table()

    def select_none(self) -> None:
        self.checked.clear()
        self._refresh_table()

    def select_idle(self) -> None:
        self.checked = {info.pid for info in self.infos if info.group == "idle"}
        self._refresh_table()
        if not self.checked:
            self.app.notify(
                "No windowless leftovers right now — everything is in use or owned by Windows.",
                timeout=4,
            )

    def open_item(self) -> None:
        table = self.query_one(DataTable)
        index = table.cursor_row
        if 0 <= index < len(self._visible):
            info = self._visible[index]
            if info.exe:
                util.open_in_explorer(info.exe)

    # -- events ----------------------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            self._toggle(int(event.row_key.value or 0))
        except (TypeError, ValueError):
            pass

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id or ""
        if button.startswith("filter-"):
            self._set_filter_button(button.removeprefix("filter-"))
            self._refresh_table()
        elif button == "procs-refresh":
            self.reload()
        elif button == "procs-select-idle":
            self.select_idle()
        elif button == "procs-clear":
            self.select_none()
        elif button == "procs-kill":
            self.primary_action()

    # -- kill ------------------------------------------------------------
    def primary_action(self) -> None:
        if self._busy:
            self.app.notify("Still refreshing.", timeout=3)
            return
        targets = [info for info in self.infos if info.pid in self.checked and info.killable]
        if not targets:
            self.app.notify("Select one or more idle/tray processes first.", timeout=4)
            return
        ram = sum(info.rss for info in targets)
        message = Text()
        message.append(
            f"{len(targets)} processes, {util.human_size(ram)} of RAM\n", style=TEXT
        )
        names = ", ".join(info.name for info in targets[:6])
        if len(targets) > 6:
            names += f", +{len(targets) - 6} more"
        message.append(names + "\n", style=DIM)
        message.append(
            "Windows processes, tray apps you did not select and this session are untouched.",
            style=MUTED,
        )
        self.confirm(
            "TERMINATE PROCESSES",
            message,
            self._do_kill,
            confirm_label="Terminate",
            danger=True,
            require_text="kill" if len(targets) >= 5 else None,
        )

    def _do_kill(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        targets = [info for info in self.infos if info.pid in self.checked and info.killable]
        if not targets:
            return
        self._busy = True
        self.query_one("#procs-progress", ProgressBar).display = True
        self.query_one("#procs-progress", ProgressBar).update(
            total=max(1, len(targets)), progress=0
        )
        self._kill_worker(targets)

    @work(thread=True, exclusive=True, group="procs-kill")
    def _kill_worker(self, targets: list[procs.ProcessInfo]) -> None:
        results = procs.kill_processes(
            targets,
            progress=lambda done, total, name: self.app.call_from_thread(
                self._kill_progress, done, total
            ),
        )
        try:
            self.app.call_from_thread(self._kill_done, results)
        except Exception:  # noqa: BLE001
            pass

    def _kill_progress(self, done: int, total: int) -> None:
        self.query_one("#procs-progress", ProgressBar).update(progress=done, total=total)

    def _kill_done(self, results: list[procs.KillResult]) -> None:
        self._busy = False
        self.query_one("#procs-progress", ProgressBar).display = False
        ok = sum(1 for result in results if result.ok)
        failed = [result for result in results if not result.ok]
        self.checked.clear()
        self.app.notify(
            f"Terminated {ok} of {len(results)} processes."
            + (f" {len(failed)} refused or protected." if failed else ""),
            title="Processes",
            severity="warning" if failed else "information",
            timeout=6,
        )
        self.reload()
