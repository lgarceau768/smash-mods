"""Tracks whether this user has seen the welcome/help screen before.

Deliberately per-user (XDG config dir), not repo-local: the repo can be
re-cloned, moved, or shared across machines, but "have I been shown the
tour" is a fact about the person running it, not the checkout.
"""

from __future__ import annotations

import os
from pathlib import Path

_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "smash-mods"
_MARKER = _CONFIG_DIR / "first_run_seen"


def is_first_run() -> bool:
    return not _MARKER.is_file()


def mark_seen() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _MARKER.touch()
