#!/usr/bin/env python3
"""Safe, append-only edits to profiles.toml.

Mirrors roster_edit.py's discipline: never regex-patch bytes in an existing
table, only append a brand new `[name]` table as text, and refuse to write
anything that doesn't round-trip through tomllib first. A new profile always
starts `status = "untested"` -- the same rule every hand-authored profile in
this file follows until someone actually runs it on real hardware.

Usage:
    profile_edit.py NAME --description TEXT --layers roster,reskin
    profile_edit.py NAME --description TEXT --selfcontained hdr
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import tomllib

PROFILES = pathlib.Path(__file__).resolve().parent.parent / "profiles.toml"


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def add_profile(
    name: str,
    *,
    description: str,
    layers: list[str] | None = None,
    selfcontained: str | None = None,
    base: bool = True,
) -> bool:
    """Append a new profile. Returns False if `name` already exists."""
    txt = PROFILES.read_text() if PROFILES.exists() else ""
    existing = tomllib.loads(txt) if txt.strip() else {}
    if name in existing:
        return False

    lines = [f"[{name}]", f"description = {_toml_str(description)}"]
    if selfcontained:
        lines.append("base = false")
        lines.append(f"selfcontained = {_toml_str(selfcontained)}")
    else:
        lines.append(f"base = {'true' if base else 'false'}")
        layer_list = ", ".join(_toml_str(layer) for layer in (layers or []))
        lines.append(f"layers = [{layer_list}]")
    lines.append('status = "untested"')

    separator = "\n\n" if txt.rstrip() else ""
    new_txt = txt.rstrip("\n") + separator + "\n".join(lines) + "\n"
    tomllib.loads(new_txt)  # refuse to write anything that will not parse
    PROFILES.write_text(new_txt)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name")
    ap.add_argument("--description", required=True)
    ap.add_argument("--layers", help="Comma-separated workspace names, later wins.")
    ap.add_argument("--selfcontained", help="A single workspace that ships its own base stack.")
    ap.add_argument("--no-base", action="store_true", help="Don't install the pinned base stack.")
    args = ap.parse_args()

    layers = [l.strip() for l in args.layers.split(",") if l.strip()] if args.layers else None
    ok = add_profile(
        args.name,
        description=args.description,
        layers=layers,
        selfcontained=args.selfcontained,
        base=not args.no_base,
    )
    if not ok:
        print(f"profile '{args.name}' already exists", file=sys.stderr)
        return 1
    print(f"wrote profile '{args.name}' to {PROFILES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
