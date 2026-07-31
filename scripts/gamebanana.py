"""GameBanana ProfilePage lookups, with an on-disk cache.

curate.py/curate_skins.py/curate_nsfw.py already fetch from this same API
when surveying candidates; this module adds a cached read path for a single
already-picked mod (by its pinned gamebanana_id in roster.toml), for the
TUI's mod-detail view -- so opening the same mod's detail repeatedly doesn't
refetch every time, and a flaky/offline GameBanana never blocks browsing.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from pathlib import Path

from common import ROOT

CACHE_DIR = ROOT / "build" / ".gamebanana_cache"
UA = "Mozilla/5.0 (smash-mods build script)"
PROFILE_URL = "https://gamebanana.com/apiv11/Mod/{}/ProfilePage"
CACHE_TTL = 7 * 24 * 3600  # a week -- submission metadata rarely changes


def has_fresh_cache(mod_id: int) -> bool:
    """Whether fetch_profile(mod_id) would return cached data without
    touching the network -- lets a caller decide whether to show a
    "fetching" message at all."""
    cache_path = CACHE_DIR / f"{mod_id}.json"
    if not cache_path.is_file():
        return False
    return time.time() - cache_path.stat().st_mtime < CACHE_TTL


def fetch_profile(mod_id: int, *, use_cache: bool = True) -> dict | None:
    """The GameBanana ProfilePage JSON for a mod id, or None if unreachable."""
    cache_path = CACHE_DIR / f"{mod_id}.json"
    if use_cache and cache_path.is_file():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_TTL:
            try:
                return json.loads(cache_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    try:
        req = urllib.request.Request(PROFILE_URL.format(mod_id), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data))
    return data


def screenshot_urls(profile: dict, *, size: str = "530") -> list[str]:
    """Screenshot URLs from a ProfilePage's _aPreviewMedia.

    GameBanana only generates a full set of resized variants (_sFile220,
    _sFile530, _sFile800, ...) for the primary screenshot -- secondary ones
    in the gallery often expose only a tiny 100x56 _sFile100 thumbnail. The
    bare _sFile (no size prefix) is always present and is the original,
    unresized upload, so it's the fallback here -- not _sFile100, which
    would otherwise silently render every screenshot past the first one at
    thumbnail resolution.
    """
    images = (profile.get("_aPreviewMedia") or {}).get("_aImages") or []
    urls = []
    for img in images:
        base = img.get("_sBaseUrl")
        file_name = img.get(f"_sFile{size}") or img.get("_sFile") or img.get("_sFile220") or img.get("_sFile100")
        if base and file_name:
            urls.append(f"{base}/{file_name}")
    return urls


def fetch_image_bytes(url: str, *, cache_key: str) -> Path | None:
    """Download (or reuse a cached copy of) an image, returning its local path."""
    cache_path = CACHE_DIR / cache_key
    if cache_path.is_file():
        return cache_path
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except Exception:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(data)
    return cache_path


def strip_html(text: str) -> str:
    """GameBanana's _sText is a small HTML subset (mostly <br>) -- flatten it
    to plain text rather than pulling in a full HTML parser dependency."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
