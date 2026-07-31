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
    """Every mod directory a profile installs.

    Selfcontained profiles are just every mod in their one workspace. Layered
    profiles merge their layers with later ones OVERWRITING earlier ones by
    mod directory name -- that is what stage_layered() does when it copies,
    and what the declared layer order is for. The linter has to model the
    same thing, or it reports conflicts between two copies of a mod where
    only one ever reaches the card (reskin/Skin-Marth vs nsfw/Skin-Marth
    produced 60+ phantom errors).
    """
    prof = load_profiles().get(profile)
    if not prof:
        return []
    if prof.get("selfcontained"):
        return all_mods(prof["selfcontained"])
    chosen: dict[str, Path] = {}
    for layer in prof.get("layers", []):
        for mod in all_mods(layer):
            chosen[mod.name] = mod
    return [chosen[k] for k in sorted(chosen)]


def profiles_including_workspace(workspace: str) -> list[str]:
    """Every profile that would install this workspace's mods -- as a layer,
    or as its selfcontained workspace. Lets a mod's detail view answer "is
    this mod part of any current profile" without the caller re-deriving
    profiles.toml's layer/selfcontained logic itself."""
    names = []
    for name, prof in load_profiles().items():
        if prof.get("selfcontained") == workspace or workspace in prof.get("layers", []):
            names.append(name)
    return sorted(names)


def load_roster() -> dict:
    """Roster is optional -- an empty roster is a valid (if boring) build."""
    if not ROSTER.exists():
        return {"mod": []}
    with ROSTER.open("rb") as fh:
        return tomllib.load(fh)


def roster_entry(mod_name: str) -> dict | None:
    """The [[mod]] entry in roster.toml matching an installed mod's directory
    name, if any -- e.g. to recover the gamebanana_id a workspace mod came
    from. Only mods actually pulled in through roster.toml/fetch.py have one;
    hand-placed mods don't."""
    entries = load_roster().get("mod", [])
    for m in entries:
        if m.get("name") == mod_name:
            return m
    # Workspace directories sometimes get an extra tag appended by hand after
    # unpacking (e.g. "Shadow-The-Hedgehog" -> "Shadow-The-Hedgehog-{Moveset}-
    # Shadow"), so fall back to a prefix match -- conservative enough to
    # avoid matching unrelated mods, unlike a substring-anywhere match would.
    lowered = mod_name.lower()
    for m in entries:
        name = m.get("name", "")
        if name and lowered.startswith(name.lower()):
            return m
    return None


def all_known_mods() -> list[dict]:
    """Every mod this tool knows about, fetched or not.

    Unifies workspace directories (already downloaded, in `workspaces/`) with
    roster.toml entries (curated picks that may not be fetched yet) into one
    deduplicated list, so a mod doesn't have to already be on disk to be
    browsable and reassignable -- a profile is a composition of workspaces,
    so "which workspace a mod targets" is what matters, whether or not it has
    actually been unpacked there yet.

    Each record: {"name", "path" (Path|None), "workspace" (str|None),
    "fetched" (bool), "gamebanana_id" (int|None)}. path is None exactly when
    fetched is False -- run Build to turn a pending pick into a real one.

    Keyed by (workspace, name), NOT name alone: mods can legitimately share a
    name across different workspaces by design (e.g. reskin/Skin-Marth vs
    nsfw/Skin-Marth, so a later profile layer can override the earlier one by
    name -- see profiles.toml's own header comment). Deduping by name alone
    would silently collapse two distinct, real mods into one record.
    """
    records: dict[tuple[str, str], dict] = {}
    fetched_names_by_workspace: dict[str, list[str]] = {}
    for workspace in list_workspaces():
        names = []
        for path in all_mods(workspace):
            entry = roster_entry(path.name)
            records[(workspace, path.name)] = {
                "name": path.name,
                "path": path,
                "workspace": workspace,
                "fetched": True,
                "gamebanana_id": entry.get("gamebanana_id") if entry else None,
            }
            names.append(path.name)
        fetched_names_by_workspace[workspace] = names

    for entry in load_roster().get("mod", []):
        name = entry.get("name")
        workspace = entry.get("workspace", "roster")
        if not name:
            continue
        key = (workspace, name)
        if key in records:
            continue
        # Same prefix-match fallback as roster_entry(), scoped to this
        # entry's own target workspace: a pending pick whose name is a prefix
        # of an already-fetched (and since-renamed) mod IN THAT WORKSPACE is
        # already represented above -- don't list it twice.
        lowered_name = name.lower()
        already_fetched = any(
            fetched.lower().startswith(lowered_name)
            for fetched in fetched_names_by_workspace.get(workspace, [])
        )
        if already_fetched:
            continue
        records[key] = {
            "name": name,
            "path": None,
            "workspace": workspace,
            "fetched": False,
            "gamebanana_id": entry.get("gamebanana_id"),
        }

    return sorted(records.values(), key=lambda r: (r["name"].lower(), r["workspace"] or ""))


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


def list_workspaces() -> list[str]:
    """Every workspace directory that actually exists on disk, sorted.

    Not a fixed list: workspaces/ is a symlinked data directory that gains
    new workspaces over time (e.g. a selfcontained total-conversion mod gets
    its own), so anything that needs "every workspace" must look at the
    filesystem rather than hardcode names that will drift out of date.
    """
    if not WORKSPACES.is_dir():
        return []
    return sorted(p.name for p in WORKSPACES.iterdir() if p.is_dir() and not p.name.startswith("."))


def mod_info(path: Path) -> dict:
    """Read a mod directory's optional info.toml. Empty dict if absent/unparseable.

    Fields seen in the wild: display_name, description, authors, category --
    none are guaranteed, so callers must treat every key as optional.
    """
    info_path = path / "info.toml"
    if not info_path.is_file():
        return {}
    try:
        with info_path.open("rb") as fh:
            return tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError):
        return {}
