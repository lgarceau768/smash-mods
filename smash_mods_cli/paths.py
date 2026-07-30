"""Shared path constants for the smash-mods CLI wrapper.

Nothing under scripts/, tests/, or the TOML configs is modified by this
package -- these are just the locations the wrapper needs to find and invoke
the existing tooling.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"

# scripts/common.py is a read-only dependency of the `profiles` command: it
# imports the helpers common.py already exposes (load_profiles, all_mods)
# rather than re-parsing profiles.toml by hand, so the table it renders can
# never drift from what deploy.sh --profile list or verify.py itself see.
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
