#!/usr/bin/env python3
"""Normalise mod archives into the layout ARCropolis actually requires.

ARCropolis expects  ultimate/mods/<ModName>/<game path>/...  where <game path>
is a top-level game directory such as fighter/ or ui/. Community archives are
wildly inconsistent about this: many wrap everything in an extra folder (the
CSS layout fix ships as "Slots/ui/...", one level too deep), some carry
__MACOSX/ noise, some are already correct.

A mod nested one level too deep does not error -- it loads nothing, silently.
So this script finds the real root rather than trusting the archive, and
refuses loudly when it can't, on the principle that a build failure is far
cheaper than a mod that quietly does nothing on the console.

Usage:
    unpack.py <archive> --workspace roster [--name ModName]
    unpack.py --all                 # everything in manifest/roster
"""

from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import (
    ALLOWED_ROOT_FILES, DOWNLOADS, ROOT, GAME_PATHS, JUNK_NAMES, WORKSPACES,
    die, err, info, load_manifest, load_roster, ok, warn,
)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def scratch_dir() -> str:
    """Where to extract archives.

    Deliberately NOT the system temp dir. Extraction needs room for the largest
    archive expanded (630MB+ here), and filling the root filesystem is not
    hypothetical -- it happened: `/` hit 100% and 7z began failing with
    errno=28, silently truncating extractions to a few dozen files while
    reporting success. Staging next to workspaces/ puts scratch on whatever
    volume holds the bulk data, which is where the room actually is.
    """
    import os
    if (env := os.environ.get("SMASH_SCRATCH")):
        d = pathlib.Path(env)
    else:
        d = WORKSPACES.resolve().parent / "scratch"
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def declared_contents(archive: Path) -> tuple[int, int, int]:
    """(file count, total bytes, zero-byte count) as declared by the archive.

    7z can *list* RAR5 accurately even though it cannot decompress it, so one
    code path covers zip/7z/rar.
    """
    res = subprocess.run(["7z", "l", "-slt", str(archive)],
                         capture_output=True, text=True)
    count = total = zeros = 0
    is_dir = False
    for line in res.stdout.splitlines():
        if line.startswith("Path = "):
            is_dir = False
        elif line.startswith("Folder = "):
            is_dir = line.split("=", 1)[1].strip() == "+"
        elif line.startswith("Attributes = "):
            is_dir = is_dir or "D" in line.split("=", 1)[1]
        elif line.startswith("Size = ") and not is_dir:
            raw = line.split("=", 1)[1].strip()
            if raw.isdigit():
                count += 1
                total += int(raw)
                zeros += 1 if int(raw) == 0 else 0
    return count, total, zeros


def extract(archive: Path, dest: Path) -> None:
    """Extract, then prove the bytes actually arrived.

    Two real extractor failures motivate this:

    1. p7zip *recognises* RAR5 but cannot decompress it without the proprietary
       codec. It exits reporting sub-item errors while writing a full tree of
       zero-byte files.
    2. `unar` is worse because it fails QUIETLY and only PARTIALLY. On these
       archives it corrupted ~15% of files to zero bytes while reporting
       success -- 100 of 642 for one mod, including the nus3bank audio files
       that made The CSK Collection panic on console with
       "range start index 16 out of range for slice of length 0".

    A percentage heuristic missed (2) entirely, because 15% empty looks nothing
    like a total failure. So the check is now absolute: compare the extracted
    byte total against what the archive itself declares. Some files ARE
    legitimately zero bytes -- mods ship one empty `.marker` per slot -- which
    is exactly why the archive's own declaration is the only trustworthy
    reference.
    """
    is_rar = archive.suffix.lower() == ".rar"

    if is_rar:
        # unrar first: it is correct on these archives where unar is not.
        if have("unrar"):
            cmd = ["unrar", "x", "-y", str(archive), str(dest) + "/"]
        elif have("unar"):
            cmd = ["unar", "-quiet", "-force-overwrite", "-output-directory",
                   str(dest), str(archive)]
            warn(f"{archive.name}: falling back to unar, which is known to "
                 f"silently zero out some files. Install unrar.")
        else:
            raise RuntimeError(
                "RAR archive and no RAR extractor installed. p7zip cannot "
                "decompress RAR5 -- it writes empty files instead.\n"
                "    Install one:  sudo apt install unrar")
    else:
        cmd = ["7z", "x", "-y", f"-o{dest}", str(archive)]

    res = subprocess.run(cmd, capture_output=True, text=True)

    files = [p for p in dest.rglob("*") if p.is_file()]
    if not files:
        raise RuntimeError(
            f"extraction produced no files "
            f"({res.stdout[-300:]}{res.stderr[-300:]})")

    got_total = sum(p.stat().st_size for p in files)
    got_zeros = sum(1 for p in files if p.stat().st_size == 0)
    want_count, want_total, want_zeros = declared_contents(archive)

    # Byte total is the real integrity signal: it catches zeroed files and
    # truncation alike, and needs no path mapping between listing and disk.
    if want_total and got_total < want_total:
        short = want_total - got_total
        raise RuntimeError(
            f"extraction is INCOMPLETE -- {short:,} bytes missing.\n"
            f"    archive declares {want_total:,} bytes in {want_count} files\n"
            f"    extracted        {got_total:,} bytes in {len(files)} files\n"
            f"    zero-byte files: {got_zeros} on disk vs {want_zeros} declared\n"
            f"    The extractor reported success but lost data. Do not ship this."
        )

    if got_zeros > want_zeros:
        raise RuntimeError(
            f"{got_zeros} zero-byte files on disk but the archive declares only "
            f"{want_zeros}.\n    {got_zeros - want_zeros} file(s) were silently "
            f"emptied by the extractor."
        )

    if res.returncode != 0:
        warn(f"{archive.name}: extractor returned {res.returncode} but all "
             f"{want_total:,} declared bytes are present")


def is_mod_root(d: Path) -> bool:
    """True if this directory directly contains at least one game path."""
    try:
        return any(c.is_dir() and c.name.lower() in GAME_PATHS for c in d.iterdir())
    except OSError:
        return False


def find_all_mod_roots(base: Path, max_depth: int = 8) -> list[Path]:
    """Every mod root at any depth, not just the shallowest.

    Needed for variant selection: an archive can offer alternatives at
    different depths. Sonic Re-Imagined puts [SL2 Universal] variants at depth 3
    and [SL2 Slotted] ones at depth 4, so a shallowest-only search silently
    hides half the choices -- including the only variant that leaves the vanilla
    c00 slot alone.

    Roots nested inside another root are dropped, so we never return both a mod
    and its own subdirectory.
    """
    found: list[Path] = []
    stack = [(base, 0)]
    while stack:
        d, depth = stack.pop()
        if depth > max_depth:
            continue
        if is_mod_root(d):
            found.append(d)
            continue          # do not descend into a mod
        try:
            stack += [(c, depth + 1) for c in d.iterdir()
                      if c.is_dir() and c.name not in JUNK_NAMES]
        except OSError:
            continue
    return sorted(found)


def find_mod_roots(base: Path, max_depth: int = 6) -> list[Path]:
    """Find the shallowest directories that look like mod roots.

    Breadth-first so we stop at the shallowest level that works -- descending
    further would find fighter/ inside a valid root and mistake it for one.
    Returns multiple roots when an archive bundles several mods side by side.
    """
    frontier = [base]
    depth = 0
    while frontier and depth <= max_depth:
        hits = [d for d in frontier if is_mod_root(d)]
        if hits:
            return hits
        nxt: list[Path] = []
        for d in frontier:
            try:
                nxt += [c for c in d.iterdir()
                        if c.is_dir() and c.name not in JUNK_NAMES]
            except OSError:
                continue
        frontier = nxt
        depth += 1
    return []


def strip_junk(root: Path) -> int:
    """Remove OS metadata that would otherwise be copied to the SD card."""
    removed = 0
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.name in JUNK_NAMES or p.name.startswith("._"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
            removed += 1
    return removed


def safe_name(name: str) -> str:
    """A mod directory name that survives FAT32 and reads cleanly in-game."""
    name = re.sub(r"\.(zip|7z|rar)$", "", name, flags=re.I)
    name = re.sub(r'[\\/:*?"<>|]+', "-", name)
    name = re.sub(r"\s+", "-", name.strip())
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("-.") or "mod"


def install(root: Path, target: Path) -> tuple[int, int]:
    """Copy game paths (and permitted root files) from root into target."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    dirs = files = 0
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name.lower() in GAME_PATHS:
            # Normalise the game path itself to lowercase; the console's
            # filesystem lookups are case-sensitive here.
            shutil.copytree(child, target / child.name.lower())
            dirs += 1
        elif child.is_file() and child.name not in JUNK_NAMES \
                and not child.name.startswith("._"):
            # Copy EVERY root-level file, not an allowlist.
            #
            # 30 of 31 added-character mods ship plugin.nro (the Smashline code
            # that implements the moveset) and config.json (the added-character
            # definition) beside the game paths. An allowlist silently dropped
            # both, which would have put models and animations on the card with
            # no moveset behind them -- every character broken, no error
            # anywhere. Anything unexpected here is worth carrying over;
            # dropping files is never the safe default.
            shutil.copy2(child, target / child.name)
            files += 1
    return dirs, files


def apply_excludes(target: Path, excludes: list[str]) -> None:
    """Drop files a roster entry declares it must not ship.

    Used to resolve conflicts where two mods carry different versions of the
    same non-mergeable asset. Recording it in roster.toml keeps the resolution
    reproducible instead of a manual delete that the next rebuild would undo.
    """
    for rel in excludes or []:
        victim = target / rel
        if victim.is_dir():
            shutil.rmtree(victim)
            info(f"    - excluded {rel}/")
        elif victim.exists():
            victim.unlink()
            info(f"    - excluded {rel}")
        else:
            warn(f"    exclude '{rel}' matched nothing in {target.name}")


def unpack_one(archive: Path, workspace: str, name: str | None = None,
               variant: str | None = None,
               excludes: list[str] | None = None) -> bool:
    if not archive.exists():
        err(f"missing archive: {archive}")
        return False

    mod_name = safe_name(name or archive.stem)
    target = WORKSPACES / workspace / mod_name

    # Extract on the SAME filesystem as the repo, not /tmp.
    #
    # /tmp here is tmpfs -- RAM-backed and small (15GB, often much less free).
    # Skin archives expand to several GB each, so extracting there silently ran
    # out of space and produced partial trees; the byte-total check caught five
    # of them. A repo-local scratch dir has the whole disk behind it, and makes
    # the final install a same-filesystem operation rather than a cross-device
    # copy.
    scratch = ROOT / ".tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smash-unpack-", dir=scratch) as tmp:
        tmpdir = Path(tmp)
        try:
            extract(archive, tmpdir)
        except Exception as exc:
            err(f"{mod_name}: {exc}")
            return False

        strip_junk(tmpdir)
        roots = find_all_mod_roots(tmpdir) if variant else find_mod_roots(tmpdir)

        if not roots:
            # Deliberately loud: keep the extraction for inspection rather than
            # installing something that would be inert on the console.
            keep = Path(tempfile.mkdtemp(prefix=f"smash-FAILED-{mod_name}-"))
            shutil.copytree(tmpdir, keep, dirs_exist_ok=True)
            err(f"{mod_name}: no recognisable game path found in archive")
            err(f"    top level: {sorted(p.name for p in tmpdir.iterdir())[:8]}")
            err(f"    extracted for inspection: {keep}")
            err("    expected one of: fighter/ ui/ sound/ effect/ stage/ ...")
            return False

        if len(roots) == 1:
            root = roots[0]
            rel = root.relative_to(tmpdir)
            if str(rel) != ".":
                info(f"{mod_name}: stripped wrapper '{rel}/'")
            dirs, files = install(root, target)
            apply_excludes(target, excludes)
            # If the archive shipped moveset code, it must survive installation.
            # This is the precise form of the check: an allowlist in install()
            # once dropped plugin.nro from 30 of 31 mods, and only the archive
            # knows whether one was there to begin with.
            if (root / "plugin.nro").is_file() and not (target / "plugin.nro").is_file():
                err(f"{mod_name}: archive contained plugin.nro but it did not "
                    f"reach the workspace -- the moveset code was lost")
                return False
            ok(f"{mod_name} -> {workspace}/ ({dirs} game path(s), {files} meta file(s))")
            return True

        # Archive bundles several mods. Sometimes they are additive, sometimes
        # they are mutually exclusive variants of one mod (Sonic Re-Imagined
        # ships "Battle Mode" and "Modern Mode", both rewriting all 8 vanilla
        # Sonic slots). A roster entry can pin which one it wants with
        # `variant = "Modern"`; without that, all roots are installed and
        # verify.py reports the collision.
        if variant:
            matched = [r for r in roots if variant.lower() in r.name.lower()]
            if not matched:
                err(f"{mod_name}: variant '{variant}' matched none of: "
                    f"{[r.name for r in roots]}")
                return False
            if len(matched) == 1:
                dirs, files = install(matched[0], target)
                apply_excludes(target, excludes)
                info(f"{mod_name}: selected variant '{matched[0].name}' "
                     f"({len(roots) - 1} other(s) skipped)")
                ok(f"{mod_name} -> {workspace}/ ({dirs} game path(s), "
                   f"{files} meta file(s))")
                return True
            roots = matched

        # Distinguish ADDITIVE bundles from mutually exclusive VARIANTS.
        #
        # Shadow ships a moveset plus a separate assist trophy -- different
        # files, both wanted. Inkling ships "Octoling_VanillaSlot" and
        # "...VanillaSlotAlt" -- the same files twice, and installing both is a
        # guaranteed ARCropolis boot conflict where declining loads neither.
        #
        # File overlap is what separates the two cases, so test for it rather
        # than guessing from folder names.
        def rel_files(r: Path) -> set[str]:
            return {str(f.relative_to(r)) for f in r.rglob("*") if f.is_file()}

        sets = [(r, rel_files(r)) for r in roots]
        overlapping = any(
            sets[i][1] & sets[j][1]
            for i in range(len(sets)) for j in range(i + 1, len(sets))
        )
        if overlapping:
            chosen = sets[0][0]
            skipped = [r.name for r, _ in sets[1:]]
            warn(f"{mod_name}: archive holds {len(roots)} MUTUALLY EXCLUSIVE "
                 f"variants (they share files). Installing '{chosen.name}' and "
                 f"skipping {len(skipped)}.")
            warn(f"    to choose differently, set variant = \"...\" in "
                 f"roster.toml; options: {', '.join(skipped)}")
            dirs, files = install(chosen, target)
            apply_excludes(target, excludes)
            ok(f"{mod_name} -> {workspace}/ ({dirs} game path(s), "
               f"{files} meta file(s))")
            return True

        info(f"{mod_name}: archive contains {len(roots)} additive mods, splitting")
        allok = True
        for root in roots:
            sub = safe_name(f"{mod_name}-{root.name}")
            sub_target = WORKSPACES / workspace / sub
            dirs, files = install(root, sub_target)
            apply_excludes(sub_target, excludes)
            ok(f"  {sub} ({dirs} game path(s), {files} meta file(s))")
            allok = allok and dirs > 0
        return allok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", nargs="?", help="archive to unpack")
    ap.add_argument("--workspace", default="roster")
    ap.add_argument("--name")
    ap.add_argument("--variant",
                    help="when an archive bundles mutually exclusive variants, "
                         "install only the one whose folder matches this")
    ap.add_argument("--all", action="store_true",
                    help="unpack every mod pinned in manifest.toml and roster.toml")
    args = ap.parse_args()

    if args.all:
        entries = []
        for e in load_manifest().get("mod", []):
            entries.append((e, e.get("workspace", "roster")))
        for e in load_roster().get("mod", []):
            entries.append((e, e.get("workspace", "roster")))
        if not entries:
            warn("no mods pinned yet -- nothing to unpack")
            return 0
        failures = 0
        for entry, ws in entries:
            archive = DOWNLOADS / "mods" / entry["file"]
            if not unpack_one(archive, ws, entry.get("name"),
                              entry.get("variant"), entry.get("exclude")):
                failures += 1
        print()
        if failures:
            err(f"{failures} of {len(entries)} mods failed to unpack")
            return 1
        ok(f"unpacked {len(entries)} mod(s)")
        return 0

    if not args.archive:
        die("give an archive path, or --all")
    return 0 if unpack_one(Path(args.archive), args.workspace, args.name,
                           args.variant) else 1


if __name__ == "__main__":
    sys.exit(main())
