"""AllModsScreen: a real explorer for every mod you have data on.

Search, filter by workspace/status, sort, and browse a results table with a
live preview pane -- arrowing to a row shows its thumbnail (local
preview.webp if fetched, otherwise a cached/lazily-fetched GameBanana
screenshot) and key metadata without opening the full detail modal.

Thumbnails are NOT loaded for every row up front -- that would mean a
network fetch per visible row for anything not already cached, which doesn't
scale to a few hundred mods and would make scrolling feel awful. Instead
only the currently-highlighted row's image is resolved, debounced so
scrolling quickly past several rows doesn't fire a fetch for each one only
to immediately discard it.
"""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static

from .mod_detail import ModDetailModal

_STATUS_OPTIONS = [("All", "all"), ("Fetched", "fetched"), ("Pending (not fetched)", "pending")]
_SORT_OPTIONS = [("Name (A-Z)", "name"), ("Name (Z-A)", "name-desc"), ("Workspace", "workspace")]
_THUMBNAIL_DELAY = 0.3  # seconds of no further navigation before fetching a preview image


class AllModsScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back"), ("/", "focus_search", "Search")]

    def __init__(self) -> None:
        super().__init__()
        self._records: list[dict] = []
        self._filtered: list[dict] = []
        self._thumbnail_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="explorer-main"):
            with Vertical(id="explorer-list-pane"):
                with Horizontal(id="explorer-filters"):
                    yield Input(placeholder="Search...", id="explorer-search")
                    yield Select([], prompt="Workspace", id="explorer-workspace-filter")
                    yield Select(_STATUS_OPTIONS, value="all", prompt="Status", id="explorer-status-filter")
                    yield Select(_SORT_OPTIONS, value="name", prompt="Sort", id="explorer-sort")
                yield Static(id="explorer-summary")
                yield DataTable(id="explorer-table", cursor_type="row", zebra_stripes=True)
            with Vertical(id="explorer-preview-pane"):
                yield Container(id="explorer-preview-image")
                yield Static(id="explorer-preview-text")
                yield Button("Open full detail", id="explorer-open-btn", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        import common  # scripts/common.py

        self._records = common.all_known_mods()
        for record in self._records:
            record["category"] = ""
            if record["fetched"]:
                info = common.mod_info(record["path"])
                record["category"] = info.get("category") or ""

        table = self.query_one("#explorer-table", DataTable)
        table.add_columns("Name", "Workspace", "Status", "Category")

        workspaces = sorted({r["workspace"] for r in self._records if r["workspace"]})
        self.query_one("#explorer-workspace-filter", Select).set_options(
            [("All workspaces", "all")] + [(w, w) for w in workspaces]
        )
        self.query_one("#explorer-workspace-filter", Select).value = "all"

        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.query_one("#explorer-search", Input).value.strip().lower()
        workspace_filter = self.query_one("#explorer-workspace-filter", Select).value
        status_filter = self.query_one("#explorer-status-filter", Select).value
        sort_key = self.query_one("#explorer-sort", Select).value

        rows = self._records
        if query:
            rows = [
                r for r in rows
                if query in r["name"].lower() or query in (r["workspace"] or "").lower() or query in r["category"].lower()
            ]
        if workspace_filter and workspace_filter != "all" and workspace_filter is not Select.NULL:
            rows = [r for r in rows if r["workspace"] == workspace_filter]
        if status_filter == "fetched":
            rows = [r for r in rows if r["fetched"]]
        elif status_filter == "pending":
            rows = [r for r in rows if not r["fetched"]]

        if sort_key == "name-desc":
            rows = sorted(rows, key=lambda r: r["name"].lower(), reverse=True)
        elif sort_key == "workspace":
            rows = sorted(rows, key=lambda r: (r["workspace"] or "", r["name"].lower()))
        else:
            rows = sorted(rows, key=lambda r: r["name"].lower())

        self._filtered = rows
        self._render_table()

    @staticmethod
    def _row_key(record: dict) -> str:
        # Mods can legitimately share a name across different workspaces
        # (e.g. reskin/Skin-Marth vs nsfw/Skin-Marth, by design -- see
        # common.all_known_mods()), so the name alone isn't a unique row key.
        return f"{record['workspace']}::{record['name']}"

    def _render_table(self) -> None:
        table = self.query_one("#explorer-table", DataTable)
        table.clear()
        for record in self._filtered:
            status = "fetched" if record["fetched"] else "[yellow]pending[/yellow]"
            table.add_row(
                record["name"], record["workspace"] or "-", status, record["category"] or "-",
                key=self._row_key(record),
            )
        self.query_one("#explorer-summary", Static).update(f"{len(self._filtered)} of {len(self._records)} mods")
        if self._filtered:
            table.move_cursor(row=0)
            self._schedule_preview(self._filtered[0])
        else:
            self._clear_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "explorer-search":
            self._apply_filters()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("explorer-workspace-filter", "explorer-status-filter", "explorer-sort"):
            self._apply_filters()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value is None:
            return
        record = next((r for r in self._filtered if self._row_key(r) == event.row_key.value), None)
        if record is not None:
            self._schedule_preview(record)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_detail()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "explorer-open-btn":
            self._open_detail()

    def _open_detail(self) -> None:
        table = self.query_one("#explorer-table", DataTable)
        if table.cursor_row is None or not self._filtered:
            return
        record = self._filtered[table.cursor_row]
        self.app.push_screen(ModDetailModal(record=record), callback=self._on_detail_closed)

    def _on_detail_closed(self, moved: bool | None) -> None:
        if moved:
            self.on_mount()  # cheap enough (no network) to just rebuild from scratch

    def _schedule_preview(self, record: dict) -> None:
        if self._thumbnail_timer is not None:
            self._thumbnail_timer.stop()
        self._render_preview_text(record)
        self.query_one("#explorer-open-btn", Button).disabled = False
        self._thumbnail_timer = self.set_timer(_THUMBNAIL_DELAY, lambda: self._load_preview_image(record))

    def _render_preview_text(self, record: dict) -> None:
        import common  # scripts/common.py

        lines = [f"[bold]{record['name']}[/bold]", ""]
        lines.append(f"Workspace: {record['workspace'] or '(unknown)'}")
        lines.append(f"Status: {'fetched' if record['fetched'] else '[yellow]pending -- run Build[/yellow]'}")
        if record["category"]:
            lines.append(f"Category: {record['category']}")
        profile_names = common.profiles_including_workspace(record["workspace"]) if record["workspace"] else []
        lines.append("")
        if profile_names:
            lines.append(f"In profiles: {', '.join(profile_names)}")
        else:
            lines.append("[dim]Not part of any current profile[/dim]")
        self.query_one("#explorer-preview-text", Static).update("\n".join(lines))

    def _clear_preview(self) -> None:
        self.query_one("#explorer-preview-text", Static).update("[dim]No mods match the current filters.[/dim]")
        self.query_one("#explorer-preview-image", Container).remove_children()
        self.query_one("#explorer-preview-image", Container).display = False
        self.query_one("#explorer-open-btn", Button).disabled = True

    @work(thread=True, exclusive=True)
    def _load_preview_image(self, record: dict) -> None:
        image_path = None
        if record["fetched"]:
            preview = next(record["path"].glob("[Pp]review.webp"), None)
            if preview is not None:
                image_path = preview
        if image_path is None and record.get("gamebanana_id"):
            import gamebanana  # scripts/gamebanana.py

            profile = gamebanana.fetch_profile(record["gamebanana_id"])
            if profile is not None:
                urls = gamebanana.screenshot_urls(profile)
                if urls:
                    image_path = gamebanana.fetch_image_bytes(urls[0], cache_key=f"{record['gamebanana_id']}_0.jpg")
        self.app.call_from_thread(self._on_preview_image_ready, self._row_key(record), image_path)

    def _on_preview_image_ready(self, row_key: str, image_path: Path | None) -> None:
        if not self.is_attached:
            return
        table = self.query_one("#explorer-table", DataTable)
        current = self._filtered[table.cursor_row] if self._filtered and table.cursor_row is not None else None
        if current is None or self._row_key(current) != row_key:
            return  # user has already moved on to a different row
        container = self.query_one("#explorer-preview-image", Container)
        container.remove_children()
        if image_path is None:
            container.display = False
            return
        from textual_image.widget import Image

        try:
            container.mount(Image(str(image_path)))
            container.display = True
        except Exception:
            container.display = False

    def action_focus_search(self) -> None:
        self.query_one("#explorer-search", Input).focus()
