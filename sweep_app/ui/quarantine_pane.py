"""Quarantine pane: everything removed is restorable."""
from __future__ import annotations


from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, ProgressBar, Static

from .. import paths, safety, util
from .common import ACCENT, BAD, DIM, MUTED, TEXT, ConfirmableMixin, PaneHeader


class QuarantinePane(ConfirmableMixin, Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.batches: list[dict] = []
        self.checked: set[str] = set()
        self._busy = False
        self._cols = []

    def compose(self) -> ComposeResult:
        yield PaneHeader(
            "QUARANTINE",
            "Removed files wait here, on the same drive they came from. Restore or purge them.",
            "quarantine-meta",
        )
        with Horizontal(id="quarantine-actions", classes="actions"):
            yield Button("Refresh", id="quarantine-refresh", variant="primary")
            yield Button("Restore selected", id="quarantine-restore")
            yield Button("Purge selected", id="quarantine-purge", variant="error")
            yield Button("Empty all", id="quarantine-empty", variant="error")
            yield Button("Open folder", id="quarantine-open")
            yield Static("", id="quarantine-status", classes="progress-label")
        yield ProgressBar(total=100, show_eta=False, id="quarantine-progress")
        yield DataTable(id="quarantine-table", cursor_type="row", zebra_stripes=True)
        yield Static(
            "Quarantine is empty.\n\n"
            "Anything Sweep removes lands here first, on the same drive\n"
            "it came from. Restore it, or purge it when you are sure.",
            id="quarantine-empty",
            classes="empty-state",
        )
        yield Static("", id="quarantine-detail", classes="detail")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._cols = table.add_columns("", "BATCH", "CREATED", "ITEMS", "SIZE", "NOTE")
        self.query_one("#quarantine-progress", ProgressBar).display = False
        self.refresh_batches()

    def focus_table(self) -> None:
        self.query_one(DataTable).focus()

    def on_show(self) -> None:
        self.refresh_batches()

    def rescan(self) -> None:
        self.refresh_batches()

    # -- data ------------------------------------------------------------
    def refresh_batches(self) -> None:
        self.batches = safety.quarantine_batches()
        self.checked &= {batch.get("id", "") for batch in self.batches}
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        table.display = bool(self.batches)
        self.query_one("#quarantine-empty", Static).display = not self.batches
        for batch in self.batches:
            items = batch.get("items", [])
            size = sum(int(item.get("size") or 0) for item in items)
            created = str(batch.get("created", ""))[:19].replace("T", " ")
            table.add_row(
                self._marker(batch.get("id", "")),
                Text(batch.get("id", "?"), style=TEXT),
                created or "—",
                f"{len(items):,}",
                util.human_size(size),
                Text(batch.get("note", "") or "—", style=DIM),
                key=batch.get("id", ""),
            )
        self._update_meta()
        self._update_detail()

    def _marker(self, batch_id: str) -> Text:
        return Text("●", style=ACCENT) if batch_id in self.checked else Text("○", style=MUTED)

    def _update_meta(self) -> None:
        total, items = safety.quarantine_usage()
        text = Text()
        text.append(util.human_size(total), style=f"bold {ACCENT}")
        text.append(f"  ·  {items:,} items", style=DIM)
        text.append(f"  ·  {len(self.batches)} batches", style=MUTED)
        self.query_one("#quarantine-meta", Static).update(text)

    def _update_detail(self) -> None:
        table = self.query_one(DataTable)
        index = table.cursor_row
        detail = self.query_one("#quarantine-detail", Static)
        if not (0 <= index < len(self.batches)):
            detail.update("")
            return
        batch = self.batches[index]
        text = Text()
        text.append(batch.get("dir", ""), style=TEXT)
        text.append(f"   {batch.get('mode', 'quarantine')}", style=MUTED)
        detail.update(text)

    # -- selection -------------------------------------------------------
    def _toggle(self, batch_id: str) -> None:
        if batch_id in self.checked:
            self.checked.discard(batch_id)
        else:
            self.checked.add(batch_id)
        self.query_one(DataTable).update_cell(batch_id, self._cols[0], self._marker(batch_id))
        self._update_meta()

    def toggle_cursor(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self.batches):
            self._toggle(self.batches[table.cursor_row].get("id", ""))

    def select_all(self) -> None:
        self.checked = {batch.get("id", "") for batch in self.batches}
        self._refresh_table()

    def select_none(self) -> None:
        self.checked.clear()
        self._refresh_table()

    def open_item(self) -> None:
        util.open_in_explorer(paths.QUARANTINE)

    # -- events ----------------------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self._toggle(event.row_key.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_detail()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "quarantine-refresh":
            self.refresh_batches()
        elif button == "quarantine-restore":
            self.primary_action()
        elif button == "quarantine-purge":
            self.purge_selected()
        elif button == "quarantine-empty":
            self.empty_all()
        elif button == "quarantine-open":
            util.open_in_explorer(paths.QUARANTINE)

    # -- actions ---------------------------------------------------------
    def primary_action(self) -> None:
        ids = sorted(self.checked)
        if not ids:
            self.app.notify("Select a batch to restore.", timeout=4)
            return
        total = sum(
            int(item.get("size") or 0)
            for batch in self.batches
            if batch.get("id") in self.checked
            for item in batch.get("items", [])
        )
        self.confirm(
            "RESTORE FROM QUARANTINE",
            f"Put {len(ids)} batch(es), {util.human_size(total)}, back where they came from?",
            self._do_restore,
            confirm_label="Restore",
            danger=False,
        )

    def _do_restore(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        ids = sorted(self.checked)
        if not ids:
            return
        self._busy = True
        self.query_one("#quarantine-progress", ProgressBar).display = True
        self.query_one("#quarantine-progress", ProgressBar).update(total=100, progress=0)
        self.query_one("#quarantine-status", Static).update(Text("restoring…", style=ACCENT))
        self._restore_worker(ids)

    @work(thread=True, exclusive=True, group="quarantine-restore")
    def _restore_worker(self, ids: list[str]) -> None:
        restored = failed = 0
        for batch_id in ids:
            done, bad = safety.restore_batch(
                batch_id,
                progress=lambda index, total, src: self.app.call_from_thread(
                    self._restore_progress, index, total
                ),
            )
            restored += done
            failed += bad
        try:
            self.app.call_from_thread(self._restore_done, restored, failed)
        except Exception:  # noqa: BLE001
            pass

    def _restore_progress(self, done: int, total: int) -> None:
        self.query_one("#quarantine-progress", ProgressBar).update(
            progress=(done / total * 100) if total else 100
        )

    def _restore_done(self, restored: int, failed: int) -> None:
        self._busy = False
        self.checked.clear()
        self.query_one("#quarantine-progress", ProgressBar).display = False
        self.query_one("#quarantine-status", Static).update("")
        self.app.notify(
            f"Restored {restored} items" + (f", {failed} could not be restored." if failed else "."),
            title="Quarantine",
            severity="warning" if failed else "information",
            timeout=8,
        )
        self.refresh_batches()

    def purge_selected(self) -> None:
        ids = sorted(self.checked)
        if not ids:
            self.app.notify("Select a batch to purge.", timeout=4)
            return
        self.confirm(
            "PURGE QUARANTINE",
            f"Permanently delete {len(ids)} batch(es)? They cannot be restored afterwards.",
            self._do_purge,
            confirm_label="Purge",
            danger=True,
            require_text="purge",
        )

    def _do_purge(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        ids = sorted(self.checked)
        self._busy = True
        self.query_one("#quarantine-status", Static).update(Text("purging…", style=BAD))
        self.query_one("#quarantine-progress", ProgressBar).display = True
        self.query_one("#quarantine-progress", ProgressBar).update(total=max(1, len(ids)), progress=0)
        self._purge_worker(ids)

    @work(thread=True, exclusive=True, group="quarantine-purge")
    def _purge_worker(self, ids: list[str]) -> None:
        ok = bad = 0
        for index, batch_id in enumerate(ids, start=1):
            if safety.purge_batch(batch_id):
                ok += 1
            else:
                bad += 1
            self.app.call_from_thread(self._purge_progress, index, len(ids))
        try:
            self.app.call_from_thread(self._purge_done, ok, bad)
        except Exception:  # noqa: BLE001
            pass

    def _purge_progress(self, done: int, total: int) -> None:
        self.query_one("#quarantine-progress", ProgressBar).update(progress=done, total=total)

    def _purge_done(self, ok: int, bad: int) -> None:
        self._busy = False
        self.checked.clear()
        self.query_one("#quarantine-progress", ProgressBar).display = False
        self.query_one("#quarantine-status", Static).update("")
        self.app.notify(
            f"Purged {ok} batches" + (f", {bad} failed." if bad else "."),
            title="Quarantine",
            severity="warning" if bad else "information",
            timeout=6,
        )
        self.refresh_batches()

    def empty_all(self) -> None:
        if not self.batches:
            self.app.notify("Quarantine is already empty.", timeout=3)
            return
        total, items = safety.quarantine_usage()
        self.confirm(
            "EMPTY QUARANTINE",
            f"Permanently delete {len(self.batches)} batches, {util.human_size(total)} "
            f"({items:,} items)?",
            self._do_empty,
            confirm_label="Empty all",
            danger=True,
            require_text="empty",
        )

    def _do_empty(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self._busy = True
        self.query_one("#quarantine-status", Static).update(Text("purging…", style=BAD))
        self.query_one("#quarantine-progress", ProgressBar).display = True
        self.query_one("#quarantine-progress", ProgressBar).update(total=1, progress=0)
        self._empty_worker()

    @work(thread=True, exclusive=True, group="quarantine-empty")
    def _empty_worker(self) -> None:
        ok, bad = safety.purge_all()
        try:
            self.app.call_from_thread(self._purge_done, ok, bad)
        except Exception:  # noqa: BLE001
            pass
