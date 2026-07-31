"""ProfileWizardScreen: build a new profile and append it to profiles.toml.

A profile is either a layered stack of workspaces (later layers win on a
name clash -- see profiles.toml's own header comment) or a single
selfcontained workspace that ships its own base stack. This mirrors that
choice directly: pick a mode, pick workspace(s), see the resulting mod count
and plugin-budget live (same coloring/thresholds `smash-mods profiles`
uses), then save. Saving goes through commands.create_profile_cmd(), which
appends to profiles.toml the same way scripts/profile_edit.py would if
called by hand -- nothing here writes TOML directly.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RadioButton, RadioSet, SelectionList, Static, Switch

from ... import commands
from ...paths import SCRIPTS  # noqa: F401  (import side effect: scripts/ on sys.path)
from ...profiles_view import PLUGIN_BUDGET_ERROR, PLUGIN_BUDGET_WARN, _plugin_cell
from .live_output import LiveOutputScreen


class ProfileWizardScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        import common  # scripts/common.py

        workspaces = common.list_workspaces()

        yield Header()
        with Vertical(id="content"):
            yield Static(
                "Create a new profile. Layered profiles stack workspaces (later wins on a "
                "name clash); selfcontained profiles are a single workspace that ships its own base stack.\n"
                "[dim]Need a workspace that doesn't exist yet? Back out and use the 'Create workspace' "
                "action first, then come back here.[/dim]"
            )
            yield Input(placeholder="Profile name (e.g. my-custom)", id="name")
            yield Input(placeholder="One-line description", id="description")
            yield RadioSet(
                RadioButton("layered", value=True),
                RadioButton("selfcontained"),
                id="mode",
            )
            with Vertical(id="layered-fields"):
                yield Static("Layers, in order (later overrides earlier on a name clash):")
                yield SelectionList(*[(name, name) for name in workspaces], id="layers-select")
                yield Static("Install the pinned base stack (Skyline/ARCropolis/...):")
                yield Switch(id="base-switch", value=True)
            with Vertical(id="selfcontained-fields"):
                yield Static("Workspace that ships its own base stack:")
                yield RadioSet(*[RadioButton(name) for name in workspaces], id="selfcontained-select")
            yield Static(id="preview")
            yield Button("Create profile", id="create-btn", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#selfcontained-fields").display = False
        self._update_preview()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "mode":
            layered = event.index == 0
            self.query_one("#layered-fields").display = layered
            self.query_one("#selfcontained-fields").display = not layered
        self._update_preview()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        self._update_preview()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._update_preview()

    def _mode(self) -> str:
        mode_set = self.query_one("#mode", RadioSet)
        return "layered" if mode_set.pressed_index == 0 else "selfcontained"

    def _selected_layers(self) -> list[str]:
        return list(self.query_one("#layers-select", SelectionList).selected)

    def _selected_selfcontained(self) -> str | None:
        rs = self.query_one("#selfcontained-select", RadioSet)
        return str(rs.pressed_button.label) if rs.pressed_button else None

    def _update_preview(self) -> None:
        import common  # scripts/common.py

        preview = self.query_one("#preview", Static)
        if self._mode() == "layered":
            chosen: dict[str, object] = {}
            for layer in self._selected_layers():
                for mod in common.all_mods(layer):
                    chosen[mod.name] = mod
            mods = list(chosen.values())
        else:
            workspace = self._selected_selfcontained()
            mods = common.all_mods(workspace) if workspace else []

        n_plugins = sum(1 for m in mods if (m / "plugin.nro").is_file())
        preview.update(
            f"Preview: {len(mods)} mods, {_plugin_cell(n_plugins)} with plugin.nro "
            f"(green <={PLUGIN_BUDGET_WARN}, yellow <={PLUGIN_BUDGET_ERROR}, red above)"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "create-btn":
            return
        name = self.query_one("#name", Input).value.strip()
        description = self.query_one("#description", Input).value.strip()
        if not name or not description:
            self.app.notify("Name and description are both required.", severity="warning")
            return

        if self._mode() == "layered":
            layers = self._selected_layers()
            if not layers:
                self.app.notify("Pick at least one layer.", severity="warning")
                return
            base = self.query_one("#base-switch", Switch).value
            argv = commands.create_profile_argv(name, description=description, layers=layers, base=base)
        else:
            selfcontained = self._selected_selfcontained()
            if not selfcontained:
                self.app.notify("Pick a selfcontained workspace.", severity="warning")
                return
            argv = commands.create_profile_argv(name, description=description, selfcontained=selfcontained)

        async def on_done(code: int | None) -> None:
            if code != 0:
                return
            self.app.pop_screen()
            home = self.app.screen
            await home._load_nav()
            home.select_profile(name)

        self.app.push_screen(LiveOutputScreen(argv, title=f"Create profile '{name}'"), callback=on_done)
