#!/usr/bin/env python3
"""Fixture-driven tests for verify.py.

Each fixture reproduces a real failure mode that is invisible on the console.
A test passes when verify.py both fails the build AND names the offending file,
because an error that doesn't identify the culprit is nearly useless when
thirty mods are installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "workspaces"
VERIFY = ROOT / "scripts" / "verify.py"

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"


def touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 16)


def run_verify(ws: str) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, str(VERIFY), "--workspace", ws],
        capture_output=True, text=True, cwd=ROOT,
    )
    return res.returncode, res.stdout + res.stderr


# --- fixtures --------------------------------------------------------------

def fx_nested(ws: Path) -> None:
    """Archive wrapper left in place: mod does nothing, silently."""
    touch(ws / "BadNest" / "Slots" / "ui" / "layout" / "chara.arc")


def fx_collision(ws: Path) -> None:
    """Two added characters riding the same host slot."""
    touch(ws / "Waluigi" / "fighter" / "mario" / "model" / "body" / "c08" / "model.numdlb")
    touch(ws / "Silver" / "fighter" / "mario" / "model" / "body" / "c08" / "model.numdlb")


def fx_collision_shallow(ws: Path) -> None:
    """Regression: slot dirs sitting directly under the fighter, not nested.

    An earlier regex required an intermediate path segment and silently missed
    this form, which would have let a real collision reach the console.
    """
    touch(ws / "ModA" / "fighter" / "koopa" / "c08" / "thing.bin")
    touch(ws / "ModB" / "fighter" / "koopa" / "c08" / "other.bin")


def fx_typo_fighter(ws: Path) -> None:
    """'bowser' is a display name; the internal directory is 'koopa'.

    Lexically distant from the real name, so edit distance cannot catch it --
    this needs the display-name table.
    """
    touch(ws / "TypoMod" / "fighter" / "bowser" / "model" / "body" / "c08" / "model.numdlb")


def fx_junk(ws: Path) -> None:
    touch(ws / "JunkMod" / "fighter" / "mario" / "model" / "body" / "c09" / "model.numdlb")
    touch(ws / "JunkMod" / "__MACOSX" / "._model.numdlb")


def fx_case_collision(ws: Path) -> None:
    """Distinct on ext4, one file on FAT32."""
    touch(ws / "CaseMod" / "fighter" / "mario" / "model" / "body" / "c10" / "Model.numdlb")
    touch(ws / "CaseMod" / "fighter" / "mario" / "model" / "body" / "c10" / "model.numdlb")


def fx_fat32_illegal(ws: Path) -> None:
    touch(ws / "IllegalMod" / "fighter" / "mario" / "model" / "body" / "c11" / "what?.numdlb")


def fx_hdr_contamination(ws: Path) -> None:
    touch(ws / "hdr" / "fighter" / "mario" / "model" / "body" / "c00" / "model.numdlb")


def fx_collision_3digit(ws: Path) -> None:
    """Regression: the c120-c127 block, where collisions actually happen.

    `c(\\d{2})` matched none of these, so 57% of real slot claims -- including
    every mod in the community's default landing block -- were invisible to the
    collision check while it reported the workspace clean.
    """
    for mod in ("ModA", "ModB"):
        (ws / mod).mkdir(parents=True, exist_ok=True)
        (ws / mod / "config.json").write_text(json.dumps(
            {"new-dir-infos": ["fighter/dolly/c120", "fighter/dolly/result/c120"]}))
        touch(ws / mod / "fighter" / "dolly" / "model" / "body" / "c120" / "model.numdlb")
        (ws / mod / "plugin.nro").write_bytes(b"\x00" * 16)


def fx_no_collision_adjacent(ws: Path) -> None:
    """c120 and c128 are distinct. A truncating regex collapsed both to 'c12'."""
    for mod, slot in (("ModA", 120), ("ModB", 128)):
        (ws / mod).mkdir(parents=True, exist_ok=True)
        (ws / mod / "config.json").write_text(json.dumps(
            {"new-dir-infos": [f"fighter/palutena/c{slot}"]}))
        (ws / mod / "plugin.nro").write_bytes(b"\x00" * 16)


def fx_file_conflict(ws: Path) -> None:
    """Two mods shipping the same non-mergeable asset."""
    for mod in ("ModA", "ModB"):
        touch(ws / mod / "ui" / "layout" / "info" / "info_melee" / "layout.arc")


def fx_patch_files_ok(ws: Path) -> None:
    """Patch formats are merged by ARCropolis and must NOT be flagged."""
    for mod in ("ModA", "ModB", "ModC"):
        touch(ws / mod / "ui" / "message" / "msg_name.xmsbt")


def fx_missing_plugin(ws: Path) -> None:
    """Added-character data installed without its moveset code.

    Regression: unpack.py used an allowlist for root-level files and silently
    dropped plugin.nro / config.json from 30 of 31 mods.
    """
    touch(ws / "AddedChar" / "fighter" / "silver" / "model" / "body" / "c00" / "model.numdlb")
    (ws / "AddedChar" / "config.json").write_text("{}")


def fx_zero_byte_audio(ws: Path) -> None:
    """Regression: extractor-zeroed audio, the cause of the CSK boot panic."""
    m = ws / "ZeroMod"
    touch(m / "fighter" / "palutena" / "model" / "body" / "c120" / "model.numdlb")
    (m / "sound" / "bank" / "fighter_voice").mkdir(parents=True, exist_ok=True)
    (m / "sound" / "bank" / "fighter_voice" / "vc_palutena_c120.nus3bank").write_bytes(b"")
    (m / "config.json").write_text(json.dumps(
        {"new-dir-infos": ["fighter/palutena/c120"]}))
    (m / "plugin.nro").write_bytes(b"\x00" * 16)


def fx_marker_files_ok(ws: Path) -> None:
    """Empty .marker files are how mods flag a slot -- must NOT be flagged."""
    m = ws / "MarkerMod"
    for slot in range(120, 128):
        d = m / "fighter" / "dolly" / "model" / "body" / f"c{slot}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "waluigi.marker").write_bytes(b"")
    # Authors also use arbitrary extensions for the same purpose.
    for name in ("sonic.modern", "phoenix.wright", "alt_maya.wright"):
        (m / "fighter" / "dolly" / "model" / "body" / "c120" / name).write_bytes(b"")
    (m / "config.json").write_text(json.dumps(
        {"new-dir-infos": [f"fighter/dolly/c{s}" for s in range(120, 128)]}))
    (m / "plugin.nro").write_bytes(b"\x00" * 16)


def fx_vanilla_base_moveset(ws: Path) -> None:
    """A moveset on c00 that an added character inherits cmn from -> error."""
    added = ws / "AddedChar"
    (added).mkdir(parents=True, exist_ok=True)
    (added / "config.json").write_text(json.dumps({
        "new-dir-infos": ["fighter/sonic/c120"],
        "new-dir-infos-base": {"fighter/sonic/c120/cmn": "fighter/sonic/c00/cmn"}}))
    (added / "plugin.nro").write_bytes(b"\x00" * 16)
    touch(added / "fighter" / "sonic" / "model" / "body" / "c120" / "model.numdlb")
    touch(ws / "VanillaMoveset" / "fighter" / "sonic" / "cmn" / "c00" / "anim.nuanmb")


def fx_vanilla_base_reskin_ok(ws: Path) -> None:
    """A RESKIN of c00 is harmless -- model data is never inherited."""
    added = ws / "AddedChar"
    (added).mkdir(parents=True, exist_ok=True)
    (added / "config.json").write_text(json.dumps({
        "new-dir-infos": ["fighter/sonic/c120"],
        "new-dir-infos-base": {"fighter/sonic/c120/cmn": "fighter/sonic/c00/cmn"}}))
    (added / "plugin.nro").write_bytes(b"\x00" * 16)
    touch(ws / "Reskin" / "fighter" / "sonic" / "model" / "body" / "c00" / "model.numdlb")


def fx_vanilla_slot_shared_ok(ws: Path) -> None:
    """Several mods touching one VANILLA slot via different sub-paths is fine.

    Kirby's c00 holds a copy-ability hat per character, so the Dr. Mario, Hero
    and Ike skins all legitimately write fighter/kirby/.../c00/. A moveset
    writing motion/ alongside a skin writing model/ is the same pattern.
    Genuine overlap here means the same FILE twice, which the file-conflict
    check catches instead.
    """
    touch(ws / "SkinA" / "fighter" / "kirby" / "model" / "copy_mario_hat" / "c00" / "model.numdlb")
    touch(ws / "SkinB" / "fighter" / "kirby" / "model" / "copy_brave_hat" / "c00" / "model.numdlb")
    touch(ws / "MovesetC" / "fighter" / "kirby" / "motion" / "body" / "c00" / "anim.nuanmb")


def fx_clean(ws: Path) -> None:
    """A well-formed roster -- must produce no errors."""
    touch(ws / "GoodChar" / "fighter" / "koopa" / "model" / "body" / "c08" / "model.numdlb")
    touch(ws / "GoodChar" / "ui" / "replace" / "chara" / "chara_1" / "chara_1_koopa_08.bntx")
    touch(ws / "OtherChar" / "fighter" / "murabito" / "model" / "body" / "c09" / "model.numdlb")
    (ws / "GoodChar" / "info.toml").write_text('name = "Good Char"\n')
    (ws / "GoodChar" / "config.json").write_text("{}")
    (ws / "GoodChar" / "plugin.nro").write_bytes(b"\x00" * 16)


TESTS = [
    # (name, builder, should_fail, substrings that must appear)
    ("nested wrapper not stripped", fx_nested, True,
     ["BadNest", "Slots", "unrecognised top-level"]),
    ("two mods claim one slot", fx_collision, True,
     ["COLLISION", "mario", "c08", "Waluigi", "Silver"]),
    ("collision, slot directly under fighter", fx_collision_shallow, True,
     ["COLLISION", "koopa", "c08", "ModA", "ModB"]),
    ("display name used instead of internal name", fx_typo_fighter, True,
     ["display name", "bowser", "koopa", "loads nothing"]),
    ("OS junk files", fx_junk, False,
     ["__MACOSX"]),
    ("case-only collision", fx_case_collision, True,
     ["CaseMod", "case-only", "Model.numdlb"]),
    ("FAT32-illegal filename", fx_fat32_illegal, True,
     ["IllegalMod", "illegal on FAT32"]),
    ("HDR payload in roster workspace", fx_hdr_contamination, True,
     ["HDR payload", "hdr"]),
    ("collision at c120 (3-digit slot)", fx_collision_3digit, True,
     ["COLLISION", "dolly", "c120", "ModA", "ModB"]),
    ("c120 vs c128 are NOT a collision", fx_no_collision_adjacent, False, []),
    ("same non-mergeable file in two mods", fx_file_conflict, True,
     ["FILE CONFLICT", "layout.arc", "ModA", "ModB"]),
    ("shared .xmsbt patches are merged, not conflicts", fx_patch_files_ok, False, []),
    ("config.json without plugin.nro warns, does not fail", fx_missing_plugin,
     False, ["AddedChar", "plugin.nro"]),
    ("zero-byte audio file (CSK panic cause)", fx_zero_byte_audio, True,
     ["ZeroMod", "nus3bank", "zero-byte"]),
    ("empty author flag files are legitimate", fx_marker_files_ok, False, []),
    ("moveset on an inherited vanilla slot", fx_vanilla_base_moveset, True,
     ["VanillaMoveset", "AddedChar", "inherit"]),
    ("reskin of an inherited vanilla slot is fine", fx_vanilla_base_reskin_ok, False, []),
    ("shared vanilla slot via different sub-paths is not a collision",
     fx_vanilla_slot_shared_ok, False, []),
    ("clean roster", fx_clean, False, []),
]


def main() -> int:
    failures = 0
    for i, (name, builder, should_fail, needles) in enumerate(TESTS):
        ws_name = f"_fixture_{i}"
        ws = WORKSPACES / ws_name
        shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True)
        try:
            builder(ws)
            code, out = run_verify(ws_name)
            problems = []
            if should_fail and code == 0:
                problems.append("expected non-zero exit, got 0")
            if not should_fail and code != 0:
                problems.append(f"expected exit 0, got {code}")
            for needle in needles:
                if needle not in out:
                    problems.append(f"output missing {needle!r}")
            if problems:
                failures += 1
                print(f"{FAIL} {name}")
                for p in problems:
                    print(f"       {p}")
                print("       --- verify.py output ---")
                for line in out.strip().splitlines():
                    print(f"       {line}")
            else:
                print(f"{PASS} {name}")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    print()
    if failures:
        print(f"\033[31m{failures} of {len(TESTS)} tests failed\033[0m")
        return 1
    print(f"\033[32mall {len(TESTS)} tests passed\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
