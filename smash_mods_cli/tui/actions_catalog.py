"""Plain-English descriptions of every action the TUI can trigger.

Single source of truth for the "ACTIONS" nav section in HomeScreen -- one
place to keep an action's name and description in sync, instead of
duplicating text across a keybinding label and a form screen's own header.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionInfo:
    id: str
    label: str
    description: str
    writes_data: bool  # True if this action can ever write to disk/card (even if dry-run by default)


ACTIONS: list[ActionInfo] = [
    ActionInfo(
        "create-workspace",
        "Create workspace",
        "Add a new, empty workspace -- a category to move mods into (or target "
        "when curating/creating profiles) beyond the built-in roster/reskin/nsfw/"
        "etc. Needed before you can build a truly custom profile.",
        writes_data=True,
    ),
    ActionInfo(
        "create-profile",
        "Create profile",
        "Build a new profile: pick which workspaces to layer (or a single "
        "selfcontained one), see the resulting mod count and plugin budget live, "
        "and save it into profiles.toml.",
        writes_data=True,
    ),
    ActionInfo(
        "build",
        "Build",
        "Fetch, unpack, verify, and stage every profile from roster.toml. "
        "Run this after changing roster.toml, or before deploying for the first time.",
        writes_data=True,
    ),
    ActionInfo(
        "deploy",
        "Deploy",
        "Copy a staged profile onto the SD card. Dry run by default -- shows what "
        "would change without writing anything unless you turn Commit on.",
        writes_data=True,
    ),
    ActionInfo(
        "backup",
        "Backup",
        "Snapshot or restore the SD card's mods folder. Creating, listing, or "
        "verifying a backup never writes to the card; restoring does (dry run "
        "by default).",
        writes_data=True,
    ),
    ActionInfo(
        "verify",
        "Verify",
        "Lint a workspace or profile for mod-layout problems (bad paths, slot "
        "collisions, plugin budget) before staging or deploying it. Read-only, "
        "never writes anything.",
        writes_data=False,
    ),
    ActionInfo(
        "curate",
        "Curate",
        "Survey GameBanana for moveset/skin/NSFW picks, then review the results as "
        "a checklist (all selected by default) and pin just the ones you want into "
        "roster.toml. Still needs Build afterward to actually fetch them.",
        writes_data=True,
    ),
    ActionInfo(
        "toggle",
        "Toggle mods",
        "Instantly enable or disable mods already on the SD card by renaming "
        "their folder -- no re-deploy needed. Handy for bisecting crashes.",
        writes_data=True,
    ),
    ActionInfo(
        "dedupe",
        "Dedupe",
        "Remove files from a cosmetic layer (e.g. reskin) that a higher-priority "
        "layer (e.g. roster) already overrides, to save space and plugin budget. "
        "Dry run by default.",
        writes_data=True,
    ),
    ActionInfo(
        "unlock-save",
        "Unlock save",
        "Patch a save file so every fighter slot, including added characters, "
        "is unlocked and reachable in-game. Dry run by default.",
        writes_data=True,
    ),
]

ACTIONS_BY_ID = {a.id: a for a in ACTIONS}
