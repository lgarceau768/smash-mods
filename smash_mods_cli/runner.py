"""Subprocess launcher for the scripts this CLI wraps.

Every wrapped script keeps working completely unchanged when invoked
directly -- this module just assembles the same argv a human would type and
runs it, with stdio *inherited* rather than captured. That matters
concretely for deploy.sh and backup.sh: they hand rsync `--info=progress2`
for a live-redrawn progress bar, and capturing/buffering that output would
turn it into a wall of carriage-return garbage instead of an updating line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .paths import REPO_ROOT


def run(argv: list[str | Path]) -> int:
    """Run *argv* as a subprocess from the repo root, streaming its own stdio.

    Returns the subprocess's exit code unchanged, so callers can exit with it
    directly: `smash-mods deploy ...` reports the same status as running
    `./scripts/deploy.sh ...` by hand would.
    """
    proc = subprocess.run([str(a) for a in argv], cwd=REPO_ROOT, check=False)
    return proc.returncode
