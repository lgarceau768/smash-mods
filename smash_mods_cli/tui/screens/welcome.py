"""WelcomeScreen: a short tour shown on first run (or via --first-time /
the '?' key anytime), explaining what smash-mods is and how to use it."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

_BODY = """\
[bold]Welcome to smash-mods[/bold]

A Smash Ultimate modpack creator and deployer: curate mods from GameBanana, \
assemble them into a [bold]profile[/bold], and deploy it to a modded SD card.

[bold accent]The shape of the data[/bold accent]
  * [bold]All mods[/bold] (top of the left nav) opens a dedicated explorer \
for every mod you have data on, fetched or not -- search, filter by \
workspace/status, sort, and a live thumbnail preview pane as you browse, \
plus which profile(s) each mod is part of and a way to move it to a \
different workspace.
  * [bold]Workspaces[/bold] are categories of mods -- roster (added \
characters), reskin, nsfw, celshaded, chao5, parked, and any selfcontained \
total-conversion like hdr. Browsing one in the left nav filters the same \
data down to just that category.
  * [bold]Profiles[/bold] are what you actually deploy to the card: either a \
[i]layered[/i] stack of workspaces (later layers override earlier ones), or \
a single [i]selfcontained[/i] workspace that ships its own base stack.
  * A mod's [bold]workspace[/bold] is what determines which profiles it's \
part of -- there's no separate per-mod pick-list. That's the one lever: \
open any mod's detail view (even one not fetched yet) to see which profiles \
include it, and to move/retarget it to a different workspace.
  * [bold]roster.toml[/bold] is your personal curated pick-list, pinned by \
GameBanana id. The Curate action surveys GameBanana, shows every candidate \
as a checklist (all selected by default), and pins only what you keep -- \
then still needs Build to actually fetch and unpack them.

[bold accent]Getting around[/bold accent]
  * Arrow keys or click to move through the left nav and mod lists.
  * [bold]/[/bold] to filter the current mod list as you type.
  * Enter or click a mod to see its full detail -- including its GameBanana \
description, stats, and screenshots when it's a pinned roster.toml pick, \
even before it's fetched.
  * The [bold]ACTIONS[/bold] section lists everything you can do (Build, \
Deploy, Backup, Verify, Curate, Toggle, Dedupe, Unlock save, Create profile) \
with a plain description of what each one does before you run it -- actions \
run inline with live output, never dropping you to a bare terminal.
  * [bold]p[/bold] jumps to the full profiles table; click a row to browse \
that profile's mods.
  * [bold]e[/bold]/[bold]d[/bold] enable/disable the selected mod on the SD \
card instantly, without a redeploy.
  * [bold]Esc[/bold] goes back; [bold]q[/bold] quits.

Every action that writes real data (deploy, backup restore, dedupe, unlock \
save) is a dry run by default and asks you to confirm before it actually \
writes anything.

Press [bold]?[/bold] any time to see this again.
"""


class WelcomeScreen(ModalScreen):
    BINDINGS = [("escape", "dismiss", "Close"), ("enter", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-panel"):
            with VerticalScroll(id="welcome-body"):
                yield Static(_BODY)
            yield Button("Got it", id="welcome-dismiss", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "welcome-dismiss":
            self.dismiss()

    def action_dismiss(self) -> None:
        self.dismiss()
