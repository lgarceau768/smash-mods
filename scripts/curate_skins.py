#!/usr/bin/env python3
"""Curate one reskin per vanilla fighter, for the `reskin` layer.

GameBanana organises Skins (category 3330) into one subcategory per character,
93 of them. This picks the highest-rated recent skin from each, which is the
closest thing to a complete full-cast restyle -- no single pack covers all 89
fighters.

Reskins are safe to compose with the added-character roster: added characters
inherit cmn/camera/sound/bodymotion from their host's vanilla slot but never
model data, so replacing vanilla models and textures cannot reach them.
scripts/verify.py enforces that boundary.

    curate_skins.py --report            # survey and print the picks
    curate_skins.py --write             # append them to roster.toml
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from common import ROOT, Colors, err, info, ok, warn

UA = "Mozilla/5.0 (smash-mods build script)"
SKINS_CATEGORY = 3330
SUBCATS = ("https://gamebanana.com/apiv11/Mod/Categories"
           "?_idCategoryRow={cat}&_sSort=a_to_z")
INDEX = ("https://gamebanana.com/apiv11/Mod/Index"
         "?_nPerpage=20&_nPage=1&_sSort=Generic_MostLiked"
         "&_aFilters%5BGeneric_Category%5D={cat}")
PROFILE = "https://gamebanana.com/apiv11/Mod/{}/ProfilePage"

# Skins updated before this are likely built for an older game version.
RECENT = dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp()

# Subcategories that aren't a single playable fighter.
SKIP_SUBCATS = {
    "Miscellaneous", "Multiple Characters", "All Characters", "Bosses",
    "Assist Trophies", "Pokémon (Summoned)", "Enemies", "Other",
    # These leaked through on the first pass and are not single fighters.
    "Assist Trophies/Pokémon", "Custom Moveset Skins", "Items", "Packs",
    "Mii Hats", "Other/Misc", "Stages", "Music", "Effects", "UI",
}


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def slug(name: str) -> str:
    s = re.sub(r"\(.*?\)|\[.*?\]", "", name)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or "skin"


def roster_characters() -> set[str]:
    """Lowercased names of characters already installed as added fighters.

    A skin that turns Sonic into Shadow is pointless when Shadow is already on
    the roster as his own fighter -- you would meet him twice. Not a technical
    conflict, just redundant, so the next candidate is taken instead of dropping
    the fighter entirely.
    """
    import tomllib
    try:
        with (ROOT / "roster.toml").open("rb") as fh:
            data = tomllib.load(fh)
    except OSError:
        return set()
    out = set()
    for m in data.get("mod", []):
        if m.get("workspace") != "roster":
            continue
        stem = re.sub(r"-(Moveset|Movesets|Smash)$", "", m.get("name", ""),
                     flags=re.I)
        stem = stem.replace("-", " ").strip().lower()
        if stem and len(stem) > 3:
            out.add(stem)
    return out


def pick_for(subcat: dict, avoid: set[str]) -> dict | None:
    """Highest-rated viable skin in one character's subcategory."""
    try:
        data = get(INDEX.format(cat=subcat["_idRow"]))
    except Exception as exc:
        warn(f"{subcat['_sName']}: index failed ({exc})")
        return None
    for r in data.get("_aRecords", []):
        if not r.get("_bHasFiles") or r.get("_bIsObsolete"):
            continue
        if r.get("_tsDateModified", 0) < RECENT:
            continue
        low = r["_sName"].lower()
        if any(a in low for a in avoid):
            continue          # already on the roster as its own fighter
        return {"character": subcat["_sName"], "id": r["_idRow"],
                "name": r["_sName"], "likes": r.get("_nLikeCount", 0),
                "updated": dt.datetime.fromtimestamp(
                    r["_tsDateModified"], dt.timezone.utc).strftime("%Y-%m")}
    return None


def resolve(pick: dict) -> dict | None:
    """Largest file for a pick -- never _aFiles[0], which is often a readme."""
    try:
        prof = get(PROFILE.format(pick["id"]))
    except Exception as exc:
        warn(f"{pick['name']}: lookup failed ({exc})")
        return None
    files = prof.get("_aFiles") or []
    if not files:
        return None
    f = max(files, key=lambda x: x.get("_nFilesize", 0))
    if f.get("_nFilesize", 0) < 64 * 1024 and re.search(r"read\s*me", f["_sFile"], re.I):
        warn(f"{pick['name']}: only a readme is hosted here, skipping")
        return None
    return {**pick, "file": f["_sFile"], "url": f["_sDownloadUrl"],
            "md5": f.get("_sMd5Checksum", ""), "size": f.get("_nFilesize", 0)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="cap the fighter count")
    args = ap.parse_args()

    info("listing character subcategories ...")
    subs = [c for c in get(SUBCATS.format(cat=SKINS_CATEGORY))
            if c["_sName"] not in SKIP_SUBCATS and c.get("_nItemCount", 0) > 0]
    if args.limit:
        subs = subs[:args.limit]
    info(f"{len(subs)} character subcategories")

    avoid = roster_characters()
    info(f"avoiding {len(avoid)} characters already on the roster")
    picks = []
    for i, sc in enumerate(subs, 1):
        p = pick_for(sc, avoid)
        if p:
            picks.append(p)
        print(f"\r  scanned {i}/{len(subs)}", end="", flush=True)
        time.sleep(0.15)
    print()
    info(f"{len(picks)} fighters have a viable recent skin")

    if args.report:
        print()
        for p in picks:
            print(f"  {p['character']:<22} {p['likes']:>4} likes  "
                  f"{p['updated']}  {p['name'][:44]}")
        missing = {s["_sName"] for s in subs} - {p["character"] for p in picks}
        if missing:
            print()
            warn(f"no viable skin found for {len(missing)}: "
                 f"{', '.join(sorted(missing))}")

    if not args.write:
        return 0

    info("resolving downloads ...")
    resolved = []
    total = 0
    for i, p in enumerate(picks, 1):
        r = resolve(p)
        if r:
            resolved.append(r)
            total += r["size"]
        print(f"\r  resolved {i}/{len(picks)}", end="", flush=True)
        time.sleep(0.15)
    print()

    lines = ["", "# ---- reskin layer: one skin per vanilla fighter ----",
             "# Generated by scripts/curate_skins.py. Model/texture replacements",
             "# only, which is why this composes safely with the added-character",
             "# roster (added characters never inherit model data).", ""]
    for r in resolved:
        lines += [
            "[[mod]]",
            f'name = "Skin-{slug(r["character"])}"',
            f"gamebanana_id = {r['id']}",
            f'file = "{r["id"]}-{r["file"]}"',
            f'url = "{r["url"]}"',
            f'md5 = "{r["md5"]}"',
            'workspace = "reskin"',
            f'# {r["character"]}: {r["name"]}  ({r["size"] // 1024}KB)',
            "",
        ]
    p = ROOT / "roster.toml"
    p.write_text(p.read_text() + "\n".join(lines))
    ok(f"appended {len(resolved)} skins to roster.toml "
       f"({total / 1024**3:.1f} GB to download)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
