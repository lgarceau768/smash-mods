#!/usr/bin/env python3
"""Assemble build/<profile>/ -- a byte-exact mirror of what goes on the SD card.

Two profiles, and they are NOT interchangeable at the mod level:

  roster  vanilla Smash + standalone Skyline/ARCropolis/Smashline + added chars
  hdr     HewDraw Remix, which ships its OWN Skyline, ARCropolis and Smashline

HDR bundles a forked ARCropolis build and pins an older Smashline than the
standalone release. Those binaries live in exefs/ and romfs/skyline/plugins/,
which Atmosphere loads at process start -- outside ARCropolis's control. That
is why an in-game workspace toggle cannot switch between these two profiles,
and why each profile is staged as a complete, self-contained SD overlay.

Usage:
    stage.py                    # stage both profiles
    stage.py --profile roster
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import (
    BUILD, DOWNLOADS, WORKSPACES, load_profiles, die, err, human, info, load_manifest,
    load_roster, ok, warn,
)


def extract(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        ["7z", "x", "-y", f"-o{dest}", str(archive)],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(f"extract failed for {archive.name}: {res.stderr[-300:]}")


def link_tree(src: Path, dst: Path) -> None:
    """Copy a tree using hardlinks where possible.

    build/ is generated and never edited in place, and rsync writes real content
    to the FAT32 card regardless, so hardlinks are invisible downstream. They
    matter because the roster layer appears in three profiles: deep-copying it
    each time costs ~26GB for no benefit. Falls back to a real copy across
    filesystems.
    """
    def link_or_copy(a: str, b: str) -> None:
        # Fall back PER FILE. Retrying the whole tree does not work: copytree
        # has already created the directories by the time it raises, so the
        # second attempt dies with FileExistsError and the profile stages with
        # no mods at all.
        try:
            os.link(a, b)
        except OSError:
            shutil.copy2(a, b)

    shutil.copytree(src, dst, copy_function=link_or_copy)


def tree_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def stage_layered(manifest: dict, name: str, prof: dict) -> Path:
    """Base stack + one or more mod layers, in declared order."""
    out = BUILD / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    tid = manifest["meta"]["title_id"]

    for entry in manifest.get("upstream", []):
        if entry["kind"] == "workspace":
            continue  # HDR: staged into its own profile
        src = DOWNLOADS / "upstream" / entry["file"]
        if not src.exists():
            die(f"missing {src} -- run fetch.py first")
        dest = out / entry["dest"] if entry["dest"] else out

        if entry["kind"] == "zip":
            extract(src, dest)
        elif entry["kind"] == "plugin_zip":
            # Take only the .nro plugins out of the archive. These bundles also
            # ship optional example mods we have not asked for, and installing
            # a dependency must not drag unrelated content onto the card.
            dest.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="smash-plugin-") as tmp:
                extract(src, Path(tmp))
                found = sorted(Path(tmp).rglob("*.nro"))
                if not found:
                    die(f"{entry['name']}: archive contains no .nro plugin")
                for nro in found:
                    shutil.copy2(nro, dest / nro.name)
                    info(f"    + {nro.name}")
        elif entry["kind"] == "raw":
            dest.mkdir(parents=True, exist_ok=True)
            # Plugins must keep their canonical filename; Skyline loads every
            # .nro in the directory by name. Prefer an explicit install_as over
            # guessing from the cache filename.
            canonical = entry.get("install_as") or entry["file"].split("-v")[0] + ".nro"
            shutil.copy2(src, dest / canonical)
        info(f"  staged {entry['name']} {entry['version']}")

    # Sanity: the pieces that must exist or nothing loads at all.
    exefs = out / "atmosphere" / "contents" / tid / "exefs"
    plugins = out / "atmosphere" / "contents" / tid / "romfs" / "skyline" / "plugins"
    for required in (exefs / "subsdk9", exefs / "main.npdm",
                     plugins / "libarcropolis.nro"):
        if not required.exists():
            die(f"base stack incomplete: missing {required.relative_to(out)}")

    mods_dir = out / "ultimate" / "mods"
    mods_dir.mkdir(parents=True, exist_ok=True)
    installed = 0
    for layer in prof.get("layers", []):
        src_dir = WORKSPACES / layer
        if not src_dir.is_dir():
            warn(f"  layer '{layer}' has no workspace yet -- skipping")
            continue
        n = 0
        for mod in sorted(src_dir.iterdir()):
            if not mod.is_dir() or mod.name.startswith("."):
                continue
            dest = mods_dir / mod.name
            # Later layers win on a name clash, which is what the declared
            # layer order is for.
            if dest.exists():
                shutil.rmtree(dest)
            link_tree(mod, dest)
            n += 1
        info(f"  layer '{layer}': {n} mods")
        installed += n

    ok(f"profile '{name}' staged: {installed} mods, {human(tree_size(out))} "
       f"(hardlinked from workspaces/, so shared layers cost no extra disk)")
    return out


def stage_selfcontained(manifest: dict, name: str, upstream_name: str) -> Path | None:
    """A package that ships its own base stack, SD-root relative."""
    entry = next((e for e in manifest.get("upstream", [])
                  if e["kind"] == "workspace" and e["name"] == upstream_name), None)
    if entry is None:
        warn(f"no '{upstream_name}' entry in manifest -- skipping")
        return None
    src = DOWNLOADS / "upstream" / entry["file"]
    if not src.exists():
        die(f"missing {src} -- run fetch.py first")

    out = BUILD / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    info(f"  extracting {upstream_name} {entry['version']} "
         f"({human(src.stat().st_size)}) ...")
    extract(src, out)

    tid = manifest["meta"]["title_id"]
    plugins = out / "atmosphere" / "contents" / tid / "romfs" / "skyline" / "plugins"
    if not (plugins / "libarcropolis.nro").exists():
        die(f"{upstream_name} package did not contain its bundled ARCropolis -- "
            f"refusing to stage a half-installed overhaul")

    ok(f"profile '{name}' staged: {human(tree_size(out))}")
    return out


def main() -> int:
    profiles = load_profiles()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="all",
                    help=f"one of: {', '.join(sorted(profiles))}, or 'all'")
    ap.add_argument("--list", action="store_true", help="list profiles and exit")
    args = ap.parse_args()

    if args.list:
        for n, p in sorted(profiles.items()):
            kind = (f"self-contained ({p['selfcontained']})"
                    if p.get("selfcontained")
                    else "layers: " + ", ".join(p.get("layers", [])))
            print(f"  {n:<12} {p.get('description','')}\n               {kind}")
        return 0

    manifest = load_manifest()
    BUILD.mkdir(exist_ok=True)

    todo = sorted(profiles) if args.profile == "all" else [args.profile]
    for name in todo:
        prof = profiles.get(name)
        if prof is None:
            die(f"unknown profile '{name}'. Known: {', '.join(sorted(profiles))}")
        info(f"staging profile '{name}'")
        if prof.get("selfcontained"):
            stage_selfcontained(manifest, name, prof["selfcontained"])
        else:
            stage_layered(manifest, name, prof)

    print()
    info("NOTE: turn OFF auto-update in the in-game ARCropolis menu on first "
         "boot. It defaults to ON and its update check goes to a non-Nintendo "
         "host, so blocking Nintendo's servers does not stop it. The setting "
         "cannot be pre-authored here -- ARCropolis keys its config by the "
         "Nintendo account UID, known only at runtime -- but you only need to "
         "set it once: deploy.sh excludes ultimate/arcropolis/ from --delete, "
         "so it survives later deploys.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
