#!/usr/bin/env python3
"""Create a new (empty) workspace.

A workspace is nothing more than a directory under workspaces/ -- there's no
separate registry anywhere else in scripts/ that needs to know about one
(common.list_workspaces() just scans the filesystem, and profiles.toml
references workspace names as plain strings). This exists purely so that
"I want a custom category of mods for a custom profile" doesn't require
reaching for a shell and mkdir by hand.

Usage:
    create_workspace.py NAME
"""

from __future__ import annotations

import argparse
import re
import sys

from common import WORKSPACES, ok

_VALID_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def create_workspace(name: str) -> bool:
    """Create workspaces/<name>/. Returns False if the name is invalid or
    already exists (never overwrites)."""
    if not _VALID_NAME.match(name):
        return False
    target = WORKSPACES / name
    if target.exists():
        return False
    target.mkdir(parents=True)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="Workspace name, e.g. my-custom-layer")
    args = ap.parse_args()

    if not _VALID_NAME.match(args.name):
        print(
            f"'{args.name}' isn't a valid workspace name -- use letters, digits, "
            "hyphens, or underscores, starting with a letter or digit.",
            file=sys.stderr,
        )
        return 1
    if (WORKSPACES / args.name).exists():
        print(f"workspace '{args.name}' already exists", file=sys.stderr)
        return 1

    create_workspace(args.name)
    ok(f"created empty workspace '{args.name}' -- move mods into it, or reference it from a profile")
    return 0


if __name__ == "__main__":
    sys.exit(main())
