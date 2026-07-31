"""Root Textual application for smash-mods.

Screens push/pop off SmashModsApp the same way any Textual app works. The app
itself holds no business logic -- screens/widgets call straight into
smash_mods_cli.commands (the same dispatch layer Typer uses) for anything
that isn't pure read-only browsing.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from . import first_run
from .screens.home import HomeScreen
from .screens.welcome import WelcomeScreen

_STYLES_PATH = Path(__file__).parent / "styles.tcss"


class SmashModsApp(App):
    """Full-screen browse-and-act front end for the smash-mods mod collection."""

    TITLE = "smash-mods"
    CSS_PATH = _STYLES_PATH
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("?", "show_welcome", "Help"),
    ]

    def __init__(self, *args, show_welcome: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._show_welcome_on_mount = show_welcome

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
        if self._show_welcome_on_mount:
            self.push_screen(WelcomeScreen())
            first_run.mark_seen()

    def action_show_welcome(self) -> None:
        self.push_screen(WelcomeScreen())
