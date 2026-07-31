"""ToggleScreen: enable/disable mods on the SD card by glob, and show status.

Builds argv via the exact same commands.toggle_*_argv functions the Typer
subcommands use, then runs it through LiveOutputScreen so toggle_mods.sh's
own output (and any "no card mounted" error) streams live inside the TUI.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static

from ... import commands
from .live_output import LiveOutputScreen


class ToggleScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="content"):
            yield Static(
                "Enable/disable mods on the SD card by glob (e.g. 'Skin-*'). "
                "Leave blank and press Status to just check current state."
            )
            yield Input(placeholder="Mod-name glob", id="glob")
            yield Button("Status", id="status-btn")
            yield Button("Enable", id="on-btn", variant="success")
            yield Button("Disable", id="off-btn", variant="warning")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        glob = self.query_one("#glob", Input).value.strip()
        if event.button.id == "status-btn":
            self.app.push_screen(LiveOutputScreen(commands.toggle_status_argv(), title="Toggle status"))
        elif event.button.id == "on-btn":
            if not glob:
                self.app.notify("Enter a glob first.", severity="warning")
                return
            self.app.push_screen(LiveOutputScreen(commands.toggle_on_argv(glob), title=f"Enable '{glob}'"))
        elif event.button.id == "off-btn":
            if not glob:
                self.app.notify("Enter a glob first.", severity="warning")
                return
            self.app.push_screen(LiveOutputScreen(commands.toggle_off_argv(glob), title=f"Disable '{glob}'"))
