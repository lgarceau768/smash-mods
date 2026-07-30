#!/usr/bin/env python3
"""Download and checksum-verify every pinned component.

Idempotent: a file that already exists and matches its recorded checksum is
skipped, so re-runs are cheap and an interrupted download can never poison a
later build (a partial file fails its checksum and is re-fetched).

Sources:
  manifest.toml  [[upstream]] and [[mod]]  -- the base stack and structural mods
  roster.toml    [[mod]]                   -- curated added characters

GameBanana entries may specify only a mod id; the download URL is then resolved
through the public apiv11 ProfilePage endpoint, which also supplies an md5 we
verify against.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from common import (
    DOWNLOADS, Colors, die, err, human, info, load_manifest, load_roster,
    md5_file, ok, sha256_file, warn,
)

UA = "Mozilla/5.0 (smash-mods build script)"
GB_API = "https://gamebanana.com/apiv11/Mod/{}/ProfilePage"


def gb_profile(mod_id: int) -> dict:
    req = urllib.request.Request(GB_API.format(mod_id), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


README_RE = re.compile(r"read\s*me|^readme", re.I)


def gb_primary_file(mod_id: int) -> dict:
    """The download that is actually the mod.

    NOT simply _aFiles[0]. GameBanana mods routinely ship several files and the
    first is often not the one you want:

      * Raichu offers a 15MB "c02" build (overwrites a VANILLA slot) and a 115MB
        "slotted c80-87" build (a real added character). Taking [0] silently
        picked the vanilla-overwriting one.
      * Springtrap and Armstrong host only a ~1KB readme here, with the real
        payload off-site on GitHub.

    Largest file is the right heuristic for "the actual mod", and a payload that
    is both tiny and named like a readme is called out rather than installed.
    """
    prof = gb_profile(mod_id)
    files = prof.get("_aFiles") or []
    if not files:
        raise RuntimeError(f"mod {mod_id} has no current files (withdrawn?)")

    f = max(files, key=lambda x: x.get("_nFilesize", 0))

    if len(files) > 1:
        others = ", ".join(f"{x['_sFile']} ({x.get('_nFilesize', 0) // 1024}KB)"
                           for x in files if x is not f)
        warn(f"mod {mod_id} ships {len(files)} files; chose the largest "
             f"({f['_sFile']}). Others: {others}")

    if f.get("_nFilesize", 0) < 64 * 1024 and README_RE.search(f["_sFile"]):
        raise RuntimeError(
            f"mod {mod_id}'s only download is {f['_sFile']} "
            f"({f.get('_nFilesize', 0):,} B) -- that is a readme, not the mod. "
            f"The real payload is hosted off-site; pin an explicit url instead.")
    return {
        "name": prof.get("_sName", f"mod-{mod_id}"),
        "version": prof.get("_sVersion", ""),
        "file": f["_sFile"],
        "url": f["_sDownloadUrl"],
        "md5": f.get("_sMd5Checksum", ""),
        "size": f.get("_nFilesize", 0),
    }


# Spacing between downloads. Pulling ~44 files back to back got us 503'd by
# GameBanana's Cloudflare edge while their API kept answering fine. Their
# bandwidth is donated; a couple of seconds between files is the polite floor.
DOWNLOAD_SPACING = 3.0

# 503 means "slow down", so wait progressively longer rather than hammering.
BACKOFF = (30, 120, 300, 900)


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    # curl rather than urllib: GameBanana redirects to a filecache host and we
    # want its redirect/retry handling.
    cmd = [
        "curl", "-sSL", "--fail", "--retry", "2", "--retry-delay", "5",
        "-A", UA, "-o", str(tmp), url,
    ]
    for attempt, wait in enumerate((0, *BACKOFF)):
        if wait:
            warn(f"    rate limited; waiting {wait}s before retry "
                 f"{attempt}/{len(BACKOFF)}")
            time.sleep(wait)
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            tmp.replace(dest)
            time.sleep(DOWNLOAD_SPACING)
            return
        stderr = res.stderr.strip()
        tmp.unlink(missing_ok=True)
        # 22 with a 5xx is throttling; anything else is a real failure.
        if not ("503" in stderr or "429" in stderr or "502" in stderr):
            raise RuntimeError(f"download failed: {stderr or res.returncode}")
    raise RuntimeError(
        "still rate limited after backing off for "
        f"{sum(BACKOFF)}s. GameBanana is throttling this IP -- wait a while and "
        "re-run; already-downloaded files are skipped.")


def verify(path: Path, sha256: str = "", md5: str = "") -> tuple[bool, str]:
    """Returns (valid, detail). A pinned checksum of PENDING means 'record it'."""
    if sha256 and sha256 != "PENDING":
        actual = sha256_file(path)
        if actual != sha256:
            return False, f"sha256 mismatch\n    expected {sha256}\n    actual   {actual}"
    if md5:
        actual = md5_file(path)
        if actual != md5:
            return False, f"md5 mismatch\n    expected {md5}\n    actual   {actual}"
    return True, ""


def handle(entry: dict, subdir: str) -> bool:
    """Fetch one entry. Returns True on success."""
    name = entry.get("name", "?")
    gb_id = entry.get("gamebanana_id")
    url = entry.get("url", "")
    filename = entry.get("file", "")
    sha256 = entry.get("sha256", "")
    md5 = entry.get("md5", "")

    # Resolve GameBanana entries that only pin an id.
    if gb_id and not url:
        try:
            meta = gb_primary_file(gb_id)
        except Exception as exc:
            err(f"{name}: GameBanana lookup failed: {exc}")
            return False
        url = meta["url"]
        filename = filename or f"{gb_id}-{meta['file']}"
        md5 = md5 or meta["md5"]

    if not url or not filename:
        err(f"{name}: entry needs both url and file (or a gamebanana_id)")
        return False

    dest = DOWNLOADS / subdir / filename

    if dest.exists():
        valid, detail = verify(dest, sha256, md5)
        if valid:
            ok(f"{name} cached ({human(dest.stat().st_size)})")
            return True
        warn(f"{name}: cached copy invalid, re-fetching\n    {detail}")
        dest.unlink()

    info(f"fetching {name} ...")
    try:
        download(url, dest)
    except Exception as exc:
        err(f"{name}: {exc}")
        return False

    # Applies to explicitly pinned urls too, not just id-resolved ones. An
    # Armstrong entry with a hardcoded url slipped a 489-byte readme past the
    # check in gb_primary_file, because that only runs on the id path.
    if dest.stat().st_size < 64 * 1024 and README_RE.search(dest.name):
        err(f"{name}: downloaded {dest.name} ({dest.stat().st_size:,} B) -- that "
            f"is a readme, not a mod. The real payload is hosted elsewhere.")
        dest.unlink()
        return False

    valid, detail = verify(dest, sha256, md5)
    if not valid:
        err(f"{name}: downloaded file failed verification\n    {detail}")
        err("    refusing to keep it -- a mod that changed upstream must be "
            "re-pinned deliberately, not silently accepted")
        dest.unlink()
        return False

    size = human(dest.stat().st_size)
    if not sha256 or sha256 == "PENDING":
        # Surface the hash so it can be pinned in the manifest.
        warn(f"{name} fetched ({size}) but is UNPINNED -- record this sha256:")
        print(f"    sha256 = \"{sha256_file(dest)}\"")
    else:
        ok(f"{name} fetched and verified ({size})")
    return True


def main() -> int:
    manifest = load_manifest()
    roster = load_roster()

    entries: list[tuple[dict, str]] = []
    entries += [(e, "upstream") for e in manifest.get("upstream", [])]
    entries += [(e, "mods") for e in manifest.get("mod", [])]
    entries += [(e, "mods") for e in roster.get("mod", [])]

    if not entries:
        die("nothing to fetch -- manifest.toml has no entries")

    info(f"{len(entries)} pinned component(s)")
    failures = [e[0].get("name", "?") for e in entries if not handle(*e)]

    print()
    if failures:
        err(f"{len(failures)} of {len(entries)} failed: {', '.join(failures)}")
        return 1
    ok(f"all {len(entries)} components present and verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
