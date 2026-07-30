"""The `smash-mods profiles` command: profiles.toml rendered as a Rich table.

Read-only, no subprocess. Uses scripts/common.py's load_profiles()/all_mods()
so this can never drift from what deploy.sh --profile list or verify.py
themselves see -- it is the same data, just presented nicer.
"""

from __future__ import annotations

from rich import box
from rich.table import Table

from .paths import SCRIPTS  # noqa: F401  (import side effect: puts scripts/ on sys.path)
from .ui import console

# Mirrors the thresholds scripts/verify.py's check_plugin_budget() enforces:
# measured on real hardware, ~33 chainloaded plugin.nro modules is the boot
# ceiling (nn::ro's 64-module-per-process cap, shared with the game's own
# code, Skyline, and the base plugins) and 30 is the safe margin once a match
# starts loading more modules. Kept as a local copy -- this command only
# depends on common.py, not verify.py -- rather than importing verify.py.
PLUGIN_BUDGET_WARN = 30
PLUGIN_BUDGET_ERROR = 33

STATUS_STYLE = {
    "working": "bold green",
    "untested": "yellow",
    "broken": "bold red",
}


def _profile_plugin_count(prof: dict, common) -> int:
    """Count mods with a plugin.nro across a profile's actual composition.

    Layered profiles: the union of their layers, later layers overwriting
    earlier ones by mod name -- same precedence stage_layered() applies when
    it copies, so the count matches what actually reaches the card.
    Self-contained profiles: every mod in their one workspace.
    """
    if prof.get("selfcontained"):
        mods = common.all_mods(prof["selfcontained"])
    else:
        chosen: dict[str, object] = {}
        for layer in prof.get("layers", []):
            for mod in common.all_mods(layer):
                chosen[mod.name] = mod
        mods = list(chosen.values())
    return sum(1 for m in mods if (m / "plugin.nro").is_file())


def _layer_summary(prof: dict) -> str:
    if prof.get("selfcontained"):
        return f"self-contained: {prof['selfcontained']}"
    layers = prof.get("layers", [])
    return "layers: " + ", ".join(layers) if layers else "-"


def _plugin_cell(n: int) -> str:
    if n > PLUGIN_BUDGET_ERROR:
        return f"[bold red]{n}[/bold red]"
    if n > PLUGIN_BUDGET_WARN:
        return f"[yellow]{n}[/yellow]"
    return f"[green]{n}[/green]"


def render_profiles_table() -> Table:
    import common  # scripts/common.py -- read-only helpers only

    profiles = common.load_profiles()

    table = Table(
        title="smash-mods profiles",
        box=box.ROUNDED,
        header_style="bold cyan",
        title_style="bold",
        expand=False,
    )
    table.add_column("Profile", style="bold")
    table.add_column("Description")
    table.add_column("Composition")
    table.add_column("Plugins", justify="right")
    table.add_column("Status")
    table.add_column("Tested on")

    for name, prof in sorted(profiles.items()):
        n_plugins = _profile_plugin_count(prof, common)
        status = prof.get("status", "untested")
        style = STATUS_STYLE.get(status, "yellow")
        table.add_row(
            name,
            prof.get("description", ""),
            _layer_summary(prof),
            _plugin_cell(n_plugins),
            f"[{style}]{status}[/{style}]",
            prof.get("tested_on") or "-",
        )

    return table


def profiles_cmd() -> int:
    """Render and print the profiles table. Returns an exit code (always 0)."""
    console.print(render_profiles_table())
    console.print(
        f"[dim]Plugins column: green ≤{PLUGIN_BUDGET_WARN}, "
        f"yellow {PLUGIN_BUDGET_WARN + 1}–{PLUGIN_BUDGET_ERROR}, "
        f"red >{PLUGIN_BUDGET_ERROR} (measured nn::ro chainload ceiling).[/dim]"
    )
    return 0
