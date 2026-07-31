"""Typer app entry point for the `smash-mods` CLI.

Every subcommand below does the minimum: parse its own flags, hand them to
the matching plain function in commands.py (or profiles_view.py), and exit
with that function's return code. The functions themselves are shared with
the full-screen TUI in tui/, so the two front ends can never drift.

Every wrapped script keeps working completely unchanged when invoked
directly -- this is a layer on top, not a replacement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, List, Optional

import typer

from . import commands
from .profiles_view import profiles_cmd
from .tui import run_tui

app = typer.Typer(
    name="smash-mods",
    help=(
        "Fetch, verify, and stage modded Super Smash Bros. Ultimate SD-card "
        "profiles for a CFW Switch.\n\n"
        "Every subcommand wraps an existing script under scripts/ -- nothing "
        "here changes their behaviour, it just gives them one polished front "
        "door. Run with no subcommand for a full-screen interactive browser."
    ),
    no_args_is_help=False,
    add_completion=True,
    rich_markup_mode="rich",
)

curate_app = typer.Typer(
    help="Curate mod picks (movesets, skins, NSFW). Wraps scripts/curate*.py (each still works standalone).",
    no_args_is_help=True,
)
app.add_typer(curate_app, name="curate")

toggle_app = typer.Typer(
    help="Enable/disable mods on the SD card instantly, no re-copy. Wraps scripts/toggle_mods.sh (still works standalone).",
    no_args_is_help=True,
)
app.add_typer(toggle_app, name="toggle")


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    first_time: Annotated[
        bool,
        typer.Option(
            "--first-time", help="Show the welcome/help tour, whether or not you've seen it before."
        ),
    ] = False,
) -> None:
    """smash-mods: build, verify, deploy, and manage a modded Smash Ultimate SD card."""
    if ctx.invoked_subcommand is None:
        raise typer.Exit(code=run_tui(first_time=first_time))


# --- build -------------------------------------------------------------

@app.command()
def build(
    skip_fetch: Annotated[
        bool, typer.Option("--skip-fetch", help="Rebuild from what's already downloaded; skip the fetch step.")
    ] = False,
) -> None:
    """Fetch, unpack, verify, and stage every profile. Wraps scripts/build.sh (still works standalone)."""
    raise typer.Exit(code=commands.build_cmd(skip_fetch=skip_fetch))


# --- deploy --------------------------------------------------------------

@app.command()
def deploy(
    profile: Annotated[
        str, typer.Option(help="Profile to deploy (see `smash-mods profiles`), or 'list' to show them.")
    ] = "roster",
    target: Annotated[
        Optional[str], typer.Option(help="SD card mount point. Autodetected via its Nintendo/ dir if omitted.")
    ] = None,
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually write to the card. Default is a dry run.")
    ] = False,
    base_only: Annotated[
        bool, typer.Option("--base-only", help="Deploy the base stack only (Skyline/ARCropolis/...), no mods.")
    ] = False,
) -> None:
    """Copy a staged profile onto the Switch SD card. Wraps scripts/deploy.sh (still works standalone)."""
    raise typer.Exit(
        code=commands.deploy_cmd(profile=profile, target=target, commit=commit, base_only=base_only)
    )


# --- backup ---------------------------------------------------------------

@app.command()
def backup(
    mode: Annotated[str, typer.Option(help="Backup mode: archive, tree, or image.")] = "archive",
    target: Annotated[
        Optional[str], typer.Option(help="SD card mount point. Autodetected via its Nintendo/ dir if omitted.")
    ] = None,
    list_: Annotated[bool, typer.Option("--list", help="Show existing backups and exit.")] = False,
    verify: Annotated[
        Optional[str], typer.Option(help="Re-check the integrity of the backup at this path.")
    ] = None,
    restore: Annotated[
        Optional[str], typer.Option(help="Restore this backup onto the card. Default is a dry run.")
    ] = None,
    commit: Annotated[
        bool, typer.Option("--commit", help="With --restore, actually write. Ignored otherwise.")
    ] = False,
    exact: Annotated[
        bool, typer.Option("--exact", help="With --restore, delete card files absent from the backup.")
    ] = False,
) -> None:
    """Create or restore a full snapshot of the SD card. Wraps scripts/backup.sh (still works standalone)."""
    raise typer.Exit(
        code=commands.backup_cmd(
            mode=mode, target=target, list_=list_, verify=verify, restore=restore, commit=commit, exact=exact
        )
    )


# --- verify -----------------------------------------------------------------

@app.command()
def verify(
    workspace: Annotated[Optional[str], typer.Option(help="Workspace to lint (e.g. roster).")] = None,
    profile: Annotated[
        Optional[str], typer.Option(help="Profile to lint -- the union of all its layers, as staged.")
    ] = None,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as errors.")] = False,
) -> None:
    """Lint a workspace or profile for mod-layout problems before staging/deploying. Wraps scripts/verify.py (still works standalone)."""
    raise typer.Exit(code=commands.verify_cmd(workspace=workspace, profile=profile, strict=strict))


# --- profiles -----------------------------------------------------------

@app.command()
def profiles() -> None:
    """Show every profile from profiles.toml: composition, plugin budget, and hardware-test status."""
    raise typer.Exit(code=profiles_cmd())


# --- toggle ---------------------------------------------------------------

@toggle_app.command("status")
def toggle_status() -> None:
    """Show which mods and plugins are currently enabled on the card."""
    raise typer.Exit(code=commands.toggle_status_cmd())


@toggle_app.command("on")
def toggle_on(glob: Annotated[str, typer.Argument(help="Mod-name glob to enable, e.g. 'Skin-A*'.")]) -> None:
    """Enable mods matching a glob (renames .Mod -> Mod on the card)."""
    raise typer.Exit(code=commands.toggle_on_cmd(glob))


@toggle_app.command("off")
def toggle_off(glob: Annotated[str, typer.Argument(help="Mod-name glob to disable, e.g. 'Skin-*'.")]) -> None:
    """Disable mods matching a glob (renames Mod -> .Mod on the card)."""
    raise typer.Exit(code=commands.toggle_off_cmd(glob))


@toggle_app.command("batch")
def toggle_batch(
    file: Annotated[Path, typer.Argument(help="File listing mod names, one per line.")],
    action: Annotated[str, typer.Argument(help="on or off.")],
) -> None:
    """Toggle every mod listed in a file at once (used to bisect crashes)."""
    raise typer.Exit(code=commands.toggle_batch_cmd(str(file), action))


@toggle_app.command("plugins-off")
def toggle_plugins_off(
    mods: Annotated[List[str], typer.Argument(help="Mod names to disable plugin.nro for.")],
) -> None:
    """Disable just a mod's plugin.nro, keeping its other assets active."""
    raise typer.Exit(code=commands.toggle_plugins_off_cmd(mods))


@toggle_app.command("plugins-on")
def toggle_plugins_on(
    mods: Annotated[List[str], typer.Argument(help="Mod names to re-enable plugin.nro for.")],
) -> None:
    """Re-enable a previously disabled plugin.nro for specific mods."""
    raise typer.Exit(code=commands.toggle_plugins_on_cmd(mods))


# --- curate -----------------------------------------------------------------

@curate_app.command("movesets")
def curate_movesets(
    report: Annotated[bool, typer.Option("--report", help="Print a report only.")] = False,
    write: Annotated[bool, typer.Option("--write", help="Write the curated selection to roster.toml.")] = False,
    limit: Annotated[int, typer.Option(help="Max moveset picks to consider.")] = 24,
) -> None:
    """Curate added-character moveset picks. Wraps scripts/curate.py (still works standalone)."""
    raise typer.Exit(code=commands.curate_movesets_cmd(report=report, write=write, limit=limit))


@curate_app.command("skins")
def curate_skins(
    report: Annotated[bool, typer.Option("--report", help="Print a report only.")] = False,
    write: Annotated[bool, typer.Option("--write", help="Write the curated selection.")] = False,
    limit: Annotated[int, typer.Option(help="Max fighters to consider (0 = no cap).")] = 0,
) -> None:
    """Curate vanilla-fighter reskin picks. Wraps scripts/curate_skins.py (still works standalone)."""
    raise typer.Exit(code=commands.curate_skins_cmd(report=report, write=write, limit=limit))


@curate_app.command("nsfw")
def curate_nsfw(
    report: Annotated[bool, typer.Option("--report", help="Print a report only.")] = False,
    write: Annotated[bool, typer.Option("--write", help="Write the curated selection.")] = False,
) -> None:
    """Curate the NSFW skin-swap layer. Wraps scripts/curate_nsfw.py (still works standalone)."""
    raise typer.Exit(code=commands.curate_nsfw_cmd(report=report, write=write))


# --- dedupe -------------------------------------------------------------

@app.command()
def dedupe(
    layer: Annotated[str, typer.Option(help="Cosmetic layer to trim, e.g. reskin.")],
    against: Annotated[str, typer.Option(help="Layer that wins on a conflict.")] = "roster",
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually remove the duplicate files. Default is a dry run.")
    ] = False,
) -> None:
    """Strip files from a cosmetic layer that a base layer already overrides. Wraps scripts/dedupe_layer.py (still works standalone)."""
    raise typer.Exit(code=commands.dedupe_cmd(layer=layer, against=against, commit=commit))


# --- unlock-save --------------------------------------------------------

@app.command(name="unlock-save")
def unlock_save(
    save: Annotated[Path, typer.Argument(help="Path to system_data.bin.")],
    commit: Annotated[
        bool, typer.Option("--commit", help="Actually patch the save file. Default is a dry run.")
    ] = False,
) -> None:
    """Unlock every fighter in a save file so added characters' host slots are reachable. Wraps scripts/unlock_save.py (still works standalone)."""
    raise typer.Exit(code=commands.unlock_save_cmd(str(save), commit=commit))


# --- create-profile -------------------------------------------------------

@app.command(name="create-profile")
def create_profile(
    name: Annotated[str, typer.Argument(help="New profile's name -- becomes its table name in profiles.toml.")],
    description: Annotated[str, typer.Option(help="One-line description shown in `smash-mods profiles`.")],
    layers: Annotated[
        Optional[str], typer.Option(help="Comma-separated workspace names, later wins, e.g. roster,reskin.")
    ] = None,
    selfcontained: Annotated[
        Optional[str], typer.Option(help="A single workspace that ships its own base stack (e.g. hdr).")
    ] = None,
    base: Annotated[bool, typer.Option(help="Install the pinned base stack. Ignored with --selfcontained.")] = True,
) -> None:
    """Add a new profile to profiles.toml. Wraps scripts/profile_edit.py (still works standalone)."""
    layer_list = [l.strip() for l in layers.split(",") if l.strip()] if layers else None
    raise typer.Exit(
        code=commands.create_profile_cmd(
            name, description=description, layers=layer_list, selfcontained=selfcontained, base=base
        )
    )


# --- move-mod ---------------------------------------------------------------

@app.command(name="move-mod")
def move_mod(
    name: Annotated[str, typer.Argument(help="Mod's directory name, e.g. Skin-Marth.")],
    from_workspace: Annotated[str, typer.Option("--from", help="Workspace the mod currently lives in.")],
    to_workspace: Annotated[str, typer.Option("--to", help="Workspace to move it into.")],
) -> None:
    """Move a mod to a different workspace -- changes which profiles it's part of. Wraps scripts/move_mod.py (still works standalone)."""
    raise typer.Exit(code=commands.move_mod_cmd(name, from_workspace=from_workspace, to_workspace=to_workspace))


# --- create-workspace ---------------------------------------------------------

@app.command(name="create-workspace")
def create_workspace(
    name: Annotated[str, typer.Argument(help="New workspace's name, e.g. my-custom-layer.")],
) -> None:
    """Create a new, empty workspace -- a category to move mods into and reference from a custom profile. Wraps scripts/create_workspace.py (still works standalone)."""
    raise typer.Exit(code=commands.create_workspace_cmd(name))


if __name__ == "__main__":
    app()
