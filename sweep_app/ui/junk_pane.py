"""Junk files pane."""
from __future__ import annotations

import threading

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, ProgressBar, Static

from .. import admin, junk, safety, util
from .common import ACCENT, BAD, DIM, GOOD, MUTED, TEXT, WARN, ConfirmableMixin, PaneHeader, risk_text


class JunkPane(ConfirmableMixin, Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.results: dict[str, junk.CategoryScan] = {}
        self.selected: set[str] = {c.key for c in junk.CATEGORIES if c.default}
        self._rows: list[str] = [c.key for c in junk.CATEGORIES]
        self._cancel = threading.Event()
        self._scanning = False
        self._cleaning = False
        self._loaded = False
        self._cols = []

    def compose(self) -> ComposeResult:
        yield PaneHeader(
            "JUNK FILES",
            "Pick what to clear — everything is reversible in quarantine mode.",
            "junk-meta",
        )
        with Horizontal(id="junk-actions", classes="actions"):
            yield Button("Scan", id="junk-scan", variant="primary")
            yield Button("Select safe", id="junk-safe")
            yield Button("Clear", id="junk-none")
            yield Button("Clean selected", id="junk-clean", variant="error")
            yield Static("", id="junk-progress-label", classes="progress-label")
        yield ProgressBar(total=100, show_eta=False, id="junk-progress")
        yield DataTable(id="junk-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="junk-detail", classes="detail")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._cols = table.add_columns("", "CATEGORY", "RISK", "ITEMS", "SIZE", "STATE")
        for category in junk.CATEGORIES:
            table.add_row(
                self._marker(category.key),
                category.title,
                risk_text(category.risk),
                "—",
                "—",
                Text("not scanned", style=MUTED),
                key=category.key,
            )
        self.query_one("#junk-progress", ProgressBar).display = False
        self._update_summary()

    def focus_table(self) -> None:
        self.query_one(DataTable).focus()

    # -- lifecycle -------------------------------------------------------
    def on_show(self) -> None:
        if not self._loaded:
            self.start_scan()

    def rescan(self) -> None:
        if not self._cleaning:
            self.start_scan()

    def start_scan(self) -> None:
        if self._scanning or self._cleaning:
            self._cancel.set()
            return
        self._cancel = threading.Event()
        self._scanning = True
        self._loaded = True
        self.query_one("#junk-progress", ProgressBar).display = True
        self.query_one("#junk-progress", ProgressBar).update(
            total=len(junk.CATEGORIES), progress=0
        )
        self.query_one("#junk-progress-label", Static).update(
            Text("scanning…", style=ACCENT)
        )
        self._scan_worker(self._cancel)

    @work(thread=True, exclusive=True, group="junk-scan")
    def _scan_worker(self, cancel: threading.Event) -> None:
        try:
            junk.scan_all(
                cancel=cancel,
                on_result=lambda scan: self.app.call_from_thread(self._apply_scan, scan),
            )
        finally:
            try:
                self.app.call_from_thread(self._scan_finished, cancel)
            except Exception:  # noqa: BLE001 - shutting down
                pass

    def _apply_scan(self, scan: junk.CategoryScan) -> None:
        self.results[scan.key] = scan
        table = self.query_one(DataTable)
        table.update_cell(scan.key, self._cols[3], f"{scan.items:,}", update_width=True)
        table.update_cell(
            scan.key, self._cols[4], util.human_size(scan.size), update_width=True
        )
        table.update_cell(
            scan.key, self._cols[5], self._status_text(scan), update_width=True
        )
        progress = self.query_one("#junk-progress", ProgressBar)
        progress.advance(1)
        self._update_summary()

    def _scan_finished(self, cancel: threading.Event) -> None:
        if cancel is not self._cancel:
            return
        self._scanning = False
        self.query_one("#junk-progress", ProgressBar).display = False
        self.query_one("#junk-progress-label", Static).update("")
        total = sum(scan.size for scan in self.results.values())
        files = sum(scan.files for scan in self.results.values())
        state = self.app.state
        state.junk_size, state.junk_files, state.junk_scanned = total, files, True
        self._update_summary()

    @staticmethod
    def _status_text(scan: junk.CategoryScan) -> Text:
        if scan.status == "needs-admin":
            return Text("needs admin", style=WARN)
        if scan.status == "error":
            return Text("error", style=BAD)
        if scan.status == "empty":
            return Text("empty", style=MUTED)
        if scan.files:
            return Text(f"{scan.files:,} files", style=DIM)
        return Text("ready", style=GOOD)

    def _marker(self, key: str) -> Text:
        if key in self.selected:
            return Text("●", style=ACCENT)
        return Text("○", style=MUTED)

    # -- selection -------------------------------------------------------
    def _refresh_marker(self, key: str) -> None:
        self.query_one(DataTable).update_cell(key, self._cols[0], self._marker(key))
        self._update_summary()

    def _toggle(self, key: str) -> None:
        if key in self.selected:
            self.selected.discard(key)
        else:
            self.selected.add(key)
        self._refresh_marker(key)

    def toggle_cursor(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self._rows):
            self._toggle(self._rows[table.cursor_row])

    def select_all(self) -> None:
        self.selected = {c.key for c in junk.CATEGORIES}
        for key in self._rows:
            self.query_one(DataTable).update_cell(key, self._cols[0], self._marker(key))
        self._update_summary()

    def select_none(self) -> None:
        self.selected.clear()
        for key in self._rows:
            self.query_one(DataTable).update_cell(key, self._cols[0], self._marker(key))
        self._update_summary()

    def select_safe(self) -> None:
        self.selected = {c.key for c in junk.CATEGORIES if c.risk == "safe"}
        for key in self._rows:
            self.query_one(DataTable).update_cell(key, self._cols[0], self._marker(key))
        self._update_summary()

    def _update_summary(self) -> None:
        size = 0
        files = 0
        for key in self.selected:
            scan = self.results.get(key)
            if scan:
                size += scan.size
                files += scan.files
        text = Text()
        text.append(util.human_size(size), style=f"bold {ACCENT}")
        text.append(f"  ·  {files:,} files", style=DIM)
        text.append(f"  ·  {len(self.selected)} categories", style=MUTED)
        self.query_one("#junk-meta", Static).update(text)
        detail = self.query_one("#junk-detail", Static)
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self._rows):
            category = junk.CATEGORY_MAP[self._rows[table.cursor_row]]
            line = Text()
            line.append(f"{category.blurb}", style=TEXT)
            if category.note:
                line.append(f"   {category.note}", style=MUTED)
            detail.update(line)
        if self._scanning:
            self.query_one("#junk-progress-label", Static).update(
                Text("scanning…", style=ACCENT)
            )

    # -- events ----------------------------------------------------------
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self._toggle(event.row_key.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "junk-scan":
            self.start_scan()
        elif button == "junk-safe":
            self.select_safe()
        elif button == "junk-none":
            self.select_none()
        elif button == "junk-clean":
            self.primary_action()

    # -- cleaning --------------------------------------------------------
    def primary_action(self) -> None:
        if self._cleaning:
            self._cancel.set()
            return
        if self._scanning:
            self.app.notify("Wait for the scan to finish first.", severity="warning")
            return
        keys = [
            key
            for key in self.selected
            if (scan := self.results.get(key)) is not None and scan.has_content
        ]
        if not keys:
            self.app.notify("Nothing selected with anything to remove.", timeout=4)
            return
        total_size = sum(self.results[key].size for key in keys)
        total_items = sum(self.results[key].items for key in keys)
        admin_needed = [
            key
            for key in keys
            if self.results[key].status == "needs-admin" and not admin.is_admin()
        ]
        permanent = self.app.mode == "permanent"
        message = Text()
        message.append(
            f"{len(keys)} categories, {total_items:,} items, {util.human_size(total_size)}\n",
            style=TEXT,
        )
        message.append(
            "These will be permanently deleted."
            if permanent
            else "These will be moved to quarantine and can be restored later.",
            style=BAD if permanent else GOOD,
        )
        if admin_needed:
            message.append(
                f"\n{len(admin_needed)} categories need Administrator and will be skipped.",
                style=WARN,
            )
        self.confirm(
            "CLEAN JUNK" if not permanent else "PERMANENT DELETE",
            message,
            self._do_clean,
            confirm_label="Delete" if permanent else "Quarantine",
            danger=True,
            require_text="delete" if permanent else None,
        )

    def _do_clean(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        keys = [
            key
            for key in self.selected
            if (scan := self.results.get(key)) is not None and scan.has_content
        ]
        if not keys:
            return
        self._cleaning = True
        self._cancel = threading.Event()
        total_items = max(1, sum(self.results[key].items for key in keys))
        self.query_one("#junk-progress", ProgressBar).display = True
        self.query_one("#junk-progress", ProgressBar).update(
            total=total_items, progress=0
        )
        self.query_one("#junk-progress-label", Static).update(
            Text("cleaning…", style=BAD)
        )
        self._clean_worker(keys, self._cancel)

    @work(thread=True, exclusive=True, group="junk-clean")
    def _clean_worker(self, keys: list[str], cancel: threading.Event) -> None:
        mode = self.app.mode
        deleter = safety.Deleter(mode=mode, note="junk clean")
        total = max(1, sum(self.results[key].items for key in keys))
        done = 0
        try:
            for key in keys:
                if cancel.is_set():
                    break
                category = junk.CATEGORY_MAP[key]
                if category.kind == "recycle":
                    safety.empty_recycle_bin()
                    done += 1
                    continue
                roots, items = category.spec()
                for item in items:
                    if cancel.is_set():
                        break
                    deleter.delete(
                        item, allowed_roots=roots, category=key, cancel=cancel
                    )
                    done += 1
                    if done % 20 == 0:
                        self.app.call_from_thread(self._progress, done, total)
        except Exception as exc:  # noqa: BLE001 - never lose the summary
            safety.log_event("clean-crash", str(exc), ok=False)
        stats = deleter.finish()
        try:
            self.app.call_from_thread(
                self._clean_done, stats, deleter.batch_id, mode, cancel.is_set()
            )
        except Exception:  # noqa: BLE001
            pass

    def _progress(self, done: int, total: int) -> None:
        self.query_one("#junk-progress", ProgressBar).update(progress=done, total=total)

    def _clean_done(
        self,
        stats: safety.BatchStats,
        batch_id: str,
        mode: str,
        cancelled: bool,
    ) -> None:
        self._cleaning = False
        self.query_one("#junk-progress", ProgressBar).display = False
        self.query_one("#junk-progress-label", Static).update("")
        summary = (
            f"{'Stopped' if cancelled else 'Done'} — freed {util.human_size(stats.bytes)}. "
            f"{stats.moved} quarantined, {stats.failed} locked or skipped."
        )
        if mode == "permanent":
            summary = (
                f"{'Stopped' if cancelled else 'Done'} — deleted "
                f"{util.human_size(stats.bytes)}. {stats.failed} locked or skipped."
            )
        self.app.notify(
            summary,
            title="Junk cleaned",
            severity="warning" if stats.failed else "information",
            timeout=8,
        )
        if stats.failures:
            for failure in stats.failures[:20]:
                safety.log_event(
                    "clean-locked",
                    f"{failure.get('path')} :: "
                    f"{util.short_reason(failure.get('reason', ''))}",
                    ok=False,
                )
        elif stats.errors:
            safety.log_event("clean-problems", " | ".join(stats.errors[:5]), ok=False)
        self.results.clear()
        self.start_scan()
