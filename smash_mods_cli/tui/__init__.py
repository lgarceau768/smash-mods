"""Full-screen Textual front end for smash-mods.

Alongside the Typer subcommands, this is the CLI's second front end: it
never talks to scripts/ directly, every action it can trigger calls straight
into the same smash_mods_cli.commands functions Typer uses, so the two front
ends can never drift from each other.
"""

from __future__ import annotations

import sys


def run_tui(*, first_time: bool = False) -> int:
    """Launch the TUI, or print a fallback message if stdio isn't a real tty.

    Mirrors the isatty guard commands._confirm_commit already relies on --
    a Textual app can't do anything useful piped or redirected, and shouldn't
    hang trying.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        from ..ui import console

        console.print(
            "[yellow]smash-mods: no interactive terminal detected; "
            "run a specific subcommand instead (see --help).[/yellow]"
        )
        return 0

    # textual-image's terminal-graphics-protocol detection sends an escape
    # sequence and reads the raw response from stdin -- it only works before
    # Textual's own driver has started reading stdin on a thread (its own
    # docs say so explicitly). Importing it here, before SmashModsApp starts,
    # means detection runs once against a "quiet" terminal and every later
    # (lazy) import of textual_image.widget just reuses that cached result --
    # skip this and every image silently falls back to the low-fidelity
    # unicode/halfblock renderer even in a Kitty/Sixel-capable terminal.
    import textual_image.widget  # noqa: F401

    from . import first_run
    from .app import SmashModsApp

    show_welcome = first_time or first_run.is_first_run()
    SmashModsApp(show_welcome=show_welcome).run()
    return 0
