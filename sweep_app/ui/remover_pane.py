"""Program remover pane: search by name, remove every trace."""
from __future__ import annotations

import threading

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, ProgressBar, Static

from .. import appfiles, procs, safety, util
from .common import ACCENT, BAD, DIM, GOOD, MUTED, TEXT, WARN, ConfirmableMixin, PaneHeader

KIND_COLORS = {
    "folder": "#7dd3fc",
    "file": "#a78bfa",
    "registry": "#fbbf24",
    "service": "#fb7185",
}


class RemoverPane(ConfirmableMixin, Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.hits: list[appfiles.Hit] = []
        self.checked: set[int] = set()
        self._query = ""
        self._cancel = threading.Event()
        self._busy = False
        self._cols = []
        self.include_registry = False
        self.include_services = False

    def compose(self) -> ComposeResult:
        yield PaneHeader(
            "PROGRAM REMOVER",
            "Type a program name. Sweep searches every fixed drive — hidden and system files too.",
            "remover-meta",
        )
        with Horizontal(id="remover-search", classes="actions"):
            yield Input(
                placeholder="program name — e.g. Lightworks, Acme Toolbar, OBS Studio",
                id="remover-input",
            )
            yield Button("Search", id="remover-search-btn", variant="primary")
            yield Button("Kill matching", id="remover-kill")
        with Horizontal(id="remover-options", classes="actions"):
            yield Button("registry: OFF", id="remover-registry", classes="toggle")
            yield Button("services: OFF", id="remover-services", classes="toggle")
            yield Static("", id="remover-status", classes="progress-label")
            yield Button("Select all", id="remover-select")
            yield Button("Clear", id="remover-clear")
            yield Button("Remove selected", id="remover-remove", variant="error")
        yield ProgressBar(total=100, show_eta=False, id="remover-progress")
        yield DataTable(id="remover-table", cursor_type="row", zebra_stripes=True)
        yield Static(
            "Type a program name and press Enter.\n\n"
            "Sweep looks for folders, files, registry keys and services\n"
            "on every fixed drive — including hidden and system paths.\n"
            "Nothing is deleted until you pick it.",
            id="remover-empty",
            classes="empty-state",
        )
        yield Static("", id="remover-detail", classes="detail")

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        self._cols = table.add_columns("", "KIND", "NAME", "SIZE", "PATH")
        self.query_one("#remover-progress", ProgressBar).display = False
        self.query_one("#remover-table", DataTable).display = False

    def focus_table(self) -> None:
        self.query_one(DataTable).focus()

    def on_show(self) -> None:
        self.query_one("#remover-input", Input).focus()

    def rescan(self) -> None:
        self.start_search()

    # -- search ----------------------------------------------------------
    @on(Input.Submitted, "#remover-input")
    def _submitted(self, _event: Input.Submitted) -> None:
        self.start_search()

    def start_search(self) -> None:
        query = self.query_one("#remover-input", Input).value.strip()
        if len(query) < 2:
            self.app.notify("Type at least two characters.", severity="warning")
            return
        if self._busy:
            self._cancel.set()
            return
        self._query = query
        self._busy = True
        self._cancel = threading.Event()
        self.query_one("#remover-progress", ProgressBar).display = True
        self.query_one("#remover-progress", ProgressBar).update(total=100, progress=0)
        self.query_one("#remover-status", Static).update(
            Text("searching drives…", style=ACCENT)
        )
        self.query_one("#remover-search-btn", Button).disabled = True
        self._search_worker(query, self.include_registry, self.include_services, self._cancel)

    @work(thread=True, exclusive=True, group="remover-search")
    def _search_worker(
        self,
        query: str,
        include_registry: bool,
        include_services: bool,
        cancel: threading.Event,
    ) -> None:
        hits: list[appfiles.Hit] = []
        outcome = appfiles.SearchOutcome()
        try:
            outcome = appfiles.search_files(
                query,
                cancel,
                progress=lambda message, fraction: self.app.call_from_thread(
                    self._search_progress, message, fraction
                ),
            )
            hits.extend(outcome.hits)
            if include_registry and not cancel.is_set():
                hits.extend(appfiles.registry_hits(query))
            if include_services and not cancel.is_set():
                hits.extend(appfiles.service_hits(query))
        except Exception as exc:  # noqa: BLE001
            safety.log_event("search-crash", str(exc), ok=False)
        try:
            self.app.call_from_thread(self._search_done, hits, outcome, query)
        except Exception:  # noqa: BLE001
            pass

    def _search_progress(self, message: str, fraction: float) -> None:
        self.query_one("#remover-status", Static).update(
            Text(util.middle_truncate(message, 70), style=DIM)
        )
        self.query_one("#remover-progress", ProgressBar).update(
            progress=max(0.0, min(100.0, fraction * 100))
        )

    def _search_done(
        self, hits: list[appfiles.Hit], outcome: appfiles.SearchOutcome, query: str
    ) -> None:
        self._busy = False
        self.hits = hits
        self.checked.clear()
        self.query_one("#remover-progress", ProgressBar).display = False
        self.query_one("#remover-search-btn", Button).disabled = False
        self.query_one("#remover-status", Static).update(
            Text(
                f"{len(hits)} hits · {outcome.scanned:,} folders in {outcome.elapsed:.1f}s",
                style=DIM,
            )
        )
        self._refresh_table()
        if not hits:
            self.app.notify(
                f"Nothing on this PC matches “{query}”.", title="No matches", timeout=5
            )

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        table.display = bool(self.hits)
        empty = self.query_one("#remover-empty", Static)
        empty.display = not self.hits
        if not self.hits and self._query:
            empty.update(
                f"Nothing matches “{self._query}”.\n\n"
                "Try a shorter name, or switch on registry and services."
            )
        for index, hit in enumerate(self.hits):
            table.add_row(
                self._marker(index),
                Text(hit.kind_label, style=f"bold {KIND_COLORS.get(hit.kind, DIM)}"),
                Text(hit.name, style=TEXT),
                util.human_size(hit.size) if hit.size else "—",
                Text(util.middle_truncate(hit.path, 78), style=MUTED),
                key=str(index),
            )
        self._update_meta()
        self._update_detail()

    def _marker(self, index: int) -> Text:
        return Text("●", style=ACCENT) if index in self.checked else Text("○", style=MUTED)

    def _update_meta(self) -> None:
        size = sum(self.hits[i].size for i in self.checked)
        text = Text()
        text.append(f"{len(self.checked)} selected", style=f"bold {ACCENT}")
        text.append(f"  ·  {util.human_size(size)}", style=DIM)
        text.append(f"  ·  {len(self.hits)} hits", style=MUTED)
        self.query_one("#remover-meta", Static).update(text)

    def _update_detail(self) -> None:
        table = self.query_one(DataTable)
        index = table.cursor_row
        detail = self.query_one("#remover-detail", Static)
        if not (0 <= index < len(self.hits)):
            detail.update("")
            return
        hit = self.hits[index]
        text = Text()
        text.append(hit.path, style=TEXT)
        if hit.extra:
            text.append(f"   {hit.extra}", style=MUTED)
        detail.update(text)

    # -- selection -------------------------------------------------------
    def _toggle(self, index: int) -> None:
        if index in self.checked:
            self.checked.discard(index)
        else:
            self.checked.add(index)
        self.query_one(DataTable).update_cell(str(index), self._cols[0], self._marker(index))
        self._update_meta()

    def toggle_cursor(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self.hits):
            self._toggle(table.cursor_row)

    def select_all(self) -> None:
        self.checked = set(range(len(self.hits)))
        self._refresh_table()

    def select_none(self) -> None:
        self.checked.clear()
        self._refresh_table()

    def open_item(self) -> None:
        table = self.query_one(DataTable)
        if 0 <= table.cursor_row < len(self.hits):
            util.open_in_explorer(self.hits[table.cursor_row].path)

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
        if button == "remover-search-btn":
            self.start_search()
        elif button == "remover-select":
            self.select_all()
        elif button == "remover-clear":
            self.select_none()
        elif button == "remover-remove":
            self.primary_action()
        elif button == "remover-kill":
            self.kill_matching()
        elif button == "remover-registry":
            self.include_registry = not self.include_registry
            self._sync_toggles()
        elif button == "remover-services":
            self.include_services = not self.include_services
            self._sync_toggles()

    def _sync_toggles(self) -> None:
        for ident, enabled, label in (
            ("#remover-registry", self.include_registry, "registry"),
            ("#remover-services", self.include_services, "services"),
        ):
            button = self.query_one(ident, Button)
            button.label = f"{label}: {'ON' if enabled else 'OFF'}"
            button.variant = "success" if enabled else "default"

    # -- actions ---------------------------------------------------------
    def primary_action(self) -> None:
        if self._busy:
            self.app.notify("Wait for the search to finish.", severity="warning")
            return
        chosen = [self.hits[i] for i in sorted(self.checked) if i < len(self.hits)]
        if not chosen:
            self.app.notify("Select something to remove.", timeout=4)
            return
        size = sum(hit.size for hit in chosen)
        permanent = self.app.mode == "permanent"
        registry = [h for h in chosen if h.kind == "registry"]
        services = [h for h in chosen if h.kind == "service"]
        message = Text()
        message.append(f"{len(chosen)} items, {util.human_size(size)}\n", style=TEXT)
        if registry:
            message.append(
                f"{len(registry)} registry keys (exported to quarantine first)\n", style=WARN
            )
        if services:
            message.append(f"{len(services)} services will be stopped and deleted\n", style=WARN)
        message.append(
            "Permanent delete is ON — this cannot be undone."
            if permanent
            else "Files are quarantined; registry keys are backed up as .reg.",
            style=BAD if permanent else GOOD,
        )
        require = self._query if (size > 1024**3 or registry or services or permanent) else None
        self.confirm(
            f"REMOVE “{self._query.upper()}”",
            message,
            self._do_remove,
            confirm_label="Remove",
            danger=True,
            require_text=require,
        )

    def _do_remove(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        indices = sorted(self.checked)
        chosen = [self.hits[i] for i in indices if i < len(self.hits)]
        if not chosen:
            return
        self._busy = True
        self.query_one("#remover-progress", ProgressBar).display = True
        self.query_one("#remover-progress", ProgressBar).update(
            total=max(1, len(chosen)), progress=0
        )
        self._remove_worker(chosen, indices)

    @work(thread=True, exclusive=True, group="remover-remove")
    def _remove_worker(self, chosen: list[appfiles.Hit], indices: list[int]) -> None:
        report = appfiles.remove_hits(
            chosen,
            mode=self.app.mode,
            cancel=self._cancel,
            progress=lambda done, total, name: self.app.call_from_thread(
                self._remove_progress, done, total
            ),
        )
        try:
            self.app.call_from_thread(self._remove_done, report, indices)
        except Exception:  # noqa: BLE001
            pass

    def _remove_progress(self, done: int, total: int) -> None:
        self.query_one("#remover-progress", ProgressBar).update(progress=done, total=total)

    def _remove_done(self, report: appfiles.RemovalReport, indices: list[int]) -> None:
        self._busy = False
        self.query_one("#remover-progress", ProgressBar).display = False
        removed = set(indices)
        self.hits = [hit for i, hit in enumerate(self.hits) if i not in removed]
        self.checked.clear()
        self._refresh_table()
        pieces = [f"{util.human_size(report.bytes)} freed"]
        if report.moved:
            pieces.append(f"{report.moved} quarantined")
        if report.deleted:
            pieces.append(f"{report.deleted} deleted")
        if report.registry:
            pieces.append(f"{report.registry} registry keys")
        if report.services:
            pieces.append(f"{report.services} services")
        if report.failed:
            pieces.append(f"{report.failed} failed")
        self.app.notify(
            " · ".join(pieces),
            title="Program removal",
            severity="warning" if report.failed else "information",
            timeout=10,
        )
        if report.errors:
            safety.log_event("remover-problems", " | ".join(report.errors[:5]), ok=False)

    def kill_matching(self) -> None:
        query = self.query_one("#remover-input", Input).value.strip()
        if len(query) < 2:
            self.app.notify("Search for a program name first.", severity="warning")
            return
        matches = appfiles.matching_processes(query)
        if not matches:
            self.app.notify("No matching processes are running.", timeout=4)
            return
        ram = sum(info.rss for info in matches)
        message = Text()
        message.append(f"{len(matches)} processes, {util.human_size(ram)}\n", style=TEXT)
        message.append(
            ", ".join(info.name for info in matches[:8])
            + ("…" if len(matches) > 8 else ""),
            style=DIM,
        )
        self.confirm(
            "TERMINATE MATCHING PROCESSES",
            message,
            lambda ok: self._kill_matches(ok, matches),
            confirm_label="Terminate",
            danger=True,
        )

    def _kill_matches(self, confirmed: bool | None, matches: list[procs.ProcessInfo]) -> None:
        if not confirmed:
            return
        self._busy = True
        self.query_one("#remover-progress", ProgressBar).display = True
        self.query_one("#remover-progress", ProgressBar).update(
            total=max(1, len(matches)), progress=0
        )
        self._kill_worker(matches)

    @work(thread=True, exclusive=True, group="remover-kill")
    def _kill_worker(self, matches: list[procs.ProcessInfo]) -> None:
        results = procs.kill_processes(
            matches,
            progress=lambda done, total, name: self.app.call_from_thread(
                self._remove_progress, done, total
            ),
        )
        try:
            self.app.call_from_thread(self._kill_done, results)
        except Exception:  # noqa: BLE001
            pass

    def _kill_done(self, results: list[procs.KillResult]) -> None:
        self._busy = False
        self.query_one("#remover-progress", ProgressBar).display = False
        ok = sum(1 for result in results if result.ok)
        self.app.notify(
            f"Terminated {ok} of {len(results)} processes.",
            title="Processes",
            timeout=6,
        )
