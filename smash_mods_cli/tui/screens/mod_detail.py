"""ModDetailModal: detail view for one mod, fetched or not.

Local info (from scripts/common.py's mod_info(), i.e. info.toml) renders
immediately for a fetched mod, including its preview image inline if one
exists on disk. If the mod can be traced back to a GameBanana submission (via
its pinned gamebanana_id in roster.toml), a background fetch then fills in
the full submission description, like/view counts, and its first screenshot
-- never blocking the initial view, and failing quietly if GameBanana is
unreachable.

A mod that's been curated but not fetched yet (no directory under
workspaces/) still gets a detail view: its GameBanana info/images work the
same way (the id is already known from roster.toml), just without local
file/info.toml/preview details, and "Move to workspace" retargets its
roster.toml entry instead of physically relocating a directory that doesn't
exist yet.
"""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static

from ... import commands
from ...paths import SCRIPTS  # noqa: F401
from .live_output import LiveOutputScreen

# Screenshots to download per mod. GameBanana submissions can have a dozen+;
# capping keeps the background fetch quick and avoids hoarding disk cache for
# images the user will likely never click through to.
MAX_SCREENSHOTS = 6


class ModDetailModal(ModalScreen):
    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("left", "gb_prev", "Prev image"),
        ("right", "gb_next", "Next image"),
    ]

    def __init__(self, mod_path: Path | None = None, *, record: dict | None = None) -> None:
        """Either pass a fetched mod's directory Path (legacy/simple case),
        or a unified record from common.all_known_mods() -- the latter is
        required for a pending (not yet fetched) mod, since there's no path."""
        super().__init__()
        if record is not None:
            self._path: Path | None = record.get("path")
            self._mod_name: str = record["name"]
            self._workspace: str | None = record.get("workspace")
            self._gb_id_hint: int | None = record.get("gamebanana_id")
        else:
            assert mod_path is not None
            self._path = mod_path
            self._mod_name = mod_path.name
            self._workspace = mod_path.parent.name
            self._gb_id_hint = None
        self._fetched = self._path is not None
        self._gb_images: list[Path] = []
        self._gb_index = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-panel"):
            with VerticalScroll(id="detail-body"):
                yield Static(self._render_body(), id="detail-text")
                yield Container(id="local-image-container")
                yield Static("", id="gb-status")
                yield Static("", id="gb-text")
                yield Container(id="gb-image-container")
                with Horizontal(id="move-row"):
                    yield Select([], prompt="Move to workspace...", id="move-select")
                    yield Button("Move", id="move-btn")
                yield Static("", id="move-status")
                yield Static("[dim]esc to close[/dim]")

    def on_mount(self) -> None:
        if self._fetched:
            self._mount_local_preview()
        self._start_gamebanana_fetch()
        self._populate_move_select()

    def _populate_move_select(self) -> None:
        import common  # scripts/common.py

        options = [(name, name) for name in common.list_workspaces() if name != self._workspace]
        self.query_one("#move-select", Select).set_options(options)

    def _render_body(self) -> str:
        import common  # scripts/common.py

        if not self._fetched:
            lines = [f"[bold]{self._mod_name}[/bold]", "", "[yellow]Not fetched yet[/yellow] -- run Build to download and unpack this mod."]
            lines.append(f"Target workspace: {self._workspace or '(unknown)'}")
            profile_names = common.profiles_including_workspace(self._workspace) if self._workspace else []
            lines.append("")
            if profile_names:
                lines.append(f"Once fetched, will be part of: {', '.join(profile_names)}")
            else:
                lines.append("[dim]Its target workspace isn't used by any current profile yet.[/dim]")
            return "\n".join(lines)

        path = self._path
        info = common.mod_info(path)

        lines = [f"[bold]{info.get('display_name') or path.name}[/bold]"]
        if info.get("display_name") and info["display_name"] != path.name:
            lines.append(f"[dim]directory: {path.name}[/dim]")
        lines.append("")

        if info.get("category"):
            lines.append(f"Category: {info['category']}")
        if info.get("authors"):
            lines.append(f"Authors: {info['authors']}")
        if info.get("version"):
            lines.append(f"Version: {info['version']}")
        if info.get("description"):
            lines.append("")
            lines.append(info["description"].strip())
        if not info:
            lines.append("[dim](no info.toml for this mod)[/dim]")

        children = sorted(p.name for p in path.iterdir()) if path.is_dir() else []
        game_children = [c for c in children if c in common.GAME_PATHS]
        if game_children:
            lines.append("")
            lines.append("Contents: " + ", ".join(game_children))

        profile_names = common.profiles_including_workspace(self._workspace)
        lines.append("")
        if profile_names:
            lines.append(f"In profiles: {', '.join(profile_names)}")
        else:
            lines.append("[dim]Not part of any current profile (workspace not layered anywhere)[/dim]")

        return "\n".join(lines)

    def _mount_local_preview(self) -> None:
        preview = next(self._path.glob("[Pp]review.webp"), None)
        if preview is None:
            return
        self._show_image("local-image-container", str(preview))

    def _show_image(self, container_id: str, image_source: str) -> None:
        """Mount an image into a container that starts hidden/zero-space.
        Sizing is handled entirely by CSS (width/height: auto on both the
        container and the Image itself) so the image keeps its own aspect
        ratio instead of being stretched/cropped to a guessed box."""
        from textual_image.widget import Image

        container = self.query_one(f"#{container_id}", Container)
        try:
            container.mount(Image(image_source))
        except Exception:
            container.mount(Static(f"[dim]Image (couldn't render inline): {image_source}[/dim]"))
        container.display = True

    def _start_gamebanana_fetch(self) -> None:
        import common  # scripts/common.py
        import gamebanana  # scripts/gamebanana.py

        gb_id = self._gb_id_hint
        if gb_id is None:
            entry = common.roster_entry(self._mod_name)
            gb_id = entry.get("gamebanana_id") if entry else None
        if not gb_id:
            return
        # Cached lookups are near-instant -- only show a "fetching" message
        # when this is actually about to hit the network, so a cache hit is
        # visibly (not just theoretically) different from a live fetch.
        if not gamebanana.has_fresh_cache(gb_id):
            self.query_one("#gb-status", Static).update("[dim]Fetching GameBanana info...[/dim]")
        self._fetch_gamebanana(gb_id)

    @work(thread=True, exclusive=True)
    def _fetch_gamebanana(self, mod_id: int) -> None:
        import gamebanana  # scripts/gamebanana.py

        profile = gamebanana.fetch_profile(mod_id)
        if profile is None:
            self.app.call_from_thread(self._on_gamebanana_failed)
            return
        image_paths = []
        for i, url in enumerate(gamebanana.screenshot_urls(profile)[:MAX_SCREENSHOTS]):
            path = gamebanana.fetch_image_bytes(url, cache_key=f"{mod_id}_{i}.jpg")
            if path is not None:
                image_paths.append(path)
        self.app.call_from_thread(self._on_gamebanana_loaded, profile, image_paths)

    def _on_gamebanana_failed(self) -> None:
        if not self.is_attached:
            return  # modal was closed before the background fetch finished
        self.query_one("#gb-status", Static).update(
            "[dim]Could not reach GameBanana (offline, or the submission was removed).[/dim]"
        )

    def _on_gamebanana_loaded(self, profile: dict, image_paths: list[Path]) -> None:
        if not self.is_attached:
            return  # modal was closed before the background fetch finished
        import gamebanana  # scripts/gamebanana.py

        self.query_one("#gb-status", Static).update("")

        stats = []
        submitter = (profile.get("_aSubmitter") or {}).get("_sName")
        if submitter:
            stats.append(f"by {submitter}")
        if profile.get("_nLikeCount") is not None:
            stats.append(f"{profile['_nLikeCount']} likes")
        if profile.get("_nViewCount") is not None:
            stats.append(f"{profile['_nViewCount']} views")

        lines = []
        if stats:
            lines.append("[dim]" + "  ·  ".join(stats) + " (GameBanana)[/dim]")
        description = gamebanana.strip_html(profile.get("_sText") or profile.get("_sDescription") or "")
        if description:
            lines.append("")
            lines.append(description[:2000])
        self.query_one("#gb-text", Static).update("\n".join(lines))

        if image_paths:
            self._setup_gb_carousel(image_paths)

    def _setup_gb_carousel(self, image_paths: list[Path]) -> None:
        from textual_image.widget import Image

        self._gb_images = image_paths
        self._gb_index = 0
        container = self.query_one("#gb-image-container", Container)

        nav = Horizontal(
            Button("< Prev", id="gb-prev"),
            Static(f"1 / {len(image_paths)}", id="gb-caption"),
            Button("Next >", id="gb-next"),
            id="gb-nav",
        )
        nav.display = len(image_paths) > 1
        container.mount(nav)
        container.mount(Image(str(image_paths[0]), id="gb-image-widget"))
        container.display = True

    def _gb_show(self, index: int) -> None:
        if not self._gb_images:
            return
        self._gb_index = index % len(self._gb_images)
        from textual_image.widget import Image

        self.query_one("#gb-image-widget", Image).image = str(self._gb_images[self._gb_index])
        self.query_one("#gb-caption", Static).update(f"{self._gb_index + 1} / {len(self._gb_images)}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "gb-prev":
            self._gb_show(self._gb_index - 1)
        elif event.button.id == "gb-next":
            self._gb_show(self._gb_index + 1)
        elif event.button.id == "move-btn":
            self._do_move()

    def _do_move(self) -> None:
        select = self.query_one("#move-select", Select)
        target = select.value
        if target is Select.NULL:
            self.app.notify("Pick a workspace to move to first.", severity="warning")
            return
        mod_name = self._mod_name

        if self._fetched:
            argv = commands.move_mod_argv(mod_name, from_workspace=self._workspace, to_workspace=target)
            title = f"Move '{mod_name}': {self._workspace} -> {target}"
            fail_msg = f"Could not move -- '{mod_name}' may already exist in '{target}'."
        else:
            argv = commands.retarget_pending_mod_argv(mod_name, to_workspace=target)
            title = f"Retarget '{mod_name}': {self._workspace} -> {target}"
            fail_msg = f"Could not retarget -- '{mod_name}' not found in roster.toml."

        def on_done(code: int | None) -> None:
            if code != 0:
                self.query_one("#move-status", Static).update(f"[red]{fail_msg}[/red]")
                return
            # This mod's path/profiles/workspace choices are now all stale --
            # close rather than try to patch the open view in place, and tell
            # HomeScreen a move happened so it refreshes whatever list is showing.
            self.dismiss(True)

        self.app.push_screen(LiveOutputScreen(argv, title=title), callback=on_done)

    def action_gb_prev(self) -> None:
        self._gb_show(self._gb_index - 1)

    def action_gb_next(self) -> None:
        self._gb_show(self._gb_index + 1)

    def action_dismiss(self) -> None:
        self.dismiss(False)
