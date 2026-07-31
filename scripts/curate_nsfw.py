#!/usr/bin/env python3
"""Curate the `nsfw` layer: top adult-rated skin per fighter, where one exists.

Selection: per character subcategory, the highest-liked skin carrying an adult
content rating (GameBanana rates nudity/sexual content per submission; the
index exposes _bHasContentRatings and the profile page the rating names).

Each entry is written with the SAME mod name the reskin layer uses for that
fighter (Skin-<Character>). Profiles stack layers in order and a later layer
replaces a same-named mod wholesale, so `nsfw` cleanly swaps that fighter's
skin without file-level conflicts:

    [nsfw]  layers = ["roster", "reskin", "nsfw"]

Fighters with no adult-rated skin keep their reskin-layer look. Skins whose
top pick in the reskin layer is ALREADY the adult one are skipped (same id).

    curate_nsfw.py --report
    curate_nsfw.py --write
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

from common import ROOT, info, ok, warn

UA = "Mozilla/5.0 (smash-mods build script)"
SKINS_CATEGORY = 3330
SUBCATS = ("https://gamebanana.com/apiv11/Mod/Categories"
           "?_idCategoryRow={cat}&_sSort=a_to_z")
INDEX = ("https://gamebanana.com/apiv11/Mod/Index"
         "?_nPerpage=25&_nPage=1&_sSort=Generic_MostLiked"
         "&_aFilters%5BGeneric_Category%5D={cat}")
PROFILE = "https://gamebanana.com/apiv11/Mod/{}/ProfilePage"

RECENT = dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp()
ADULT_RE = re.compile(r"nud|sexual|adult|suggestive|skimpy", re.I)

SKIP_SUBCATS = {
    "Miscellaneous", "Multiple Characters", "All Characters", "Bosses",
    "Assist Trophies", "Pokémon (Summoned)", "Enemies", "Other",
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


def existing_ids() -> set[int]:
    """GameBanana ids already pinned anywhere in roster.toml."""
    try:
        with (ROOT / "roster.toml").open("rb") as fh:
            data = tomllib.load(fh)
    except OSError:
        return set()
    return {m["gamebanana_id"] for m in data.get("mod", []) if m.get("gamebanana_id")}


def adult_rating(mod_id: int) -> tuple[bool, str]:
    """Confirm via profile page that the rating is adult, not violence."""
    prof = get(PROFILE.format(mod_id))
    ratings = prof.get("_aContentRatings") or {}
    names = list(ratings.values()) if isinstance(ratings, dict) else list(ratings)
    joined = ", ".join(str(n) for n in names)
    return bool(ADULT_RE.search(joined)), joined


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true",
                     help="emit machine-readable candidate JSON instead of a human report (implies --report)")
    ap.add_argument("--write-ids", help="comma-separated GameBanana ids to write, instead of every viable pick")
    args = ap.parse_args()

    have = existing_ids()
    subs = [c for c in get(SUBCATS.format(cat=SKINS_CATEGORY))
            if c["_sName"] not in SKIP_SUBCATS and c.get("_nItemCount", 0) > 0]
    if not args.json:
        info(f"{len(subs)} character subcategories; {len(have)} ids already pinned")

    picks = []
    for i, sc in enumerate(subs, 1):
        # Progress goes to stderr (not suppressed in --json mode) so a caller
        # capturing stdout for the final JSON can still show live progress.
        print(f"\r  scanning {i}/{len(subs)}", end="", flush=True, file=sys.stderr)
        try:
            recs = get(INDEX.format(cat=sc["_idRow"])).get("_aRecords", [])
        except Exception as exc:
            if not args.json:
                warn(f"{sc['_sName']}: {exc}")
            continue
        for r in recs:
            if not r.get("_bHasFiles") or r.get("_bIsObsolete"):
                continue
            if r.get("_tsDateModified", 0) < RECENT:
                continue
            if not r.get("_bHasContentRatings"):
                continue
            if r["_idRow"] in have:
                break  # reskin layer already carries this exact (adult) skin
            try:
                is_adult, names = adult_rating(r["_idRow"])
            except Exception:
                continue
            time.sleep(0.15)
            if is_adult:
                picks.append({"character": sc["_sName"], "id": r["_idRow"],
                              "name": r["_sName"], "likes": r.get("_nLikeCount", 0),
                              "ratings": names})
                break
        time.sleep(0.15)
    print(file=sys.stderr)
    if not args.json:
        info(f"{len(picks)} fighters have an adult-rated skin not already pinned")

    if args.json:
        print(json.dumps(picks))
        return 0

    if args.report or not args.write:
        for p in picks:
            print(f"  {p['character']:<20} {p['likes']:>4}  {p['name'][:40]:<40} [{p['ratings']}]")
        if not args.write and not args.write_ids:
            return 0

    if args.write_ids:
        wanted = {int(x) for x in args.write_ids.split(",") if x.strip()}
        picks = [p for p in picks if p["id"] in wanted]

    lines = ["", "# ---- nsfw layer: adult-rated skin per fighter ----",
             "# Mod names intentionally MATCH the reskin layer's (Skin-<Char>) so the",
             "# nsfw layer swaps that fighter's skin wholesale via layer ordering.", ""]
    added = 0
    for p in picks:
        try:
            prof = get(PROFILE.format(p["id"]))
            files = prof.get("_aFiles") or []
            f = max(files, key=lambda x: x.get("_nFilesize", 0)) if files else None
            if not f or (f["_nFilesize"] < 65536 and re.search(r"read\s*me", f["_sFile"], re.I)):
                warn(f"{p['name']}: no usable payload, skipping")
                continue
        except Exception as exc:
            warn(f"{p['name']}: {exc}")
            continue
        time.sleep(0.15)
        lines += ["[[mod]]",
                  f'name = "Skin-{slug(p["character"])}"',
                  f"gamebanana_id = {p['id']}",
                  f'file = "{p["id"]}-{f["_sFile"]}"',
                  f'url = "{f["_sDownloadUrl"]}"',
                  f'md5 = "{f.get("_sMd5Checksum", "")}"',
                  'workspace = "nsfw"',
                  f'# {p["character"]}: {p["name"]}  [{p["ratings"]}]  ({f["_nFilesize"] // 1024}KB)',
                  ""]
        added += 1
    p = ROOT / "roster.toml"
    p.write_text(p.read_text() + "\n".join(lines))
    ok(f"appended {added} nsfw skins to roster.toml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
