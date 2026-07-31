"""HomeScreen: the landing screen -- workspace/profile/roster/action nav on
the left, and either a filterable mod list or an action's description on the
right, depending on what's selected. Every action is reachable by clicking
(or arrowing to) its row and pressing Enter/clicking Open -- no keybinding to
memorize.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from ... import commands
from ...paths import SCRIPTS  # noqa: F401  (import side effect: scripts/ on sys.path)
from ..actions_catalog import ACTIONS, ACTIONS_BY_ID
from ..widgets.mod_list import ModEntry, ModListView
from .live_output import LiveOutputScreen
from .mod_detail import ModDetailModal


@dataclass
class NavEntry:
    kind: str  # "header" | "all-mods" | "workspace" | "profile" | "action"
    label: str
    name: str = ""  # workspace/profile/action id; unused for "header"/"all-mods"


class HomeScreen(Screen):
    BINDINGS = [
        ("/", "focus_search", "Search"),
        ("p", "show_profiles", "Profiles"),
        ("e", "enable_mod", "Enable"),
        ("d", "disable_mod", "Disable"),
        ("escape", "clear_search", "Back"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_profile = "roster"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield ListView(id="nav")
            with Vertical(id="content"):
                yield Input(placeholder="Filter mods...", id="search")
                yield ModListView(id="mod-list")
                with Vertical(id="action-panel"):
                    yield Static(id="action-desc")
                    yield Button("Open", id="action-open-btn", variant="primary")
        yield Static(id="status-line")
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_nav()
        nav = self.query_one("#nav", ListView)
        # Select the first real (non-header) entry so a mod list shows immediately.
        for index, item in enumerate(nav.children):
            entry: NavEntry = item.nav_entry  # type: ignore[attr-defined]
            if entry.kind != "header":
                nav.index = index
                break
        self._load_for_nav_entry(self._current_nav_entry())

    async def _load_nav(self) -> None:
        """(Re)build the nav list. Callers that need to select a specific
        entry right after (select_profile/select_workspace) must await this
        first -- clear()/extend() are async DOM operations, and calling them
        without awaiting (as this used to) left a window where nav.children
        was transiently doubled (old items not yet removed, new ones already
        added), which could make an immediate post-load selection miss."""
        import common  # scripts/common.py

        nav = self.query_one("#nav", ListView)
        entries: list[NavEntry] = [
            NavEntry("header", "MODS  ·  everything you have data on"),
            NavEntry("all-mods", "All mods (fetched + pending)", "all-mods"),
        ]
        entries.append(NavEntry("header", "WORKSPACES  ·  mods, grouped by category"))
        entries += [NavEntry("workspace", name, name) for name in common.list_workspaces()]
        entries.append(NavEntry("header", "PROFILES  ·  what you deploy to the card"))
        entries += [NavEntry("profile", name, name) for name in sorted(common.load_profiles())]
        entries.append(NavEntry("header", "ACTIONS  ·  build, deploy, curate, and more"))
        entries += [NavEntry("action", a.label, a.id) for a in ACTIONS]

        items = []
        for entry in entries:
            label = Label(entry.label)
            item = ListItem(label, classes="-section" if entry.kind == "header" else "")
            item.nav_entry = entry  # type: ignore[attr-defined]
            item.disabled = entry.kind == "header"
            items.append(item)
        await nav.clear()
        await nav.extend(items)

    def select_profile(self, name: str) -> None:
        """Jump the nav to a profile by name and load its mod list.

        Used by ProfilesScreen to drill from a clicked/selected profile row
        straight into that profile's mods, instead of leaving the user to
        hunt for it again in the nav list by hand.
        """
        nav = self.query_one("#nav", ListView)
        for index, item in enumerate(nav.children):
            entry: NavEntry = item.nav_entry  # type: ignore[attr-defined]
            if entry.kind == "profile" and entry.name == name:
                nav.index = index
                nav.focus()
                return

    def select_workspace(self, name: str) -> None:
        """Jump the nav to a workspace by name and load its mod list -- used
        after creating one, so it's immediately visible rather than leaving
        the nav on whatever it was previously showing."""
        nav = self.query_one("#nav", ListView)
        for index, item in enumerate(nav.children):
            entry: NavEntry = item.nav_entry  # type: ignore[attr-defined]
            if entry.kind == "workspace" and entry.name == name:
                nav.index = index
                nav.focus()
                return

    def _current_nav_entry(self) -> NavEntry | None:
        nav = self.query_one("#nav", ListView)
        highlighted = nav.highlighted_child
        if highlighted is None:
            return None
        return getattr(highlighted, "nav_entry", None)

    def _load_for_nav_entry(self, entry: NavEntry | None) -> None:
        import common  # scripts/common.py

        mod_list = self.query_one("#mod-list", ModListView)
        search = self.query_one("#search", Input)
        action_panel = self.query_one("#action-panel", Vertical)
        status = self.query_one("#status-line", Static)

        if entry is not None and entry.kind == "action":
            mod_list.display = False
            search.display = False
            action_panel.display = True
            info = ACTIONS_BY_ID[entry.name]
            note = " Can write to disk/card." if info.writes_data else " Read-only, never writes anything."
            self.query_one("#action-desc", Static).update(f"[bold]{info.label}[/bold]\n\n{info.description}{note}")
            status.update("")
            return

        if entry is not None and entry.kind == "all-mods":
            mod_list.display = False
            search.display = False
            action_panel.display = True
            self.query_one("#action-desc", Static).update(
                "[bold]All mods[/bold]\n\n"
                "Search, filter, and sort every mod you have data on -- fetched or not -- "
                "with a live thumbnail preview pane. Opens a dedicated explorer screen."
            )
            status.update("")
            return

        mod_list.display = True
        search.display = True
        action_panel.display = False

        if entry is None or entry.kind == "header":
            mod_list.load([])
            status.update("")
            return

        if entry.kind == "workspace":
            paths = common.all_mods(entry.name)
            mod_entries = [self._mod_entry_from_path(p, common) for p in paths]
            profiles_using_it = common.profiles_including_workspace(entry.name)
            where = f" -- used by profile(s): {', '.join(profiles_using_it)}" if profiles_using_it else " -- not used by any profile yet"
            status.update(f"workspace '{entry.name}': {len(mod_entries)} mods installed{where}")
        else:  # profile
            self._last_profile = entry.name
            paths = common.profile_mods(entry.name)
            mod_entries = [self._mod_entry_from_path(p, common) for p in paths]
            status.update(f"profile '{entry.name}' would deploy {len(mod_entries)} mods to the card")

        mod_list.load(mod_entries)

    @staticmethod
    def _mod_entry_from_path(path: Path, common) -> ModEntry:
        info = common.mod_info(path)
        subtitle = info.get("display_name") or info.get("category") or ""
        return ModEntry(name=path.name, path=path, subtitle=subtitle)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id == "nav":
            self._load_for_nav_entry(self._current_nav_entry())

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "nav":
            entry = self._current_nav_entry()
            if entry is not None and entry.kind == "action":
                self._open_action(entry.name)
            elif entry is not None and entry.kind == "all-mods":
                self._open_all_mods()
            return
        if event.list_view.id != "mod-list":
            return
        mod_list = self.query_one("#mod-list", ModListView)
        entry = mod_list.selected_entry
        if entry is not None and entry.path is not None:
            self.app.push_screen(ModDetailModal(entry.path), callback=self._on_mod_detail_closed)

    def _on_mod_detail_closed(self, moved: bool | None) -> None:
        if moved:
            self._load_for_nav_entry(self._current_nav_entry())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "action-open-btn":
            return
        entry = self._current_nav_entry()
        if entry is not None and entry.kind == "action":
            self._open_action(entry.name)
        elif entry is not None and entry.kind == "all-mods":
            self._open_all_mods()

    def _open_all_mods(self) -> None:
        from .all_mods import AllModsScreen

        self.app.push_screen(AllModsScreen())

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        self.query_one("#mod-list", ModListView).filter_text(event.value)

    def action_focus_search(self) -> None:
        self.query_one("#search", Input).focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        if search.has_focus:
            search.value = ""
            self.query_one("#mod-list", ModListView).filter_text("")
            self.query_one("#mod-list", ModListView).focus()

    def action_show_profiles(self) -> None:
        from .profiles import ProfilesScreen

        self.app.push_screen(ProfilesScreen())

    def action_enable_mod(self) -> None:
        self._toggle_selected(on=True)

    def action_disable_mod(self) -> None:
        self._toggle_selected(on=False)

    def _toggle_selected(self, *, on: bool) -> None:
        mod_list = self.query_one("#mod-list", ModListView)
        entry = mod_list.selected_entry
        if entry is None:
            return
        if entry.path is None:
            self.app.notify(
                f"{entry.name} has no local mod directory to toggle.", severity="warning"
            )
            return
        argv_fn = commands.toggle_on_argv if on else commands.toggle_off_argv
        title = f"{'Enable' if on else 'Disable'} '{entry.name}'"
        self.app.push_screen(LiveOutputScreen(argv_fn(entry.name), title=title))

    def _current_profile_name(self) -> str:
        """The profile Deploy should default to: whichever one was last
        browsed in the nav (workspace/action selections don't clear this)."""
        return self._last_profile

    def _open_action(self, action_id: str) -> None:
        if action_id == "create-workspace":
            from .action_forms import CreateWorkspaceFormScreen

            self.app.push_screen(CreateWorkspaceFormScreen())
        elif action_id == "create-profile":
            from .profile_wizard import ProfileWizardScreen

            self.app.push_screen(ProfileWizardScreen())
        elif action_id == "build":
            from .action_forms import BuildFormScreen

            self.app.push_screen(BuildFormScreen())
        elif action_id == "deploy":
            from .action_forms import DeployFormScreen

            self.app.push_screen(DeployFormScreen(profile=self._current_profile_name()))
        elif action_id == "backup":
            from .action_forms import BackupFormScreen

            self.app.push_screen(BackupFormScreen())
        elif action_id == "verify":
            from .action_forms import VerifyFormScreen

            self.app.push_screen(VerifyFormScreen())
        elif action_id == "curate":
            from .curate_review import CurateReviewScreen

            self.app.push_screen(CurateReviewScreen())
        elif action_id == "toggle":
            from .toggle import ToggleScreen

            self.app.push_screen(ToggleScreen())
        elif action_id == "dedupe":
            from .action_forms import DedupeFormScreen

            self.app.push_screen(DedupeFormScreen())
        elif action_id == "unlock-save":
            from .action_forms import UnlockSaveFormScreen

            self.app.push_screen(UnlockSaveFormScreen())
