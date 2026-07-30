"""Shared helpers: manifest loading, paths, logging, game-path knowledge."""

from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = ROOT / "downloads"
WORKSPACES = ROOT / "workspaces"
BUILD = ROOT / "build"
MANIFEST = ROOT / "manifest.toml"
PROFILES = ROOT / "profiles.toml"
ROSTER = ROOT / "roster.toml"

# Top-level directories the game recognises inside data.arc. A mod folder's
# immediate children must be drawn from this set -- anything else means the
# archive was nested one level too deep and ARCropolis will silently ignore it.
# This is the single most common reason a mod "does nothing".
# The trailing-semicolon names ("stream;", "prebuilt;") are not typos -- that
# is genuinely how they appear inside data.arc. Confirmed against the real
# roster archives, where stream; carries voice/music streams.
GAME_PATHS = {
    "fighter", "ui", "sound", "effect", "stage", "camera", "param",
    "prebuilt;", "stream;", "append", "assist", "item", "pokemon", "render",
    "spirits", "standard", "bgm", "movie", "message", "font",
}

# Files that are legitimately allowed at a mod root alongside game paths.
ALLOWED_ROOT_FILES = {"info.toml", "preview.webp", "readme.txt", "README.md"}

JUNK_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini", ".Trash-1000"}

# Characters FAT32 rejects in filenames.
FAT32_ILLEGAL = set('"*:<>?\\|')

# Internal fighter directory names. Many differ sharply from display names
# (Bowser is "koopa", Villager is "murabito", R.O.B. is "robot"), so a typo here
# is easy to make and silently produces a mod that loads nothing.
#
# Treated as ADVISORY: an unknown name produces a warning, not an error, because
# added-character mods sometimes introduce their own fighter directories.
KNOWN_FIGHTERS = {
    "mario", "donkey", "link", "samus", "samusd", "yoshi", "kirby", "fox",
    "pikachu", "luigi", "ness", "captain", "purin", "peach", "daisy", "koopa",
    "popo", "nana", "sheik", "zelda", "mariod", "pichu", "falco", "marth",
    "lucina", "younglink", "ganon", "mewtwo", "roy", "chrom", "gamewatch",
    "metaknight", "pit", "pitb", "szerosuit", "wario", "snake", "ike",
    "ptrainer", "pzenigame", "pfushigisou", "plizardon", "diddy", "lucas",
    "sonic", "dedede", "pikmin", "lucario", "robot", "toonlink", "wolf",
    "murabito", "rockman", "wiifit", "rosetta", "littlemac", "gekkouga",
    "miifighter", "miiswordsman", "miigunner", "palutena", "pacman", "reflet",
    "shulk", "koopajr", "duckhunt", "ryu", "ken", "cloud", "kamui", "bayonetta",
    "inkling", "ridley", "simon", "richter", "krool", "shizue", "gaogaen",
    "packun", "jack", "brave", "buddy", "dolly", "master", "tantan", "pickel",
    "edge", "eflame", "elight", "demon", "trail",
}

# Display name -> internal directory name, for every vanilla fighter whose two
# names differ. Using the display name is a silent no-op, and it is a distinct
# failure from a typo: "bowser" is lexically nowhere near "koopa", so edit
# distance cannot catch it. This is the more common mistake of the two.
DISPLAY_ALIASES = {
    "bowser": "koopa", "bowserjr": "koopajr", "villager": "murabito",
    "rob": "robot", "jigglypuff": "purin", "captainfalcon": "captain",
    "drmario": "mariod", "darksamus": "samusd", "darkpit": "pitb",
    "zerosuitsamus": "szerosuit", "megaman": "rockman", "greninja": "gekkouga",
    "robin": "reflet", "corrin": "kamui", "kingkrool": "krool",
    "isabelle": "shizue", "incineroar": "gaogaen", "piranhaplant": "packun",
    "joker": "jack", "hero": "brave", "banjo": "buddy", "terry": "dolly",
    "byleth": "master", "minmin": "tantan", "steve": "pickel",
    "sephiroth": "edge", "pyra": "eflame", "mythra": "elight",
    "kazuya": "demon", "sora": "trail", "wiifittrainer": "wiifit",
    "olimar": "pikmin", "rosalina": "rosetta", "iceclimbers": "popo",
    "ganondorf": "ganon", "mrgameandwatch": "gamewatch",
    "gameandwatch": "gamewatch", "pokemontrainer": "ptrainer",
    "squirtle": "pzenigame", "ivysaur": "pfushigisou",
    "charizard": "plizardon", "wiifit_trainer": "wiifit",
}

# The game's own character-select ceiling. Exceeding it without the CSS layout
# fix crashes the CSS; the 91+ fix raises the ceiling to 255.
CSS_DEFAULT_LIMIT = 91
CSS_EXPANDED_LIMIT = 255

# Vanilla costume slots are c00-c07. Added characters ride c08 and above.
VANILLA_SLOT_MAX = 7


class Colors:
    RED = "\033[31m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    BOLD = "\033[1m"
    OFF = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        for attr in ("RED", "YELLOW", "GREEN", "BLUE", "BOLD", "OFF"):
            setattr(cls, attr, "")


if not sys.stdout.isatty():
    Colors.disable()


def info(msg: str) -> None:
    print(f"{Colors.BLUE}::{Colors.OFF} {msg}")


def ok(msg: str) -> None:
    print(f"{Colors.GREEN}OK{Colors.OFF} {msg}")


def warn(msg: str) -> None:
    print(f"{Colors.YELLOW}WARN{Colors.OFF} {msg}")


def err(msg: str) -> None:
    print(f"{Colors.RED}ERROR{Colors.OFF} {msg}", file=sys.stderr)


def die(msg: str) -> None:
    err(msg)
    sys.exit(1)


def load_manifest() -> dict:
    if not MANIFEST.exists():
        die(f"missing {MANIFEST}")
    with MANIFEST.open("rb") as fh:
        return tomllib.load(fh)


def load_profiles() -> dict:
    """Profile definitions. Falls back to the two built-ins if absent."""
    if not PROFILES.exists():
        return {
            "roster": {"description": "Vanilla + added characters",
                       "base": True, "layers": ["roster"]},
            "hdr": {"description": "HewDraw Remix", "base": False,
                    "selfcontained": "hdr"},
        }
    with PROFILES.open("rb") as fh:
        return tomllib.load(fh)


def profile_mods(profile: str) -> list[Path]:
    """Every mod directory a profile installs, across all of its layers.

    Later layers come last so callers that care about precedence can rely on
    the order.
    """
    prof = load_profiles().get(profile)
    if not prof:
        return []
    # Later layers OVERWRITE earlier ones by mod directory name -- that is what
    # stage_layered() does when it copies, and what the declared layer order is
    # for. The linter has to model the same thing, or it reports conflicts
    # between two copies of a mod where only one ever reaches the card
    # (reskin/Skin-Marth vs nsfw/Skin-Marth produced 60+ phantom errors).
    chosen: dict[str, Path] = {}
    for layer in prof.get("layers", []):
        for mod in all_mods(layer):
            chosen[mod.name] = mod
    return [chosen[k] for k in sorted(chosen)]


def load_roster() -> dict:
    """Roster is optional -- an empty roster is a valid (if boring) build."""
    if not ROSTER.exists():
        return {"mod": []}
    with ROSTER.open("rb") as fh:
        return tomllib.load(fh)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n: int) -> str:
    x = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if x < 1024 or unit == "GB":
            return f"{x:.1f}{unit}" if unit != "B" else f"{int(x)}B"
        x /= 1024
    return f"{x:.1f}GB"


def all_mods(workspace: str) -> list[Path]:
    """Every installed mod directory in a workspace, sorted for stable output."""
    base = WORKSPACES / workspace
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
