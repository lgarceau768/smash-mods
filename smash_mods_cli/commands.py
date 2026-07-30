"""Plain functions backing every subcommand.

Each Typer command in main.py and each interactive-menu action in menu.py
calls one of these -- neither reimplements the other's logic. A function
here does exactly one thing: build the argv the equivalent hand-typed
`./scripts/...` invocation would use, run it, and return the exit code.

Guardrail: for the four subcommands that map onto a script's own --commit
flag (deploy, backup restore, dedupe, unlock-save), pass interactive_menu=True
only from menu.py. That is what makes _confirm_commit fire an *extra*
Confirm.ask specifically for the menu path -- typing `--commit` directly on a
command line is already a deliberate, explicit choice, so the direct
subcommands never re-prompt and never weaken the safety the underlying
scripts already have (dry-run unless --commit, in all cases).
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
    """Extra confirmation before a --commit run, reached only via the menu.

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

def build_cmd(*, skip_fetch: bool = False) -> int:
    argv = [BASH, str(SCRIPTS / "build.sh")]
    if skip_fetch:
        argv.append("--skip-fetch")
    return run(argv)


# --- deploy --------------------------------------------------------------

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
    argv = [BASH, str(SCRIPTS / "deploy.sh"), "--profile", profile]
    if target:
        argv += ["--target", target]
    if base_only:
        argv.append("--base-only")
    if commit:
        argv.append("--commit")
    return run(argv)


# --- backup ---------------------------------------------------------------

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
    return run(argv)


# --- verify -----------------------------------------------------------------

def verify_cmd(*, workspace: str | None = None, profile: str | None = None, strict: bool = False) -> int:
    argv = [PY, str(SCRIPTS / "verify.py")]
    if workspace:
        argv += ["--workspace", workspace]
    if profile:
        argv += ["--profile", profile]
    if strict:
        argv.append("--strict")
    return run(argv)


# --- toggle -------------------------------------------------------------

def toggle_status_cmd() -> int:
    return run([BASH, str(SCRIPTS / "toggle_mods.sh"), "status"])


def toggle_on_cmd(glob: str) -> int:
    return run([BASH, str(SCRIPTS / "toggle_mods.sh"), "on", glob])


def toggle_off_cmd(glob: str) -> int:
    return run([BASH, str(SCRIPTS / "toggle_mods.sh"), "off", glob])


def toggle_batch_cmd(file: str, action: str) -> int:
    return run([BASH, str(SCRIPTS / "toggle_mods.sh"), "batch", file, action])


def toggle_plugins_off_cmd(mods: list[str]) -> int:
    return run([BASH, str(SCRIPTS / "toggle_mods.sh"), "plugins-off", *mods])


def toggle_plugins_on_cmd(mods: list[str]) -> int:
    return run([BASH, str(SCRIPTS / "toggle_mods.sh"), "plugins-on", *mods])


# --- curate -----------------------------------------------------------------

def curate_movesets_cmd(*, report: bool = False, write: bool = False, limit: int = 24) -> int:
    argv = [PY, str(SCRIPTS / "curate.py"), "--limit", str(limit)]
    if report:
        argv.append("--report")
    if write:
        argv.append("--write")
    return run(argv)


def curate_skins_cmd(*, report: bool = False, write: bool = False, limit: int = 0) -> int:
    argv = [PY, str(SCRIPTS / "curate_skins.py"), "--limit", str(limit)]
    if report:
        argv.append("--report")
    if write:
        argv.append("--write")
    return run(argv)


def curate_nsfw_cmd(*, report: bool = False, write: bool = False) -> int:
    argv = [PY, str(SCRIPTS / "curate_nsfw.py")]
    if report:
        argv.append("--report")
    if write:
        argv.append("--write")
    return run(argv)


# --- dedupe -------------------------------------------------------------

def dedupe_cmd(*, layer: str, against: str = "roster", commit: bool = False, interactive_menu: bool = False) -> int:
    if not _confirm_commit(
        f"Dedupe layer '{layer}' against '{against}'", commit=commit, interactive_menu=interactive_menu
    ):
        console.print("[yellow]Cancelled -- nothing was written.[/yellow]")
        return 1
    argv = [PY, str(SCRIPTS / "dedupe_layer.py"), "--layer", layer, "--against", against]
    if commit:
        argv.append("--commit")
    return run(argv)


# --- unlock-save --------------------------------------------------------

def unlock_save_cmd(save: str, *, commit: bool = False, interactive_menu: bool = False) -> int:
    if not _confirm_commit(f"Unlock save '{save}'", commit=commit, interactive_menu=interactive_menu):
        console.print("[yellow]Cancelled -- nothing was written.[/yellow]")
        return 1
    argv = [PY, str(SCRIPTS / "unlock_save.py"), save]
    if commit:
        argv.append("--commit")
    return run(argv)
