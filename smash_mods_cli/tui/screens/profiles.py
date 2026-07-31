"""ProfilesScreen: profiles.toml as a clickable table.

Reuses profiles_view's own per-profile computation (plugin counts, layer
summaries, status coloring) so this can never drift from what
`smash-mods profiles` itself prints -- only the presentation becomes a
DataTable instead of a static Rich Table, so a row can be clicked/Enter'd to
drill straight into that profile's mods on HomeScreen (the browse-to-act path
that a plain, non-interactive table couldn't offer).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Static

from ...profiles_view import (
    PLUGIN_BUDGET_ERROR,
    PLUGIN_BUDGET_WARN,
    STATUS_STYLE,
    _layer_summary,
    _plugin_cell,
    _profile_plugin_count,
)


class ProfilesScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static(
                "Click a profile (or press Enter) to browse its mods. "
                f"Plugins: green <={PLUGIN_BUDGET_WARN}, "
                f"yellow {PLUGIN_BUDGET_WARN + 1}-{PLUGIN_BUDGET_ERROR}, red >{PLUGIN_BUDGET_ERROR}."
            )
            yield DataTable(id="profiles-table", cursor_type="row", zebra_stripes=True)
            with Horizontal():
                yield Input(placeholder="Profile name to deploy", id="deploy-profile")
                yield Button("Deploy...", id="deploy-btn", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        import common  # scripts/common.py

        table = self.query_one("#profiles-table", DataTable)
        table.add_columns("Profile", "Description", "Composition", "Plugins", "Status", "Tested on")

        profiles = common.load_profiles()
        for name, prof in sorted(profiles.items()):
            n_plugins = _profile_plugin_count(name, common)
            status = prof.get("status", "untested")
            style = STATUS_STYLE.get(status, "yellow")
            table.add_row(
                name,
                prof.get("description", ""),
                _layer_summary(prof),
                _plugin_cell(n_plugins),
                f"[{style}]{status}[/{style}]",
                prof.get("tested_on") or "-",
                key=name,
            )
        if profiles:
            table.move_cursor(row=0)
            self._sync_deploy_input(sorted(profiles)[0])

    def _sync_deploy_input(self, profile_name: str) -> None:
        self.query_one("#deploy-profile", Input).value = profile_name

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value is not None:
            self._sync_deploy_input(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        profile_name = event.row_key.value
        if profile_name is None:
            return
        self.app.pop_screen()
        home = self.app.screen
        home.select_profile(profile_name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "deploy-btn":
            return
        from .action_forms import DeployFormScreen

        profile = self.query_one("#deploy-profile", Input).value.strip() or "roster"
        self.app.push_screen(DeployFormScreen(profile=profile))
