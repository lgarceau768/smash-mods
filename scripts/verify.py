#!/usr/bin/env python3
"""Lint a workspace before anything is written to the SD card.

Everything here exists because the corresponding failure is invisible until the
console black-screens, with no diagnostics and no obvious culprit among thirty
installed mods. Catching it on the PC is the whole point of this repo.

The headline check is slot collision. Added characters are not new fighters
internally -- each one rides a host fighter's extra costume slot (c08 and up;
c00-c07 are vanilla). Two mods claiming the same (fighter, slot) will load one
and corrupt or crash the other, and nothing in the install process warns you.

Usage:
    verify.py [--workspace roster] [--strict]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from common import (
    ALLOWED_ROOT_FILES, die, CSS_EXPANDED_LIMIT, DISPLAY_ALIASES, FAT32_ILLEGAL,
    GAME_PATHS,
    JUNK_NAMES, KNOWN_FIGHTERS, VANILLA_SLOT_MAX, WORKSPACES, Colors,
    all_mods, err, info, ok, warn,
)

# fighter/<name>/.../c<NN>/...  and  ui/.../chara_<n>_<name>_<NN>...
#
# The middle segment group is optional: slot dirs appear both deep
# (fighter/mario/model/body/c08/) and directly under the fighter
# (fighter/koopa/c08/). Requiring an intermediate segment silently missed the
# shallow form, which would let a real collision through undetected.
# Slot numbers are NOT two digits. The community's default landing block for
# added characters is c120-c127, and the roster also uses c95-c135. An earlier
# `c(\d{2})` silently matched none of them -- 57% of real claims were invisible,
# including every mod in the c120 block, which is exactly where a collision is
# most likely. Case-sensitive on purpose: the console's lookups are, so
# `fighter/Mario/` is a real bug we must not normalise away (see check_case).
SLOT_RE = re.compile(r"(?:^|/)fighter/([a-z0-9_]+)(?:/.*?)?/c(\d+)(?:/|$)")

# UI asset names, e.g. ui/replace/chara/chara_1/chara_1_sans_120.bntx.
# The trailing boundary matters: without it, a greedy name group let
# chara_1_palutena_128 parse as slot "12", collapsing 120 and 128 into one.
UI_CHARA_RE = re.compile(
    r"(?:^|/)ui/.*?chara_(\d)_([a-z0-9_]+?)_(\d{2,3})(?=\.|_|$)", re.I)

# Files ARCropolis merges rather than conflicts on: it applies a list of patches
# onto the vanilla base, so many mods can touch one of these safely.
PATCH_EXTS = {
    "prcx", "prcxml", "stdatx", "stdatxml", "stprmx", "stprmxml",
    "xmsbt", "patch3audio", "motdiff", "yml",
}
# Mod-root metadata, not game assets -- every mod legitimately has these.
ROOT_META = {"info.toml", "config.json", "plugin.nro", "preview.webp"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def rel_paths(mod: Path) -> list[str]:
    return [str(p.relative_to(mod)) for p in mod.rglob("*") if p.is_file()]


def check_structure(mod: Path, rep: Report) -> None:
    """Immediate children must be game paths -- catches leftover nesting."""
    for child in mod.iterdir():
        if child.is_dir():
            # OS junk is reported by check_filenames as a warning. Flagging it
            # here too would diagnose it as a nesting problem and point at the
            # wrong fix.
            if child.name in JUNK_NAMES or child.name.startswith("._"):
                continue
            if child.name.lower() not in GAME_PATHS:
                rep.error(
                    f"{mod.name}: unrecognised top-level directory '{child.name}/'\n"
                    f"    ARCropolis will ignore this mod entirely.\n"
                    f"    Expected a game path (fighter/, ui/, sound/, effect/, ...).\n"
                    f"    Usually means the archive was nested one level too deep."
                )
        elif child.name in JUNK_NAMES or child.name.startswith("._"):
            rep.warning(f"{mod.name}: OS junk at mod root: {child.name}")


CONFIG_DIR_RE = re.compile(r"^fighter/([a-z0-9_]+)/(?:.*/)?c(\d+)$", re.I)


def claims_from_config(mod: Path) -> set[tuple[str, int]]:
    """Authoritative slot claims, read from the mod's own config.json.

    This is the source that matters. An added character does NOT get a new
    fighter ID -- it registers extra costume slots on an existing host fighter,
    and declares them in config.json's "new-dir-infos":

        Waluigi -> fighter/dolly/c120..   (Terry)
        Sans    -> fighter/palutena/c120..
        Silver  -> fighter/mewtwo/c128..

    The mod's files live under its OWN directory name (fighter/waluigi/,
    fighter/sans/), which is why scanning file paths finds the wrong namespace
    entirely and would miss every genuine conflict. Slots are routinely three
    digits, well past the c00-c99 the on-disk layout suggests.
    """
    cfg = mod / "config.json"
    if not cfg.is_file():
        return set()
    try:
        data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return set()
    out: set[tuple[str, int]] = set()
    for entry in data.get("new-dir-infos", []):
        if isinstance(entry, str) and (m := CONFIG_DIR_RE.match(entry.strip())):
            out.add((m.group(1).lower(), int(m.group(2))))
    return out


def collect_slots(mod: Path) -> tuple[set[tuple[str, int]], set[str], str]:
    """Return (host, slot) claims, fighter dirs referenced, and the source used."""
    # Only real fighter/ directories count as fighter names. UI asset filenames
    # (chara_1_sans_120.bntx) carry the *character's* display id, not a fighter
    # directory -- feeding those in produced a bogus "40 added fighter
    # directories" list full of texture variants like tetrisblue and
    # gogeta_ss4_lb, and two false typo warnings.
    fighters: set[str] = set()
    for rp in rel_paths(mod):
        norm = rp.replace("\\", "/")
        for m in SLOT_RE.finditer(norm):
            fighters.add(m.group(1))

    if (declared := claims_from_config(mod)):
        return declared, fighters, "config.json"

    # Fallback for mods with no config.json -- costume/model replacements that
    # write vanilla slots directly. Here the on-disk path IS the claim.
    claims: set[tuple[str, int]] = set()
    for rp in rel_paths(mod):
        norm = rp.replace("\\", "/")
        for m in SLOT_RE.finditer(norm):
            claims.add((m.group(1).lower(), int(m.group(2))))
        for m in UI_CHARA_RE.finditer(norm):
            claims.add((m.group(2).lower(), int(m.group(3))))
    return claims, fighters, "paths"


def check_collisions(mods: list[Path], rep: Report) -> dict:
    """The main event: two mods claiming one costume slot."""
    owners: dict[tuple[str, int], list[str]] = defaultdict(list)
    all_fighters: set[str] = set()
    added_slots = 0
    added_chars = 0
    by_source: dict[str, int] = defaultdict(int)

    declared_by: dict[tuple[str, int], set[str]] = defaultdict(set)
    for mod in mods:
        claims, fighters, source = collect_slots(mod)
        by_source[source] += 1
        if source == "config.json":
            added_chars += 1
        all_fighters |= fighters
        for claim in claims:
            owners[claim].append(mod.name)
            if source == "config.json":
                declared_by[claim].add(mod.name)

    for (fighter, slot), mod_names in sorted(owners.items()):
        # A VANILLA slot (c00-c07) is shared territory. Several mods routinely
        # touch the same one via different sub-paths and that is correct, not a
        # conflict: Kirby's c00 carries a copy-ability hat per character, so the
        # Dr. Mario, Hero and Ike skins each update their own hat there; a
        # moveset writes motion/ while a skin writes model/. Genuine overlap on
        # a vanilla slot means the SAME FILE twice, which check_file_conflicts
        # already catches precisely.
        #
        # An ADDED slot is different: it represents one registered character, so
        # two claimants is always wrong. Likewise two mods both DECLARING the
        # same slot in config.json, at any index.
        exclusive = slot > VANILLA_SLOT_MAX or len(declared_by.get((fighter, slot), ())) > 1
        if len(mod_names) > 1 and exclusive:
            listing = "\n".join(f"      claimed by: {n}" for n in sorted(mod_names))
            rep.error(
                f"COLLISION  fighter/{fighter} slot c{slot:02d}\n{listing}\n"
                f"    Both mods write the same costume slot. One will be "
                f"silently overwritten; the other may crash the game.\n"
                f"    Fix: re-slot one of them, or drop it from the roster."
            )
        if slot > VANILLA_SLOT_MAX:
            added_slots += 1

    # An unknown fighter directory is the NORMAL case for a Smashline 2 added
    # character -- they genuinely create their own (silver/, waluigi/, kuribo/
    # for Goomba, naruhodo/ for Phoenix Wright). Warning on all of them buries
    # the real signal under noise.
    #
    # A typo, by contrast, lands very close to a real internal name. So only
    # flag names within edit distance 1 of a known fighter, and merely count
    # the rest.
    import difflib
    added_fighters = []
    for fighter in sorted(all_fighters):
        if fighter in KNOWN_FIGHTERS:
            continue
        # Display name used in place of the internal one -- silent no-op, and
        # lexically too far from the real name for edit distance to catch.
        if (internal := DISPLAY_ALIASES.get(fighter.replace("_", ""))):
            rep.error(
                f"fighter directory '{fighter}' is a display name, not an "
                f"internal name -- the internal name is '{internal}'.\n"
                f"    The game will never look under '{fighter}/', so this mod "
                f"loads nothing at all."
            )
            continue
        near = difflib.get_close_matches(fighter, KNOWN_FIGHTERS, n=1, cutoff=0.85)
        if near:
            rep.warning(
                f"fighter directory '{fighter}' is suspiciously close to "
                f"'{near[0]}' -- if it is a typo the mod silently loads nothing"
            )
        else:
            added_fighters.append(fighter)
    if added_fighters:
        rep.note(f"{len(added_fighters)} added fighter directories: "
                 f"{', '.join(added_fighters)}")

    # The real engine constraint is per-fighter: a host's costume index cannot
    # exceed 255. Summing added slots across all fighters and comparing that to
    # a per-fighter cap, as this used to, compares two unrelated quantities.
    worst = {}
    for (fighter, slot) in owners:
        worst[fighter] = max(worst.get(fighter, 0), slot)
    for fighter, hi in sorted(worst.items()):
        if hi > 255:
            rep.error(
                f"fighter/{fighter} uses slot c{hi}, above the 255 per-fighter "
                f"costume ceiling."
            )

    # Total added characters is a soft, memory-bound limit rather than a hard
    # cap. Reported envelope is ~46 working / ~55 breaking, and load times grow
    # sharply well before that.
    if added_chars > 40:
        rep.warning(
            f"{added_chars} added characters. Community reports put the working "
            f"envelope near 46 and failure near 55, with boot/load times of "
            f"several minutes at this scale. Expect slow loads and test in "
            f"small batches."
        )

    return {"claims": owners, "added_slots": added_slots,
            "fighters": all_fighters, "added_chars": added_chars,
            "by_source": dict(by_source)}


def check_added_char_payload(mods: list[Path], rep: Report) -> None:
    """An added character is code + data. Catch the data arriving without it.

    Added-character mods ship plugin.nro (the Smashline moveset code) and
    config.json (the fighter definition) at the mod root. If the models and
    animations land on the card without them, the character exists visually and
    does nothing -- or crashes. An earlier version of unpack.py dropped exactly
    these two files, so this is a standing regression guard.
    """
    for mod in mods:
        names = {c.name for c in mod.iterdir() if c.is_file()}
        has_code = "plugin.nro" in names
        has_conf = "config.json" in names
        if has_conf and not has_code:
            # Advisory only. config.json is NOT exclusive to movesets: skins use
            # it for unshare-blacklist / new-dir-files so each costume slot can
            # own its model animation, and those legitimately ship no code.
            # The real regression guard lives in unpack.py, which knows what the
            # archive contained and errors if a plugin.nro went missing.
            rep.warning(
                f"{mod.name}: config.json but no plugin.nro. Fine for a skin "
                f"(unshare/new-dir-files); a problem only if this is a moveset."
            )
        elif has_code and not has_conf:
            rep.warning(
                f"{mod.name}: plugin.nro present but no config.json -- "
                f"verify the mod is complete"
            )


# Binary game formats that are NEVER legitimately zero bytes -- each has a
# header, so an empty one means data was lost.
#
# Deliberately an allowlist of *dangerous* extensions rather than a list of safe
# ones. Mods use arbitrary extensions for zero-byte slot flags by convention
# (sans.marker, sonic.modern, phoenix.wright, alt_maya.wright), all declared as
# empty in their archives. Chasing those names is a losing game; naming the
# handful of real binary formats is not. unpack.py already guarantees no bytes
# were lost by reconciling against the archive's declared total, so this is a
# targeted backstop, not the primary defence.
BINARY_ASSET_EXTS = (
    ".nus3bank", ".nus3audio", ".idsp", ".lopus", ".sli",      # audio
    ".bntx", ".numdlb", ".numshb", ".nusktb", ".numatb",       # models/ui
    ".nuanmb", ".arc", ".prc", ".eff", ".nutexb", ".msbt",     # anim/param/vfx
)


def check_empty_files(mods: list[Path], rep: Report) -> None:
    """Zero-byte game assets -- data lost between archive and workspace.

    This is what actually broke on console: `unar` silently zeroed ~15% of the
    files in the RAR-packaged mods, and The CSK Collection panicked trying to
    read a 16-byte header out of a 0-byte nus3bank:

        _csk_collection panicked at src/api/audio.rs:335
        range start index 16 out of range for slice of length 0

    unpack.py now validates extracted bytes against the archive's declared
    total, so this should never fire again. It stays as a backstop because the
    staged tree is what reaches the card, and a silent zero here is
    indistinguishable on console from a mod that simply crashes.
    """
    AUDIO = (".nus3bank", ".nus3audio", ".idsp", ".sli", ".lopus")
    for mod in mods:
        empties = [rp for rp in rel_paths(mod)
                   if rp.lower().endswith(BINARY_ASSET_EXTS)
                   and (mod / rp).stat().st_size == 0]
        if not empties:
            continue
        audio = [e for e in empties if e.endswith(AUDIO)]
        detail = "\n".join(f"      {e}" for e in sorted(empties)[:6])
        more = f"\n      ... and {len(empties) - 6} more" if len(empties) > 6 else ""
        if audio:
            rep.error(
                f"{mod.name}: {len(empties)} zero-byte file(s), including "
                f"{len(audio)} audio file(s).\n{detail}{more}\n"
                f"    A 0-byte nus3bank makes The CSK Collection panic on boot.\n"
                f"    Re-unpack this mod -- the extractor lost data."
            )
        else:
            rep.error(
                f"{mod.name}: {len(empties)} zero-byte game asset(s).\n"
                f"{detail}{more}\n    The extractor lost data; re-unpack."
            )


# Components an added character inherits from its host's vanilla slot via
# config.json "new-dir-infos-base". Measured across the real roster: every one
# of 29 added characters inherits some of these, and NONE inherits model/.
INHERITED_COMPONENTS = ("cmn", "camera", "sound", "bodymotion", "motion")


def check_vanilla_base_conflicts(mods: list[Path], rep: Report) -> None:
    """A mod overwriting a vanilla slot that added characters inherit from.

    Added characters do not copy their host's whole costume -- they inherit
    specific components (cmn, camera, sound, bodymotion) from a vanilla slot,
    almost always c00, and declare it in new-dir-infos-base.

    So the two cases differ sharply, which is worth being precise about:

      * A RESKIN of a vanilla slot (model/, textures) is harmless. No added
        character inherits model data.
      * A MOVESET or animation pack on that slot IS a problem. The added
        character silently inherits the modified animations and can end up
        with wrong motion, invisible models, or a crash.

    This is why Sonic Re-Imagined's vanilla-slot variant endangered Tails and
    Knuckles while a cel-shade pack would not.
    """
    # Which (host, vanilla slot) does each mod depend on?
    depends: dict[tuple[str, int], set[str]] = defaultdict(set)
    for mod in mods:
        cfg = mod / "config.json"
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            continue
        for src in (data.get("new-dir-infos-base") or {}).values():
            if not isinstance(src, str):
                continue
            if (m := re.match(r"fighter/([a-z0-9_]+)/c(\d+)", src)):
                if int(m.group(2)) <= VANILLA_SLOT_MAX:
                    depends[(m.group(1).lower(), int(m.group(2)))].add(mod.name)

    if not depends:
        return

    # Which mods write inherited components into those same vanilla slots?
    for mod in mods:
        for rp in rel_paths(mod):
            norm = rp.replace("\\", "/")
            m = re.match(r"fighter/([a-z0-9_]+)/([a-z]+)/.*?/c(\d+)/", norm) \
                or re.match(r"fighter/([a-z0-9_]+)/([a-z]+)/c(\d+)/", norm)
            if not m:
                continue
            host, comp, slot = m.group(1).lower(), m.group(2), int(m.group(3))
            if slot > VANILLA_SLOT_MAX or comp not in INHERITED_COMPONENTS:
                continue
            victims = depends.get((host, slot), set()) - {mod.name}
            if victims:
                rep.error(
                    f"{mod.name} writes '{comp}' into fighter/{host} c{slot:02d}, "
                    f"which {len(victims)} added character(s) inherit from:\n"
                    + "\n".join(f"      {v}" for v in sorted(victims)) + "\n"
                    f"    They will silently inherit the modified {comp} data -- "
                    f"expect wrong animations, invisible models, or a crash.\n"
                    f"    Reskins (model/, textures) are safe here; motion and "
                    f"sound are not. Use a variant that avoids c{slot:02d}."
                )
                # Move to the next mod, but keep scanning the rest. An early
                # `return` here exited the whole check after the first hit, so
                # each rebuild surfaced exactly one more violation instead of
                # the full set -- five separate round trips for one problem.
                break


# Measured on hardware (13.0.4, Erista): 29 mod plugins boot and play; the
# 34th chainload call dies, twice, with different mods at that index. Cause:
# ARCropolis chainloader.rs loads each mod plugin.nro via nn::ro::LoadModule,
# and the OS caps loaded NRO modules per process at 64 -- shared with the
# game's own modules, Skyline, the 6 base plugins, AND the lua2cpp fighter
# modules the game loads when a match starts. Boot-time headroom is therefore
# not optional: sitting at the boot ceiling crashes on entering a match.
PLUGIN_BUDGET_WARN = 30
PLUGIN_BUDGET_ERROR = 33


def check_plugin_budget(mods: list[Path], rep: Report) -> None:
    """Count chainloaded plugin.nro files against the nn::ro module cap."""
    with_plugin = [m.name for m in mods if (m / "plugin.nro").is_file()]
    n = len(with_plugin)
    if n > PLUGIN_BUDGET_ERROR:
        rep.error(
            f"{n} mods ship plugin.nro -- past the measured chainload ceiling "
            f"(~{PLUGIN_BUDGET_ERROR}). The {PLUGIN_BUDGET_ERROR + 1}th dies at "
            f"boot regardless of which mod it is (nn::ro 64-module cap).\n"
            f"    Reduce plugin-bearing mods, or use a pack with a merged plugin."
        )
    elif n > PLUGIN_BUDGET_WARN:
        rep.warning(
            f"{n} mods ship plugin.nro. Boot works up to ~33 but the game loads "
            f"more modules when a match starts; {PLUGIN_BUDGET_WARN} is the "
            f"known-safe ceiling with headroom."
        )
    rep.note(f"{n} chainloaded plugins (budget: warn>{PLUGIN_BUDGET_WARN}, "
             f"error>{PLUGIN_BUDGET_ERROR})")


# Files The CSK Collection mutates at runtime to register added characters.
# Shipping a RAW replacement of one clobbers CSK's work; the .prcx/.prcxml patch
# forms are fine because ARCropolis merges those onto the vanilla base.
CSK_MANAGED = {
    "ui/param/database/ui_chara_db.prc": "the character-select database",
    "ui/param/database/ui_chara_layout_db.prc": "the CSS layout database",
    "ui/param/database/ui_series_db.prc": "the series database",
    "sound/param/soundlabelinfo.sli": "the sound label table",
}


def check_csk_managed(mods: list[Path], rep: Report,
                      allow: bool = False) -> None:
    """Raw replacement of a file The CSK Collection writes at runtime.

    This is not theoretical. The "Majin Android 21" Mewtwo skin ships a full
    sound/param/soundlabelinfo.sli. CSK appends tone entries to that file for
    every added character, and given a replacement that lacks its expected
    structure it reads a 16-byte header out of nothing:

        _csk_collection panicked at src/api/audio.rs:335
        range start index 16 out of range for slice of length 0

    The fix is to drop the raw file from the mod -- the skin's models and
    textures are unaffected, and the database entries it wanted are what CSK is
    generating anyway.
    """
    if allow:
        return
    for mod in mods:
        for rel, what in CSK_MANAGED.items():
            if not (mod / rel).is_file():
                continue
            patched = any((mod / (rel + ext)).is_file() or
                          (mod / rel).with_suffix(ext).is_file()
                          for ext in (".prcx", ".prcxml"))
            rep.error(
                f"{mod.name} ships a RAW {rel}\n"
                f"    That file is {what}, which The CSK Collection rewrites at "
                f"runtime to register added characters.\n"
                f"    A raw replacement clobbers it and crashes on boot "
                f"(api/audio.rs panic for the .sli).\n"
                f"    Fix: add an exclude for this path in roster.toml. Patch "
                f"forms (.prcx/.prcxml) are safe and are merged instead."
                + ("\n    NOTE: this mod also ships a patch form of the same "
                   "file, so the raw one is redundant." if patched else "")
            )


def check_file_conflicts(mods: list[Path], rep: Report) -> None:
    """Two mods shipping the same non-mergeable file.

    This is the conflict ARCropolis itself enforces: from its wiki, "if you have
    two directories with the exact same / an overlapping file, the game will
    prompt you to correct it on boot" -- and declining the prompt means NEITHER
    file loads. Patch formats (.prcxml, .xmsbt, ...) are exempt because
    ARCropolis merges them onto the vanilla base, which is how 30 mods can all
    edit msg_name.xmsbt without fighting.
    """
    owners: dict[str, list[str]] = defaultdict(list)
    for mod in mods:
        for rp in rel_paths(mod):
            # Only files under a game path map into the arc filesystem and can
            # therefore collide. Mod-root metadata (README.txt, info.toml,
            # config.json, plugin.nro) lives per-mod-directory and never
            # conflicts, so an allowlist of filenames is the wrong instrument.
            head = rp.replace("\\", "/").split("/", 1)[0].lower()
            if head not in GAME_PATHS:
                continue
            if rp.rsplit(".", 1)[-1].lower() in PATCH_EXTS:
                continue
            owners[rp].append(mod.name)

    for path, names in sorted(owners.items()):
        if len(names) > 1:
            listing = "\n".join(f"      claimed by: {n}" for n in sorted(names))
            rep.error(
                f"FILE CONFLICT  {path}\n{listing}\n"
                f"    ARCropolis prompts about this on boot; declining loads "
                f"NEITHER copy.\n"
                f"    Fix: drop one mod, or delete the duplicate file from one "
                f"of them."
            )


def check_filenames(mods: list[Path], rep: Report) -> None:
    """FAT32 and case-sensitivity hazards.

    The build tree lives on ext4 (case-sensitive) but the card is FAT32
    (case-insensitive), so two files differing only in case silently collapse
    into one during the copy.
    """
    for mod in mods:
        seen: dict[str, str] = {}
        for rp in rel_paths(mod):
            for part in Path(rp).parts:
                if bad := (set(part) & FAT32_ILLEGAL):
                    rep.error(
                        f"{mod.name}: filename illegal on FAT32 "
                        f"({''.join(sorted(bad))}): {rp}"
                    )
                    break
            if any(part in JUNK_NAMES or part.startswith("._")
                   for part in Path(rp).parts):
                rep.warning(f"{mod.name}: OS junk file: {rp}")

            lower = rp.lower()
            if lower in seen and seen[lower] != rp:
                rep.error(
                    f"{mod.name}: case-only filename collision -- these merge "
                    f"into one file on FAT32:\n"
                    f"      {seen[lower]}\n      {rp}"
                )
            seen[lower] = rp


def check_hdr_contamination(workspace: str, mods: list[Path], rep: Report) -> None:
    """HDR and the vanilla roster are not composable.

    HDR rewrites movesets and params for the whole cast. A roster mod built
    against vanilla will read HDR's altered params and misbehave or crash.
    """
    if workspace == "hdr":
        return
    for mod in mods:
        if mod.name.lower().startswith("hdr") or (mod / "hdr").exists():
            rep.error(
                f"{mod.name}: HDR payload found in the '{workspace}' workspace.\n"
                f"    HDR replaces cast-wide params that vanilla-built mods rely "
                f"on. Keep it in the hdr workspace."
            )


def check_plugins(rep: Report) -> None:
    """Plugin placement and the Smashline 1/2 incompatibility."""
    from common import BUILD
    for profile in ("roster", "hdr"):
        plugdir = (BUILD / profile / "atmosphere" / "contents" /
                   "01006A800016E000" / "romfs" / "skyline" / "plugins")
        if not plugdir.is_dir():
            continue
        names = {p.name for p in plugdir.glob("*.nro")}
        # Plugins that target the Smashline 1 stack and crash on boot if they
        # are loaded alongside Smashline 2 (libsmashline_plugin.nro).
        SMASHLINE1_ONLY = {
            "libsmashline_hook.nro":
                "the legacy Smashline 1 hook",
            "libsmush_extra_slots_effect_fix.nro":
                "the added-slot effect fix, whose README states plainly that "
                "it crashes if Smashline 2 is installed",
        }
        if "libsmashline_plugin.nro" in names:
            for bad, why in SMASHLINE1_ONLY.items():
                if bad in names:
                    rep.error(
                        f"{profile}: {bad} ({why}) is installed alongside "
                        f"libsmashline_plugin.nro (Smashline 2).\n"
                        f"    This combination crashes on boot. Remove {bad}."
                    )
        stray = [p for p in (BUILD / profile).rglob("*.nro")
                 if plugdir not in p.parents and "ultimate/mods" not in str(p)]
        for p in stray:
            rep.warning(f"{profile}: .nro outside the plugins dir: "
                        f"{p.relative_to(BUILD / profile)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workspace", default=None,
                    help="verify a single layer in isolation")
    ap.add_argument("--profile", default=None,
                    help="verify the union of a profile's layers (what ships)")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors")
    args = ap.parse_args()

    if args.profile:
        from common import load_profiles, profile_mods
        prof = load_profiles().get(args.profile)
        if prof is None:
            die(f"unknown profile '{args.profile}'")
        if prof.get("selfcontained"):
            ok(f"profile '{args.profile}' is a self-contained upstream package "
               f"({prof['selfcontained']}); nothing to lint")
            return 0
        ws = args.profile
        mods = profile_mods(args.profile)
        layers = prof.get("layers", [])
        info(f"profile '{args.profile}' = layers [{', '.join(layers)}]")
        # A declared layer with no mods means it failed to build. Reporting the
        # profile "clean" in that state is worse than useless -- it once passed
        # with the entire reskin layer missing, because the layer directory had
        # been deleted and never rebuilt.
        empty = [l for l in layers if not all_mods(l)]
        if empty:
            for l in empty:
                err(f"layer '{l}' is declared by profile '{args.profile}' but "
                    f"contains no mods -- it was never unpacked, or the unpack "
                    f"failed. This profile would ship without it.")
            return 1
    else:
        ws = args.workspace or "roster"
        mods = all_mods(ws)
    rep = Report()

    if not mods:
        warn(f"workspace '{ws}' has no mods installed")
        return 0

    info(f"verifying workspace '{ws}' ({len(mods)} mods)")

    for mod in mods:
        check_structure(mod, rep)
    allow_raw_csk = bool(prof.get('allow_raw_csk')) if args.profile else False
    stats = check_collisions(mods, rep)
    check_added_char_payload(mods, rep)
    check_plugin_budget(mods, rep)
    check_vanilla_base_conflicts(mods, rep)
    check_csk_managed(mods, rep, allow_raw_csk)
    check_file_conflicts(mods, rep)
    check_empty_files(mods, rep)
    check_filenames(mods, rep)
    check_hdr_contamination(ws, mods, rep)
    check_plugins(rep)

    print()
    for n in rep.notes:
        info(n)
    for w in rep.warnings:
        warn(w)
    for e in rep.errors:
        err(e)

    print()
    src = stats["by_source"]
    info(f"{len(mods)} mods | {stats['added_chars']} added characters | "
         f"{len(stats['fighters'])} host fighters | "
         f"{stats['added_slots']} added slots")
    info(f"slot claims read from: {src.get('config.json', 0)} config.json, "
         f"{src.get('paths', 0)} path-scan")

    if rep.errors:
        err(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s) "
            f"-- NOT safe to deploy")
        return 1
    if rep.warnings and args.strict:
        err(f"{len(rep.warnings)} warning(s) and --strict is set")
        return 1
    ok(f"workspace '{ws}' clean ({len(rep.warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
