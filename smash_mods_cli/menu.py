"""The bare `smash-mods` interactive menu.

Every action here dispatches into the exact same functions the Typer
subcommands in main.py call (see commands.py) -- this module only prompts for
the arguments a subcommand would otherwise take as CLI flags. It never
reimplements a script invocation itself.
"""

from __future__ import annotations

from rich.prompt import Confirm, IntPrompt, Prompt

from . import commands
from .profiles_view import profiles_cmd, render_profiles_table
from .ui import console

MENU_ITEMS = [
    ("Show profile status", "profiles"),
    ("Build", "build"),
    ("Deploy a profile", "deploy"),
    ("Backup", "backup"),
    ("Verify", "verify"),
    ("Toggle mods", "toggle"),
    ("Curate", "curate"),
    ("Unlock save", "unlock-save"),
    ("Quit", "quit"),
]


def _print_menu() -> None:
    console.print()
    console.rule("[bold]smash-mods[/bold]")
    for i, (label, _) in enumerate(MENU_ITEMS, start=1):
        console.print(f"  [cyan]{i}[/cyan]. {label}")
    console.print()


def _do_profiles() -> None:
    profiles_cmd()


def _do_build() -> None:
    skip_fetch = Confirm.ask("Skip fetch (rebuild from what's already downloaded)?", default=False)
    commands.build_cmd(skip_fetch=skip_fetch)


def _do_deploy() -> None:
    console.print(render_profiles_table())
    profile = Prompt.ask("Profile to deploy", default="roster")
    base_only = Confirm.ask("Base stack only, no mods (--base-only)?", default=False)
    commit = Confirm.ask("[bold]Write for real (--commit)?[/bold] (no = dry run)", default=False)
    commands.deploy_cmd(profile=profile, base_only=base_only, commit=commit, interactive_menu=True)


def _do_backup() -> None:
    action = Prompt.ask("Action", choices=["create", "list", "verify", "restore"], default="create")
    if action == "list":
        commands.backup_cmd(list_=True)
        return
    if action == "verify":
        path = Prompt.ask("Backup path to verify")
        commands.backup_cmd(verify=path)
        return
    if action == "restore":
        path = Prompt.ask("Backup path to restore from")
        exact = Confirm.ask("Exact restore (delete card files absent from the backup)?", default=False)
        commit = Confirm.ask("[bold]Write for real (--commit)?[/bold] (no = dry run)", default=False)
        commands.backup_cmd(restore=path, exact=exact, commit=commit, interactive_menu=True)
        return
    mode = Prompt.ask("Backup mode", choices=["archive", "tree", "image"], default="archive")
    commands.backup_cmd(mode=mode)


def _do_verify() -> None:
    workspace = Prompt.ask("Workspace to verify (blank to skip)", default="") or None
    profile = Prompt.ask("Profile to verify (blank to skip)", default="") or None
    strict = Confirm.ask("Strict mode (treat warnings as errors)?", default=False)
    commands.verify_cmd(workspace=workspace, profile=profile, strict=strict)


def _do_toggle() -> None:
    action = Prompt.ask(
        "Toggle action",
        choices=["status", "on", "off", "batch", "plugins-off", "plugins-on"],
        default="status",
    )
    if action == "status":
        commands.toggle_status_cmd()
    elif action == "on":
        commands.toggle_on_cmd(Prompt.ask("Glob pattern to enable"))
    elif action == "off":
        commands.toggle_off_cmd(Prompt.ask("Glob pattern to disable"))
    elif action == "batch":
        file = Prompt.ask("Batch file path (one mod name per line)")
        sub = Prompt.ask("on or off", choices=["on", "off"], default="off")
        commands.toggle_batch_cmd(file, sub)
    elif action == "plugins-off":
        mods = Prompt.ask("Mod names to disable plugin.nro for (space-separated)").split()
        commands.toggle_plugins_off_cmd(mods)
    elif action == "plugins-on":
        mods = Prompt.ask("Mod names to re-enable plugin.nro for (space-separated)").split()
        commands.toggle_plugins_on_cmd(mods)


def _do_curate() -> None:
    kind = Prompt.ask("Curator", choices=["movesets", "skins", "nsfw"], default="movesets")
    report = Confirm.ask("Report only (no changes)?", default=True)
    write = False if report else Confirm.ask("Write the curated selection?", default=False)
    if kind == "movesets":
        limit = IntPrompt.ask("Limit", default=24)
        commands.curate_movesets_cmd(report=report, write=write, limit=limit)
    elif kind == "skins":
        limit = IntPrompt.ask("Limit (0 = no cap)", default=0)
        commands.curate_skins_cmd(report=report, write=write, limit=limit)
    else:
        commands.curate_nsfw_cmd(report=report, write=write)


def _do_unlock_save() -> None:
    save = Prompt.ask("Path to system_data.bin")
    commit = Confirm.ask("[bold]Write for real (--commit)?[/bold] (no = dry run)", default=False)
    commands.unlock_save_cmd(save, commit=commit, interactive_menu=True)


_HANDLERS = {
    "profiles": _do_profiles,
    "build": _do_build,
    "deploy": _do_deploy,
    "backup": _do_backup,
    "verify": _do_verify,
    "toggle": _do_toggle,
    "curate": _do_curate,
    "unlock-save": _do_unlock_save,
}


def run_menu() -> int:
    """Loop the interactive menu until the user quits. Returns an exit code."""
    while True:
        _print_menu()
        try:
            choice = IntPrompt.ask("Choose an option", default=len(MENU_ITEMS))
        except (KeyboardInterrupt, EOFError):
            console.print("\nBye.")
            return 0
        if choice < 1 or choice > len(MENU_ITEMS):
            console.print("[red]Invalid choice.[/red]")
            continue
        _, key = MENU_ITEMS[choice - 1]
        if key == "quit":
            console.print("Bye.")
            return 0
        try:
            _HANDLERS[key]()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Cancelled.[/yellow]")
