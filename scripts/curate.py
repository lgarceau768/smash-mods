#!/usr/bin/env python3
"""Survey GameBanana's moveset category and propose a roster.

Added-character movesets live in Gameplay > Movesets (category 3325). This
walks that index, filters out the ones that will waste your time, and emits a
roster.toml.

The filters encode what actually predicts whether a moveset works today:

  * still has a downloadable file (submissions get withdrawn)
  * not flagged obsolete by its author
  * updated recently enough to have been built against Smashline 2 -- mods
    built against the old smashline_hook crash alongside the current plugin,
    and this is a far better predictor than popularity

Nothing here is trusted blindly: whatever is selected still goes through
unpack.py and verify.py, which is what actually catches slot collisions.

Usage:
    curate.py --report                 # survey and print candidates
    curate.py --write --limit 24       # emit roster.toml
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.request
from pathlib import Path

from common import ROOT, Colors, err, info, ok, warn

UA = "Mozilla/5.0 (smash-mods build script)"
CATEGORY_MOVESETS = 3325
INDEX = ("https://gamebanana.com/apiv11/Mod/Index"
         "?_nPerpage=50&_nPage={page}&_sSort=Generic_MostLiked"
         "&_aFilters%5BGeneric_Category%5D={cat}")
PROFILE = "https://gamebanana.com/apiv11/Mod/{}/ProfilePage"

# Smashline 2 became the norm during 2024. Anything not touched since is a
# coin flip at best, and a boot loop at worst.
SMASHLINE2_ERA = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp()


def get(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def survey(category: int = CATEGORY_MOVESETS) -> list[dict]:
    """Walk every page of a category index."""
    out: list[dict] = []
    page = 1
    while True:
        data = get(INDEX.format(page=page, cat=category))
        recs = data.get("_aRecords", [])
        if not recs:
            break
        out += recs
        meta = data.get("_aMetadata", {})
        if meta.get("_bIsComplete", True) or len(out) >= meta.get("_nRecordCount", 0):
            break
        page += 1
        time.sleep(0.25)
    return out


def triage(records: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    keep, dropped = [], []
    for r in records:
        if not r.get("_bHasFiles"):
            dropped.append((r, "no downloadable file"))
            continue
        if r.get("_bIsObsolete"):
            dropped.append((r, "author flagged obsolete"))
            continue
        if r.get("_tsDateModified", 0) < SMASHLINE2_ERA:
            when = dt.datetime.fromtimestamp(
                r.get("_tsDateModified", 0), dt.timezone.utc).strftime("%Y-%m")
            dropped.append((r, f"stale ({when}), predates Smashline 2"))
            continue
        keep.append(r)
    return keep, dropped


def detail(mod_id: int) -> dict | None:
    try:
        prof = get(PROFILE.format(mod_id))
    except Exception as exc:
        warn(f"mod {mod_id}: lookup failed: {exc}")
        return None
    files = prof.get("_aFiles") or []
    if not files:
        return None
    f = files[0]
    return {
        "id": mod_id,
        "name": prof.get("_sName", f"mod-{mod_id}"),
        "version": prof.get("_sVersion", "") or "",
        "file": f["_sFile"],
        "url": f["_sDownloadUrl"],
        "md5": f.get("_sMd5Checksum", ""),
        "size": f.get("_nFilesize", 0),
    }


def slug(name: str) -> str:
    import re
    s = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or f"mod"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=24)
    ap.add_argument("--category", type=int, default=CATEGORY_MOVESETS)
    args = ap.parse_args()

    info(f"surveying GameBanana category {args.category} ...")
    records = survey(args.category)
    info(f"{len(records)} submissions")

    keep, dropped = triage(records)
    info(f"{len(keep)} viable, {len(dropped)} filtered out")

    if args.report:
        print()
        print(f"{Colors.BOLD}Filtered out{Colors.OFF}")
        for r, why in dropped[:40]:
            print(f"  {r['_idRow']:>7}  {r['_sName'][:44]:<44} {why}")
        if len(dropped) > 40:
            print(f"  ... and {len(dropped) - 40} more")
        print()
        print(f"{Colors.BOLD}Candidates (by likes){Colors.OFF}")
        for r in keep[:args.limit]:
            when = dt.datetime.fromtimestamp(
                r["_tsDateModified"], dt.timezone.utc).strftime("%Y-%m")
            print(f"  {r['_idRow']:>7}  likes={r['_nLikeCount']:>4}  "
                  f"updated={when}  {r['_sName']}")

    if not args.write:
        return 0

    chosen = keep[:args.limit]
    info(f"resolving download metadata for {len(chosen)} mods ...")
    entries = []
    for r in chosen:
        d = detail(r["_idRow"])
        if d:
            entries.append(d)
            ok(f"{d['name']} ({d['size'] // 1024}KB)")
        time.sleep(0.25)

    lines = [
        "# Curated added-character roster.",
        "#",
        "# Generated by scripts/curate.py from GameBanana's Movesets category,",
        "# filtered to submissions with a live download, not flagged obsolete,",
        "# and updated in the Smashline 2 era (2024+).",
        "#",
        "# md5 is pinned so a silently re-uploaded mod fails loudly at fetch time",
        "# rather than becoming a mystery crash on the console.",
        "#",
        "# Slot collisions between these are caught by scripts/verify.py after",
        "# unpacking -- that is the check that actually makes a roster this size",
        "# workable. Remove any entry to drop it from the build.",
        "",
    ]
    for e in entries:
        lines += [
            "[[mod]]",
            f'name = "{slug(e["name"])}"',
            f"gamebanana_id = {e['id']}",
            f'file = "{e["id"]}-{e["file"]}"',
            f'url = "{e["url"]}"',
            f'md5 = "{e["md5"]}"',
            f'workspace = "roster"',
            f'# {e["name"]}  ({e["size"] // 1024}KB)',
            "",
        ]
    (ROOT / "roster.toml").write_text("\n".join(lines))
    ok(f"wrote roster.toml with {len(entries)} mods")
    return 0


if __name__ == "__main__":
    sys.exit(main())
