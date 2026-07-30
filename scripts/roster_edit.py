#!/usr/bin/env python3
"""Safe edits to roster.toml.

Hand-rolled regex edits to this file have broken it twice: once silently
failing to match (leaving a mod installed that was meant to be dropped), once
inserting a duplicate `exclude` key and producing invalid TOML. Both happened
because entries vary -- some carry `variant`, some carry comment blocks between
`name` and the keys.

So: operate on whole [[mod]] blocks, merge rather than insert, and verify the
result parses before writing.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

ROSTER = pathlib.Path(__file__).resolve().parent.parent / "roster.toml"


def add_excludes(name: str, paths: list[str],
                 workspace: str | None = None) -> bool:
    """Union `paths` into one mod's exclude list. Returns True if changed."""
    txt = ROSTER.read_text()
    blocks = re.split(r"(?=^\[\[mod\]\])", txt, flags=re.M)
    hit = False
    for bi, b in enumerate(blocks):
        m = re.search(r'^name = "([^"]+)"', b, flags=re.M)
        if not m or m.group(1) != name:
            continue
        # Layers reuse mod names deliberately (nsfw/Skin-Marth overrides
        # reskin/Skin-Marth), so a name alone is ambiguous.
        if workspace:
            w = re.search(r'^workspace = "([^"]+)"', b, flags=re.M)
            if not w or w.group(1) != workspace:
                continue
        lines = b.split("\n")
        idx = [i for i, l in enumerate(lines) if l.startswith("exclude = [")]
        existing: list[str] = []
        for i in idx:
            existing += re.findall(r'"([^"]+)"', lines[i])
        merged, seen = [], set()
        for x in existing + paths:
            if x not in seen:
                seen.add(x)
                merged.append(x)
        newline = "exclude = [" + ", ".join(f'"{x}"' for x in merged) + "]"
        if idx:
            lines[idx[0]] = newline
            for i in reversed(idx[1:]):
                del lines[i]
        else:
            lines.insert(m.string[:m.start()].count("\n") + 1, newline)
        blocks[bi] = "\n".join(lines)
        hit = True
        break
    if not hit:
        return False
    out = "".join(blocks)
    tomllib.loads(out)          # refuse to write anything that will not parse
    ROSTER.write_text(out)
    return True
