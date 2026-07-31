"""Plain functions backing every subcommand.

Each Typer command in main.py calls one of the `*_cmd()` functions below --
they build the argv the equivalent hand-typed `./scripts/...` invocation
would use, run it synchronously with inherited stdio (correct for a real
terminal), and return the exit code.

The TUI (tui/) doesn't call `*_cmd()` -- it needs the same argv but must run
it asynchronously with piped (not inherited) stdio, streamed into
tui/screens/live_output.py's LiveOutputScreen instead of the raw terminal
(see that module's docstring for why). So every action also has a matching
`*_argv()` function that only builds the argv list; `*_cmd()` is just
`*_argv()` + guardrail + run(). Both call the same builder, so the two front
ends can never drift on what a given action actually runs.

Guardrail: for the four actions that map onto a script's own --commit flag
(deploy, backup restore, dedupe, unlock-save), `*_cmd()`'s _confirm_commit
only re-prompts when interactive_menu=True -- typing `--commit` directly on
a command line is already a deliberate, explicit choice, so plain Typer use
never re-prompts. The TUI doesn't call _confirm_commit at all: it shows its
own modals.confirm.ConfirmModal *before* ever building a --commit argv, so
the "really commit?" step still always happens, just via a native dialog
instead of a terminal prompt.
"""

from __future__ import annotations

import sys

from rich.prompt import Confirm

from .paths import SCRIPTS
from .runner import run
from .ui import console

BASH = "bash"
PY = sys.executable


def _confirm_commit(action: str, *, commit: bool, interactive_menu: bool) -> bool:
    """Extra confirmation before a --commit run, reached only via the TUI.

    This sits on top of each script's own dry-run-by-default behaviour, never
    in place of it: even when this returns True, the wrapped script still
    makes its own decision about what --commit means and still refuses
    anything that doesn't look like a real Switch SD card.
    """
    if not commit or not interactive_menu:
        return True
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return True
    console.print()
    return Confirm.ask(
        f"[bold yellow]{action} -- this WRITES data. Really commit?[/bold yellow]",
        default=False,
    )


# --- build -------------------------------------------------------------

def build_argv(*, skip_fetch: bool = False) -> list[str]:
    argv = [BASH, str(SCRIPTS / "build.sh")]
    if skip_fetch:
        argv.append("--skip-fetch")
    return argv


def build_cmd(*, skip_fetch: bool = False) -> int:
    return run(build_argv(skip_fetch=skip_fetch))


# --- deploy --------------------------------------------------------------

def deploy_argv(
    *, profile: str = "roster", target: str | None = None, commit: bool = False, base_only: bool = False
) -> list[str]:
    argv = [BASH, str(SCRIPTS / "deploy.sh"), "--profile", profile]
    if target:
        argv += ["--target", target]
    if base_only:
        argv.append("--base-only")
    if commit:
        argv.append("--commit")
    return argv


def deploy_cmd(
    *,
    profile: str = "roster",
    target: str | None = None,
    commit: bool = False,
    base_only: bool = False,
    interactive_menu: bool = False,
) -> int:
    if not _confirm_commit(f"Deploy profile '{profile}'", commit=commit, interactive_menu=interactive_menu):
        console.print("[yellow]Cancelled -- nothing was written.[/yellow]")
        return 1
    return run(deploy_argv(profile=profile, target=target, commit=commit, base_only=base_only))


# --- backup ---------------------------------------------------------------

def backup_argv(
    *,
    mode: str = "archive",
    target: str | None = None,
    list_: bool = False,
    verify: str | None = None,
    restore: str | None = None,
    commit: bool = False,
    exact: bool = False,
) -> list[str]:
    argv = [BASH, str(SCRIPTS / "backup.sh")]
    if list_:
        argv.append("--list")
    elif verify:
        argv += ["--verify", verify]
    elif restore:
        argv += ["--restore", restore]
    else:
        argv += ["--mode", mode]
    if target:
        argv += ["--target", target]
    if exact:
        argv.append("--exact")
    if commit:
        argv.append("--commit")
    return argv


def backup_cmd(
    *,
    mode: str = "archive",
    target: str | None = None,
    list_: bool = False,
    verify: str | None = None,
    restore: str | None = None,
    commit: bool = False,
    exact: bool = False,
    interactive_menu: bool = False,
) -> int:
    # Only --restore --commit actually writes anything; creating or listing a
    # backup is always read-only on the card, so the extra guardrail only
    # fires for a restore.
    if restore and not _confirm_commit(
        f"Restore backup '{restore}' onto the SD card", commit=commit, interactive_menu=interactive_menu
    ):
        console.print("[yellow]Cancelled -- nothing was written.[/yellow]")
        return 1
    return run(
        backup_argv(mode=mode, target=target, list_=list_, verify=verify, restore=restore, commit=commit, exact=exact)
    )


# --- verify -----------------------------------------------------------------

def verify_argv(*, workspace: str | None = None, profile: str | None = None, strict: bool = False) -> list[str]:
    argv = [PY, str(SCRIPTS / "verify.py")]
    if workspace:
        argv += ["--workspace", workspace]
    if profile:
        argv += ["--profile", profile]
    if strict:
        argv.append("--strict")
    return argv


def verify_cmd(*, workspace: str | None = None, profile: str | None = None, strict: bool = False) -> int:
    return run(verify_argv(workspace=workspace, profile=profile, strict=strict))


# --- toggle -------------------------------------------------------------

def toggle_status_argv() -> list[str]:
    return [BASH, str(SCRIPTS / "toggle_mods.sh"), "status"]


def toggle_status_cmd() -> int:
    return run(toggle_status_argv())


def toggle_on_argv(glob: str) -> list[str]:
    return [BASH, str(SCRIPTS / "toggle_mods.sh"), "on", glob]


def toggle_on_cmd(glob: str) -> int:
    return run(toggle_on_argv(glob))


def toggle_off_argv(glob: str) -> list[str]:
    return [BASH, str(SCRIPTS / "toggle_mods.sh"), "off", glob]


def toggle_off_cmd(glob: str) -> int:
    return run(toggle_off_argv(glob))


def toggle_batch_argv(file: str, action: str) -> list[str]:
    return [BASH, str(SCRIPTS / "toggle_mods.sh"), "batch", file, action]


def toggle_batch_cmd(file: str, action: str) -> int:
    return run(toggle_batch_argv(file, action))


def toggle_plugins_off_argv(mods: list[str]) -> list[str]:
    return [BASH, str(SCRIPTS / "toggle_mods.sh"), "plugins-off", *mods]


def toggle_plugins_off_cmd(mods: list[str]) -> int:
    return run(toggle_plugins_off_argv(mods))


def toggle_plugins_on_argv(mods: list[str]) -> list[str]:
    return [BASH, str(SCRIPTS / "toggle_mods.sh"), "plugins-on", *mods]


def toggle_plugins_on_cmd(mods: list[str]) -> int:
    return run(toggle_plugins_on_argv(mods))


# --- curate -----------------------------------------------------------------
#
# json=True / write_ids=[...] are for the TUI's CurateReviewScreen: --json
# gets a clean machine-readable candidate list (progress still visible on
# stderr) instead of --report's human text, and --write-ids pins only the
# candidates the user actually selected instead of everything --write would.

def curate_movesets_argv(
    *, report: bool = False, write: bool = False, limit: int = 24, json: bool = False, write_ids=None
) -> list[str]:
    argv = [PY, str(SCRIPTS / "curate.py"), "--limit", str(limit)]
    if report:
        argv.append("--report")
    if write:
        argv.append("--write")
    if json:
        argv.append("--json")
    if write_ids:
        argv += ["--write-ids", ",".join(str(i) for i in write_ids)]
    return argv


def curate_movesets_cmd(*, report: bool = False, write: bool = False, limit: int = 24) -> int:
    return run(curate_movesets_argv(report=report, write=write, limit=limit))


def curate_skins_argv(
    *, report: bool = False, write: bool = False, limit: int = 0, json: bool = False, write_ids=None
) -> list[str]:
    argv = [PY, str(SCRIPTS / "curate_skins.py"), "--limit", str(limit)]
    if report:
        argv.append("--report")
    if write:
        argv.append("--write")
    if json:
        argv.append("--json")
    if write_ids:
        argv += ["--write-ids", ",".join(str(i) for i in write_ids)]
    return argv


def curate_skins_cmd(*, report: bool = False, write: bool = False, limit: int = 0) -> int:
    return run(curate_skins_argv(report=report, write=write, limit=limit))


def curate_nsfw_argv(*, report: bool = False, write: bool = False, json: bool = False, write_ids=None) -> list[str]:
    argv = [PY, str(SCRIPTS / "curate_nsfw.py")]
    if json:
        argv.append("--json")
    if write_ids:
        argv += ["--write-ids", ",".join(str(i) for i in write_ids)]
    if report:
        argv.append("--report")
    if write:
        argv.append("--write")
    return argv


def curate_nsfw_cmd(*, report: bool = False, write: bool = False) -> int:
    return run(curate_nsfw_argv(report=report, write=write))


# --- dedupe -------------------------------------------------------------

def dedupe_argv(*, layer: str, against: str = "roster", commit: bool = False) -> list[str]:
    argv = [PY, str(SCRIPTS / "dedupe_layer.py"), "--layer", layer, "--against", against]
    if commit:
        argv.append("--commit")
    return argv


def dedupe_cmd(*, layer: str, against: str = "roster", commit: bool = False, interactive_menu: bool = False) -> int:
    if not _confirm_commit(
        f"Dedupe layer '{layer}' against '{against}'", commit=commit, interactive_menu=interactive_menu
    ):
        console.print("[yellow]Cancelled -- nothing was written.[/yellow]")
        return 1
    return run(dedupe_argv(layer=layer, against=against, commit=commit))


# --- unlock-save --------------------------------------------------------

def unlock_save_argv(save: str, *, commit: bool = False) -> list[str]:
    argv = [PY, str(SCRIPTS / "unlock_save.py"), save]
    if commit:
        argv.append("--commit")
    return argv


def unlock_save_cmd(save: str, *, commit: bool = False, interactive_menu: bool = False) -> int:
    if not _confirm_commit(f"Unlock save '{save}'", commit=commit, interactive_menu=interactive_menu):
        console.print("[yellow]Cancelled -- nothing was written.[/yellow]")
        return 1
    return run(unlock_save_argv(save, commit=commit))


# --- create-profile ------------------------------------------------------

def create_profile_argv(
    name: str,
    *,
    description: str,
    layers: list[str] | None = None,
    selfcontained: str | None = None,
    base: bool = True,
) -> list[str]:
    argv = [PY, str(SCRIPTS / "profile_edit.py"), name, "--description", description]
    if selfcontained:
        argv += ["--selfcontained", selfcontained]
    else:
        argv += ["--layers", ",".join(layers or [])]
    if not base:
        argv.append("--no-base")
    return argv


def create_profile_cmd(
    name: str,
    *,
    description: str,
    layers: list[str] | None = None,
    selfcontained: str | None = None,
    base: bool = True,
) -> int:
    """Append a new profile to profiles.toml. Not commit-gated: unlike the SD
    card or a save file, profiles.toml is a git-tracked repo file, so a
    mistake here is a `git diff`/`git checkout` away from undone."""
    return run(create_profile_argv(name, description=description, layers=layers, selfcontained=selfcontained, base=base))


# --- move-mod --------------------------------------------------------------

def move_mod_argv(name: str, *, from_workspace: str, to_workspace: str) -> list[str]:
    return [PY, str(SCRIPTS / "move_mod.py"), name, "--from", from_workspace, "--to", to_workspace]


def move_mod_cmd(name: str, *, from_workspace: str, to_workspace: str) -> int:
    """Move a mod to a different workspace -- the actual lever for changing
    which profiles it's part of, since a profile is a composition of
    workspaces rather than a per-mod pick-list. Not commit-gated: workspaces/
    is regenerable from roster.toml + fetch.py/unpack.py, so this is a much
    lower-stakes mutation than the SD card or a save file."""
    return run(move_mod_argv(name, from_workspace=from_workspace, to_workspace=to_workspace))


def retarget_pending_mod_argv(name: str, *, to_workspace: str) -> list[str]:
    return [PY, str(SCRIPTS / "move_mod.py"), name, "--pending", "--to", to_workspace]


def retarget_pending_mod_cmd(name: str, *, to_workspace: str) -> int:
    """Change a not-yet-fetched roster.toml pick's target workspace. No file
    to move -- it hasn't been fetched -- so this only edits roster.toml."""
    return run(retarget_pending_mod_argv(name, to_workspace=to_workspace))


# --- create-workspace --------------------------------------------------------

def create_workspace_argv(name: str) -> list[str]:
    return [PY, str(SCRIPTS / "create_workspace.py"), name]


def create_workspace_cmd(name: str) -> int:
    """Create a new, empty workspace -- a category to move mods into and
    reference from a custom profile. Not commit-gated: it's an empty
    directory, trivially removable, regenerable, and never touches the SD
    card or an existing file."""
    return run(create_workspace_argv(name))
