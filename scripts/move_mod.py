#!/usr/bin/env python3
"""Move a mod between workspaces, keeping roster.toml's workspace field in sync.

A profile is a composition of workspaces (layers, or one selfcontained
workspace) -- there's no per-mod pick-list at the profile level, so the way
to actually change which profiles a mod is part of is to change which
workspace it lives in (e.g. move it out of `parked` into `roster`, or out of
`roster` into `parked` to pull it from every profile that layers `roster`).

Mirrors roster_edit.py's discipline for the roster.toml side: whole-[[mod]]-
block replace, verified with tomllib before writing -- never a byte-level
patch that could silently corrupt the file.

A pick that's in roster.toml but hasn't been fetched yet (no directory under
workspaces/ at all) has no file to move -- retarget_pending_mod() just
updates its `workspace` field, so it lands in the right place whenever Build
does fetch it.

Usage:
    move_mod.py NAME --from roster --to parked
    move_mod.py NAME --pending --to parked      # not fetched yet -- roster.toml only
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tomllib
from pathlib import Path

from common import ROOT, WORKSPACES, roster_entry

ROSTER = ROOT / "roster.toml"


def move_mod(dir_name: str, from_workspace: str, to_workspace: str) -> bool:
    """Move workspaces/<from>/<dir_name> to workspaces/<to>/<dir_name>.

    Returns False if the source doesn't exist or the destination already
    does (never overwrites). Updates roster.toml's matching entry, if any --
    a hand-placed mod with no roster.toml entry just moves, silently.
    """
    src = WORKSPACES / from_workspace / dir_name
    if not src.is_dir():
        return False
    dst = WORKSPACES / to_workspace / dir_name
    if dst.exists():
        raise FileExistsError(f"{dst} already exists -- refusing to overwrite")

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))

    entry = roster_entry(dir_name)
    if entry is not None:
        _update_roster_workspace(entry["name"], to_workspace)
    return True


def retarget_pending_mod(roster_name: str, to_workspace: str) -> bool:
    """Change a not-yet-fetched roster.toml pick's target workspace.

    No file to move -- there's nothing under workspaces/ for it yet -- so
    this only rewrites roster.toml's `workspace` field, exactly like the tail
    end of move_mod() does for an already-fetched mod.
    """
    return _update_roster_workspace(roster_name, to_workspace)


def _update_roster_workspace(roster_name: str, to_workspace: str) -> bool:
    """Rewrite one [[mod]] block's `workspace = "..."` line in roster.toml."""
    if not ROSTER.exists():
        return False
    txt = ROSTER.read_text()
    blocks = re.split(r"(?=^\[\[mod\]\])", txt, flags=re.M)
    for i, block in enumerate(blocks):
        m = re.search(r'^name = "([^"]+)"', block, flags=re.M)
        if not m or m.group(1) != roster_name:
            continue
        new_block, n = re.subn(
            r'^workspace = "[^"]*"', f'workspace = "{to_workspace}"', block, flags=re.M
        )
        if n == 0:
            # No existing workspace line to replace (shouldn't normally happen
            # for a real entry) -- leave the block alone rather than guess
            # where to insert one.
            return False
        blocks[i] = new_block
        out = "".join(blocks)
        tomllib.loads(out)  # refuse to write anything that will not parse
        ROSTER.write_text(out)
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="Mod's directory name, e.g. Skin-Marth")
    ap.add_argument("--from", dest="from_workspace", help="Omit with --pending (not fetched yet).")
    ap.add_argument("--to", dest="to_workspace", required=True)
    ap.add_argument(
        "--pending", action="store_true",
        help="This pick hasn't been fetched yet -- update roster.toml's workspace field only, no file to move.",
    )
    args = ap.parse_args()

    if args.pending:
        ok = retarget_pending_mod(args.name, args.to_workspace)
        if not ok:
            print(f"'{args.name}' not found in roster.toml", file=sys.stderr)
            return 1
        print(f"retargeted '{args.name}': now targets '{args.to_workspace}'")
        return 0

    if not args.from_workspace:
        print("--from is required unless --pending is set", file=sys.stderr)
        return 1

    try:
        ok = move_mod(args.name, args.from_workspace, args.to_workspace)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not ok:
        print(f"'{args.name}' not found in workspace '{args.from_workspace}'", file=sys.stderr)
        return 1
    print(f"moved '{args.name}': {args.from_workspace} -> {args.to_workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
