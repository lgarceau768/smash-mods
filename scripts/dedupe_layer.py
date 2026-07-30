#!/usr/bin/env python3
"""Resolve file conflicts between a cosmetic layer and the roster.

Two conflict classes show up once a big skin layer is stacked on the
added-character roster, and they need opposite treatment.

1. GLOBAL DATABASES. Files like ui/param/database/ui_chara_db.prc are single
   game-wide tables. Mods ship a FULL static copy containing only their own
   edit, so when nine skins each ship one, eight are discarded and ARCropolis
   prompts on boot. Worse, ui_chara_db.prc is exactly what The CSK Collection
   rewrites at runtime to register added characters -- a static replacement
   fighting that risks the roster.

   These are stripped from the cosmetic layer entirely. The cost is a skin's
   custom character-select name or series icon; the alternative is breaking 43
   added characters. CSK keeps managing the real table at runtime.

2. PLAIN OVERLAPS. Two mods legitimately shipping the same asset (a BGM track,
   a shared model). Here the ROSTER wins: an added character's theme is part of
   that character, while a skin's version of the same track is incidental.
   Within the cosmetic layer itself, the first owner in sorted order wins so the
   result is deterministic.

    dedupe_layer.py --layer reskin --against roster            # report
    dedupe_layer.py --layer reskin --against roster --commit
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from common import GAME_PATHS, WORKSPACES, all_mods, human, info, ok, warn

# Game-wide tables and config. Any mod shipping one is replacing the whole file.
GLOBAL_FILES = {
    "ui/param/database/ui_chara_db.prc",
    "ui/param/database/ui_series_db.prc",
    "ui/param/database/ui_bgm_db.prc",
    "ui/param/database/ui_layout_db.prc",
    "ui/param/database/ui_mii_hat_db.prc",
    "ui/param/database/ui_mii_body_db.prc",
    "ui/param/database/ui_stage_db.prc",
    "ui/message/msg_name.msbt",
    "ui/message/msg_menu.msbt",
    "sound/param/soundlabelinfo.sli",
    "sound/config/bgm_property.bin",
    "sound/bank/narration/vc_narration_characall.nus3bank",
    "sound/bank/narration/vc_narration_characall.nus3audio",
}

# Patch formats are merged by ARCropolis, so several mods may ship them safely.
PATCH_EXTS = {
    "prcx", "prcxml", "stdatx", "stdatxml", "stprmx", "stprmxml",
    "xmsbt", "patch3audio", "motdiff", "yml",
}


def mod_files(mod: Path) -> dict[str, Path]:
    out = {}
    for f in mod.rglob("*"):
        if not f.is_file():
            continue
        rp = str(f.relative_to(mod)).replace("\\", "/")
        if rp.split("/", 1)[0].lower() not in GAME_PATHS:
            continue
        if rp.rsplit(".", 1)[-1].lower() in PATCH_EXTS:
            continue
        out[rp] = f
    return out


def strip_inherited(layer_mods, roster_layer: str, commit: bool) -> int:
    """Remove motion/sound data a cosmetic layer writes into inherited slots.

    Added characters inherit cmn/camera/sound/bodymotion/motion from a vanilla
    slot of their host, almost always c00. A skin that also ships custom
    ANIMATIONS for that slot silently feeds them to every added character riding
    that host -- wrong animations, invisible models, or a crash.

    Model and texture files are untouched: those are never inherited, which is
    the whole reason a reskin layer is safe to stack on the roster in the first
    place. So the skin keeps its look and loses only the animation changes on
    the shared slot.
    """
    import json as _json
    import re as _re
    from common import VANILLA_SLOT_MAX

    INHERITED = ("cmn", "camera", "sound", "bodymotion", "motion")

    depends: dict[tuple[str, int], set[str]] = defaultdict(set)
    for mod in all_mods(roster_layer):
        cfg = mod / "config.json"
        if not cfg.is_file():
            continue
        try:
            data = _json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        except (ValueError, OSError):
            continue
        for src in (data.get("new-dir-infos-base") or {}).values():
            if isinstance(src, str) and (m := _re.match(r"fighter/([a-z0-9_]+)/c(\d+)", src)):
                if int(m.group(2)) <= VANILLA_SLOT_MAX:
                    depends[(m.group(1).lower(), int(m.group(2)))].add(mod.name)
    if not depends:
        return 0

    victims: list[Path] = []
    affected: dict[str, int] = defaultdict(int)
    for mod in layer_mods:
        for f in mod.rglob("*"):
            if not f.is_file():
                continue
            rp = str(f.relative_to(mod)).replace("\\", "/")
            m = (_re.match(r"fighter/([a-z0-9_]+)/([a-z]+)/.*?/c(\d+)/", rp)
                 or _re.match(r"fighter/([a-z0-9_]+)/([a-z]+)/c(\d+)/", rp))
            if not m:
                continue
            host, comp, slot = m.group(1).lower(), m.group(2), int(m.group(3))
            if slot > VANILLA_SLOT_MAX or comp not in INHERITED:
                continue
            if depends.get((host, slot)):
                victims.append(f)
                affected[mod.name] += 1

    if not victims:
        return 0
    freed = sum(f.stat().st_size for f in victims)
    print()
    info(f"{len(victims)} inherited-slot files in {len(affected)} mods "
         f"({human(freed)}) -- animations that would leak into added characters")
    for mod, n in sorted(affected.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>5}  {mod}")
    if commit:
        for f in victims:
            f.unlink(missing_ok=True)
        ok(f"stripped {len(victims)} inherited-slot files ({human(freed)})")
    return len(victims)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", required=True, help="cosmetic layer to trim")
    ap.add_argument("--against", default="roster", help="layer that wins")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    winners: dict[str, str] = {}
    for mod in all_mods(args.against):
        for rp in mod_files(mod):
            winners.setdefault(rp, mod.name)
    info(f"'{args.against}' owns {len(winners)} files")

    layer_mods = all_mods(args.layer)

    # For a duplicate inside the cosmetic layer, prefer the mod that owns more
    # of that fighter. Alphabetical order would hand fighter/packun/model/mario/
    # to Skin-Mario purely on the name, when those files belong to the Piranha
    # Plant reskin -- Piranha Plant just happens to use a Mario model internally.
    contrib: dict[tuple[str, str], int] = defaultdict(int)
    files_by_mod: dict[str, dict[str, Path]] = {}
    for mod in layer_mods:
        fm = mod_files(mod)
        files_by_mod[mod.name] = fm
        for rp in fm:
            parts = rp.split("/")
            if parts[0].lower() == "fighter" and len(parts) > 1:
                contrib[(mod.name, parts[1].lower())] += 1

    def owns_more(mod_name: str, rp: str) -> int:
        parts = rp.split("/")
        if parts[0].lower() == "fighter" and len(parts) > 1:
            return contrib.get((mod_name, parts[1].lower()), 0)
        return 0

    seen: dict[str, str] = {}
    to_remove: list[tuple[Path, str, str]] = []

    for mod in layer_mods:
        for rp, path in sorted(files_by_mod[mod.name].items()):
            if rp in GLOBAL_FILES:
                to_remove.append((path, mod.name, "global database"))
            elif rp in winners:
                to_remove.append((path, mod.name, f"owned by {winners[rp]}"))
            elif rp in seen:
                incumbent = seen[rp]
                if owns_more(mod.name, rp) > owns_more(incumbent, rp):
                    # This mod owns the fighter; evict the earlier claim.
                    prev = files_by_mod[incumbent].get(rp)
                    if prev is not None:
                        to_remove.append((prev, incumbent,
                                          f"duplicate of {mod.name}"))
                    seen[rp] = mod.name
                else:
                    to_remove.append((path, mod.name, f"duplicate of {incumbent}"))
            else:
                seen[rp] = mod.name

    strip_inherited(layer_mods, args.against, args.commit)

    if not to_remove:
        ok(f"'{args.layer}' has no file conflicts against '{args.against}'")
        return 0

    by_reason: dict[str, int] = defaultdict(int)
    by_mod: dict[str, int] = defaultdict(int)
    freed = 0
    for path, mod, reason in to_remove:
        key = reason if reason == "global database" else reason.split()[0]
        by_reason[key] += 1
        by_mod[mod] += 1
        freed += path.stat().st_size

    print()
    info(f"{len(to_remove)} files to remove ({human(freed)})")
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>5}  {reason}")
    print()
    info("most affected mods:")
    for mod, n in sorted(by_mod.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>5}  {mod}")

    if not args.commit:
        print()
        warn("dry run -- nothing removed. Re-run with --commit.")
        return 0

    for path, _, _ in to_remove:
        path.unlink(missing_ok=True)

    # Drop directories left empty, so the staged tree has no dead branches.
    pruned = 0
    for mod in layer_mods:
        for d in sorted(mod.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                pruned += 1

    print()
    ok(f"removed {len(to_remove)} files ({human(freed)}), pruned {pruned} empty dirs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
