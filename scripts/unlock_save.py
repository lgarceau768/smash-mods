#!/usr/bin/env python3
"""Unlock every fighter in a Smash Ultimate save, in place of grinding.

Why this matters for a modded setup: added characters ride a HOST fighter's
extra costume slots (Sans on Palutena c120, Waluigi on Terry c120). If the host
is locked, the host is unselectable, and so is its rider. Unlocking the base
roster is what makes the added characters reachable.

The unlock table is a contiguous array in system_data.bin:

    base offset 0x53FF40, stride 8 bytes, 1 byte per fighter
    86 entries (74 base + 12 DLC), 0x00 = locked, 0x01 = unlocked

Those offsets have been stable since 2019 -- Nintendo pre-allocated every DLC
slot at launch -- which is why the file size is identical across game versions.
The size check below is the guard: if it does not match exactly, this is not a
Smash Ultimate save and nothing is written.

Editing your own save is preferred over importing a stranger's "100% save",
which replaces your World of Light progress, replays, Miis and tags, and carries
the uploader's custom stages and rulesets. It also beats Ultimate Smasher, which
only writes 71 of the 86 entries.

The save is per-user-profile. Export it UNPACKED with JKSV, patch, restore.

    unlock_save.py <system_data.bin>            # dry run: report only
    unlock_save.py <system_data.bin> --commit   # write (backs up first)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Verified against a known-good 100% save.
SAVE_SIZE = 5_982_968
TABLE_BASE = 0x53FF40
STRIDE = 8
FIGHTER_COUNT = 86

RED, YEL, GRN, BLU, OFF = (
    "\033[31m", "\033[33m", "\033[32m", "\033[34m", "\033[0m"
) if sys.stdout.isatty() else ("",) * 5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("save", type=Path, help="path to system_data.bin")
    ap.add_argument("--commit", action="store_true",
                    help="actually write (a .bak copy is made first)")
    args = ap.parse_args()

    if not args.save.is_file():
        print(f"{RED}ERROR{OFF} no such file: {args.save}", file=sys.stderr)
        return 1

    data = bytearray(args.save.read_bytes())

    # The only real safety check available offline. A wrong file here would be
    # silently corrupted at these offsets, so refuse rather than guess.
    if len(data) != SAVE_SIZE:
        print(f"{RED}ERROR{OFF} unexpected size {len(data):,} bytes "
              f"(expected exactly {SAVE_SIZE:,}).", file=sys.stderr)
        print("    This does not look like a Smash Ultimate system_data.bin.",
              file=sys.stderr)
        print("    Export the save UNPACKED with JKSV, not as a ZIP.",
              file=sys.stderr)
        return 1

    offsets = [TABLE_BASE + n * STRIDE for n in range(FIGHTER_COUNT)]
    before = [data[o] for o in offsets]
    unlocked = sum(1 for b in before if b == 0x01)
    locked = [i for i, b in enumerate(before) if b != 0x01]

    # A table that is neither clearly locked nor clearly unlocked suggests the
    # offsets are wrong for this file -- worth saying out loud before writing.
    odd = [b for b in before if b not in (0x00, 0x01)]
    if odd:
        print(f"{YEL}WARN{OFF} {len(odd)} entries hold values other than "
              f"0x00/0x01: {sorted(set(odd))[:6]}")
        print("     The table may not be where expected. Inspect before "
              "committing.")

    print(f"{BLU}::{OFF} {args.save}")
    print(f"{BLU}::{OFF} size {len(data):,} bytes (matches expected)")
    print(f"{BLU}::{OFF} fighters unlocked: {unlocked}/{FIGHTER_COUNT}")

    if not locked:
        print(f"{GRN}OK{OFF} everything is already unlocked; nothing to do")
        return 0

    print(f"{BLU}::{OFF} would unlock {len(locked)} fighter slot(s): "
          f"indices {locked[:12]}{' ...' if len(locked) > 12 else ''}")

    if not args.commit:
        print(f"\n{YEL}WARN{OFF} dry run -- nothing written. "
              f"Re-run with --commit to apply.")
        return 0

    backup = args.save.with_suffix(args.save.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(args.save, backup)
        print(f"{GRN}OK{OFF} backed up original -> {backup.name}")
    else:
        print(f"{YEL}WARN{OFF} {backup.name} already exists, keeping the "
              f"original backup")

    for o in offsets:
        data[o] = 0x01

    # Size must be byte-identical or the game rejects the save.
    if len(data) != SAVE_SIZE:
        print(f"{RED}ERROR{OFF} size changed during patch -- refusing to write",
              file=sys.stderr)
        return 1

    args.save.write_bytes(bytes(data))

    check = args.save.read_bytes()
    now = sum(1 for o in offsets if check[o] == 0x01)
    if len(check) != SAVE_SIZE or now != FIGHTER_COUNT:
        print(f"{RED}ERROR{OFF} verification failed after write "
              f"({now}/{FIGHTER_COUNT} unlocked, {len(check):,} bytes)",
              file=sys.stderr)
        return 1

    print(f"{GRN}OK{OFF} {now}/{FIGHTER_COUNT} unlocked, size unchanged "
          f"({len(check):,} bytes)")
    print(f"""
Next:
  1. Put this file back into the JKSV backup folder it came from, keeping the
     exact folder layout JKSV produced. Mismatched layout is the usual cause of
     "the game acts like I've never played it".
  2. JKSV -> same user profile -> hover Smash -> hover the patched folder ->
     press Y, hold A to restore.
  3. Keep NSO cloud saves OFF for this title. Sync is bidirectional and will
     happily overwrite the patched save with the old one.
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
