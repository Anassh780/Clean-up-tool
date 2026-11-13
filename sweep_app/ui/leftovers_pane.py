"""Uninstall leftovers pane."""
from __future__ import annotations

import threading

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, ProgressBar, Static

from .. import leftovers, safety, util
from .common import ACCENT, BAD, DIM, GOOD, MUTED, TEXT, WARN, ConfirmableMixin, PaneHeader


class LeftoversPane(ConfirmableMixin, Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.orphans: list[leftovers.Orphan] = []
        self.checked: set[str] = set()
        self._cancel = threading.Event()
        self._busy = False
        self._loaded = False
        self._cols = []

    def compose(self) -> ComposeResult:
        yield PaneHeader(
            "UNINSTALL LEFTOVERS",
            "Folders no installed program claims and nothing has touched for three weeks.",
            "leftovers-meta",
        )
        with Horizontal(id="leftovers-actions", classes="actions"):
            yield Button("Scan", id="leftovers-scan", variant="primary")
            yield Button("Select orphans", id="leftovers-select")
            yield Button("Clear", id="leftovers-clear")
            yield Button("Remove selected", id="leftovers-remove", variant="error")
            yield Static("", id="leftovers-status", classes="progress-label")
        yield ProgressBar(total=100, show_eta=False, id="leftovers-progress")
        yield DataTable(id="leftovers-table", cursor_type="row", zebra_stripes=True)
        yield Static(
            "No stale leftovers.\n\n"
            "Every folder in AppData, ProgramData and Program Files belongs\n"
            "to an installed program — or was used in the last three weeks,\n"
            "so Sweep leaves it alone.",
            id="leftovers-empty",
            classes="empty-state",
        )
        yield Static("", id="leftovers-detail", classes="detail")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._cols = table.add_columns(
            "", "FOLDER", "LOCATION", "SIZE", "LAST USED", "CONFIDENCE"
        )
        self.query_one("#leftovers-progress", ProgressBar).display = False
        self.query_one("#leftovers-empty", Static).display = False

    def focus_table(self) -> None:
        self.query_one(DataTable).focus()

    # -- scan ------------------------------------------------------------
    def on_show(self) -> None:
        if not self._loaded:
            self.start_scan()

    def rescan(self) -> None:
        if not self._busy:
            self.start_scan()

    def start_scan(self) -> None:
        if self._busy:
            self._cancel.set()
            return
        self._busy = True
        self._loaded = True
        self._cancel = threading.Event()
        self.query_one("#leftovers-progress", ProgressBar).display = True
        self.query_one("#leftovers-progress", ProgressBar).update(total=100, progress=0)
        self.query_one("#leftovers-status", Static).update(
            Text("indexing installed programs…", style=ACCENT)
        )
        self._scan_worker(self._cancel)

    @work(thread=True, exclusive=True, group="leftovers")
    def _scan_worker(self, cancel: threading.Event) -> None:
        try:
            index = leftovers.build_index()
            orphans = leftovers.scan_orphans(
                cancel=cancel,
                progress=lambda message, fraction: self.app.call_from_thread(
                    self._progress, message, fraction
                ),
                index=index,
            )
        except Exception as exc:  # noqa: BLE001
            safety.log_event("leftovers-crash", str(exc), ok=False)
            orphans = []
        try:
            self.app.call_from_thread(self._scan_done, orphans)
        except Exception:  # noqa: BLE001
            pass

    def _progress(self, message: str, fraction: float) -> None:
        self.query_one("#leftovers-status", Static).update(Text(message, style=DIM))
        self.query_one("#leftovers-progress", ProgressBar).update(
            progress=max(0.0, min(100.0, fraction * 100))
        )

    def _scan_done(self, orphans: list[leftovers.Orphan]) -> None:
        self._busy = False
        self.orphans = orphans
        self.checked &= {orphan.path for orphan in orphans}
        self.query_one("#leftovers-progress", ProgressBar).display = False
        self.query_one("#leftovers-status", Static).update("")
        self._refresh_table()
        if not orphans:
            self.app.notify(
                "No stale leftovers — folders used in the last 3 weeks are left alone.",
                timeout=5,
            )

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        table.display = bool(self.orphans)
        self.query_one("#leftovers-empty", Static).display = not self.orphans
        for orphan in self.orphans:
            confidence = (
                Text("orphan", style=f"bold {BAD}")
                if orphan.confidence == "orphan"
                else Text("suspect", style=WARN)
            )
            table.add_row(
                self._marker(orphan.path),
                Text(orphan.name, style=TEXT),
                Text(orphan.root_label, style=DIM),
                util.human_size(orphan.size),
                orphan.last_used,
                confidence,
                key=orphan.path,
            )
        self._update_meta()
        self._update_detail()

    def _marker(self, path: str) -> Text:
        return Text("●", style=ACCENT) if path in self.checked else Text("○", style=MUTED)

    def _update_meta(self) -> None:
        total = sum(orphan.size for orphan in self.orphans)
        text = Text()
        text.append(util.human_size(total), style=f"bold {ACCENT}")
        text.append(f"  ·  {len(self.orphans)} candidates", style=DIM)
        text.append(f"  ·  {len(self.checked)} selected", style=MUTED)
        self.query_one("#leftovers-meta", Static).update(text)

    def _update_detail(self) -> None:
        table = self.query_one(DataTable)
        index = table.cursor_row
        detail = self.query_one("#leftovers-detail", Static)
        if not (0 <= index < len(self.orphans)):
            detail.update("")
            return
        orphan = self.orphans[index]
        text = Text()
        text.append(orphan.path, style=TEXT)
        text.append(f"   {orphan.reason}", style=MUTED)
        detail.update(text)

    # -- selection -------------------------------------------------------
    def _toggle(self, path: str) -> None:
        if path in self.checked:
            self.checked.discard(path)
        else:
            self.checked.add(path)
        self.query_one(DataTable).update_cell(path, self._cols[0], self._marker(path))
        self._update_meta()

    def toggle_cursor(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self.orphans):
            self._toggle(self.orphans[table.cursor_row].path)

    def select_all(self) -> None:
        self.checked = {o.path for o in self.orphans if o.confidence == "orphan"}
        self._refresh_table()

    def select_none(self) -> None:
        self.checked.clear()
        self._refresh_table()

    def open_item(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self.orphans):
            util.open_in_explorer(self.orphans[table.cursor_row].path)

    # -- events ----------------------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self._toggle(event.row_key.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "leftovers-scan":
            self.start_scan()
        elif button == "leftovers-select":
            self.select_all()
        elif button == "leftovers-clear":
            self.select_none()
        elif button == "leftovers-remove":
            self.primary_action()

    # -- removal ---------------------------------------------------------
    def primary_action(self) -> None:
        if self._busy:
            self.app.notify("Wait for the scan to finish.", severity="warning")
            return
        chosen = [o for o in self.orphans if o.path in self.checked]
        if not chosen:
            self.app.notify("Select one or more folders to remove.", timeout=4)
            return
        total = sum(orphan.size for orphan in chosen)
        permanent = self.app.mode == "permanent"
        message = Text()
        message.append(
            f"{len(chosen)} folders, {util.human_size(total)}\n", style=TEXT
        )
        message.append(
            "Heuristics can be wrong. Check the list before confirming — "
            "the folders are moved to quarantine, not shredded.\n",
            style=WARN,
        )
        message.append(
            "Permanent delete is ON: this cannot be undone."
            if permanent
            else "You can restore them from the Quarantine pane.",
            style=BAD if permanent else GOOD,
        )
        self.confirm(
            "REMOVE LEFTOVERS",
            message,
            self._do_remove,
            confirm_label="Remove",
            danger=True,
            require_text="remove" if (total > 500 * 1024 * 1024 or permanent) else None,
        )

    def _do_remove(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        chosen = [o for o in self.orphans if o.path in self.checked]
        if not chosen:
            return
        self._busy = True
        self.query_one("#leftovers-progress", ProgressBar).display = True
        self.query_one("#leftovers-progress", ProgressBar).update(
            total=max(1, len(chosen)), progress=0
        )
        self._remove_worker(chosen)

    @work(thread=True, exclusive=True, group="leftovers-remove")
    def _remove_worker(self, chosen: list[leftovers.Orphan]) -> None:
        deleter = safety.Deleter(mode=self.app.mode, note="leftovers")
        for index, orphan in enumerate(chosen, start=1):
            if self._cancel.is_set():
                break
            deleter.delete(
                orphan.path,
                allowed_roots=[orphan.path],
                category="leftovers",
                cancel=self._cancel,
            )
            self.app.call_from_thread(self._remove_progress, index, len(chosen))
        stats = deleter.finish()
        try:
            self.app.call_from_thread(self._remove_done, stats, deleter.batch_id)
        except Exception:  # noqa: BLE001
            pass

    def _remove_progress(self, done: int, total: int) -> None:
        self.query_one("#leftovers-progress", ProgressBar).update(
            progress=done, total=total
        )

    def _remove_done(self, stats: safety.BatchStats, batch_id: str) -> None:
        self._busy = False
        self.checked.clear()
        self.query_one("#leftovers-progress", ProgressBar).display = False
        self.app.notify(
            f"Removed {util.human_size(stats.bytes)} — {stats.moved} quarantined, "
            f"{stats.failed} locked or skipped.",
            title="Leftovers",
            severity="warning" if stats.failed else "information",
            timeout=8,
        )
        self.start_scan()
