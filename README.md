# smash-mods

Builds ready-to-copy SD card **profiles** for a modded Super Smash Bros.
Ultimate (13.0.4) on a CFW Switch 1. Everything is downloaded, normalised,
linted and staged on this machine; the card only ever receives a verified tree,
and switching what's on the console is one deploy command.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/platform-linux-lightgrey)](#prerequisites)
[![uv](https://img.shields.io/badge/package%20manager-uv-de5fe9)](https://github.com/astral-sh/uv)

## Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Profiles](#profiles)
- [The two hard limits](#the-two-hard-limits-measured-not-folklore)
- [Base stack](#base-stack-manifesttoml-all-pinned--checksummed)
- [Commands](#commands)
- [Documentation](#documentation)
- [Save unlock](#save-unlock)
- [Debugging on-console crashes](#debugging-on-console-crashes)
- [Safety](#safety)
- [Adding more characters](#adding-more-characters)
- [Development](#development)
- [License](#license)

## Features

- Curated roster of **31+ added characters**, each a real CSS slot
- **6 SD card profiles** (`roster`, `fullreskin`, `chao5`, `nsfw`, `celshaded`,
  `hdr`) for different casts and visual styles
- Safety-checked staging: every archive is normalised, deduped and verified
  before it ever touches the card
- A linter (`verify.py`) that catches slot collisions, raw-file conflicts,
  zero-byte assets and more before deploy
- Plugin-budget enforcement against the OS's real 64-module cap
- One-command deploy with a **dry-run default** — nothing writes until you
  pass `--commit`
- Save unlock so every added character's host fighter is actually selectable
- A bisect toolkit (`toggle_mods`) for isolating a crash on the card itself

## Prerequisites

Targets **Linux** — the scripts assume `findmnt` and autodetect the card
under `/media` or `/run/media`.

- **Python 3.11+** (scripts use stdlib `tomllib`, no third-party deps)
- **[uv](https://github.com/astral-sh/uv)** — for the `smash-mods` CLI
- External tools shelled out to by one script or another:
  - `rsync` — deploy and backup
  - `p7zip` (`7z`) — archive unpacking
  - `unrar` — the only trusted RAR extractor (see
    [Debugging on-console crashes](#debugging-on-console-crashes))
  - `unar` / `lsar` — RAR fallback only, not trusted for correctness
  - `zstd`, `tar` — archive formats in the wild
  - `curl` — fetching pinned components
  - `findmnt` — SD card autodetection
  - standard `df`, `du`, `awk`, `find`

## Installation

```bash
git clone git@github.com:lgarceau768/smash-mods.git
cd smash-mods
uv sync
uv run smash-mods --help
```

For a global `smash-mods` command instead of prefixing every call with
`uv run`:

```bash
uv tool install --editable .
smash-mods --help
```

## Quickstart

```bash
smash-mods build                          # fetch + unpack + verify + stage all
smash-mods backup                         # restore point (read-only on the card)
smash-mods deploy --profile list          # see the menu
smash-mods deploy --profile roster        # dry run
smash-mods deploy --profile roster --commit
```

Every underlying script still works standalone, if you'd rather call it
directly — e.g. `./scripts/deploy.sh --profile roster`. See
[Commands](#commands) for the full mapping.

## Profiles

Defined in `profiles.toml` as ordered **layers** of mod workspaces; a later
layer replaces a same-named mod wholesale. Deploying a profile replaces the
previous one (rsync moves only the delta and never touches saves, `Nintendo/`,
homebrew, or other titles).

Per-profile test status lives in `profiles.toml` (`status = untested | working
| broken`) so a rebuild never resets what's known to work on hardware. Run
`smash-mods profiles` at any time for a live, colorized table of this same
data straight from `profiles.toml`.

| Profile | What you get | Plugins | Status |
|---|---|---|---|
| `roster` | Vanilla-balance Ultimate + **31 added characters**, each a real CSS slot | 30 | **working** |
| `fullreskin` | roster + a curated skin for ~86 vanilla fighters | 30 | **working** |
| `chao5` | CHAO5 UN-Balance: troll-mode cast + **10 merged added chars incl. Kamek** under one plugin | 1 | untested |
| `nsfw` | fullreskin with **22 adult-rated skins** swapped in where available | 30 | untested |
| `celshaded` | roster + Cel Shaded restyle (30+ fighters, one pack) | 30 | untested |
| `hdr` | HewDraw Remix full-cast overhaul (self-contained: ships its own forked ARCropolis/Skyline/Smashline) | its own | untested |

`workspaces/parked/` holds mods deliberately out of rotation (characters CHAO5
covers, plugin-budget cuts). Un-parking is a one-line `workspace = "roster"`
edit in `roster.toml`.

`chao5` sets `allow_raw_csk = true`: its raw `ui_chara_db.prc` is how a total
conversion registers its 206 added slots, not an oversight — but its
`soundlabelinfo.sli` is stripped, since that file demonstrably panics CSK.

## The two hard limits (measured, not folklore)

**Plugin cap — an OS constraint.** ARCropolis chainloads each mod's
`plugin.nro` via `nn::ro::LoadModule`; the OS caps a process at 64 loaded
modules, shared with the game's own code, Skyline, the 6 base plugins, and the
fighter modules loaded when a match starts. Measured here: the **34th** mod
plugin dies at boot regardless of which mod it is; **30 is the safe ceiling**
with match headroom. `verify.py` enforces this (warn >30, error >33). The only
way past it is author-side merged plugins — CHAO5 ships ten characters in one —
so packs, not stacking, are the route to more characters.

**Memory — mostly exonerated.** The boot death originally blamed on file-count
OOM happened on a build that ALSO had 35 plugins (over the cap) and two raw
file conflicts. After fixing those, fullreskin (~75k files) boots and plays —
so the plugin cap explains the earlier failures, and no file-count ceiling has
actually been hit yet. The bisect kit (`smash-mods toggle`, `tests/bisect/`)
remains for the day one appears.

## Base stack (manifest.toml, all pinned + checksummed)

Skyline (`exefs/`) · ARCropolis 4.0.8 · Smashline 2 v1.6.6 · **The CSK
Collection** 5.0.6 (registers every added character's CSS entry at runtime —
without it all of them are invisible) · One Slot Effects (13.0.4 build) ·
lib_paramconfig 6.5 (stops stacked movesets crashing each other) · nro_hook.
Plus the CSS 91+ layout fix as a roster mod.

Do **not** add `smush_extra_slots_effect_fix` — its own README says it crashes
next to Smashline 2; `verify.py` refuses the pairing.

## Commands

`smash-mods` is a Typer + Rich + Textual CLI that wraps every script in
`scripts/` as a subcommand -- a Smash Ultimate modpack creator and deployer.
Run `smash-mods` with no arguments for a full-screen interactive browser:
**All mods** (top of the left nav) opens a dedicated explorer for everything
you have data on, fetched or not: search, filter by workspace/status, sort,
and a live preview pane with a thumbnail (local or a cached/lazily-fetched
GameBanana screenshot) as you arrow through results -- with which profile(s)
each mod is part of and a way to move/retarget it to a different workspace.
Plain workspace browsing in the left nav filters the same data down to one
category; profiles show what actually deploys; and every action in the
ACTIONS section -- each with a plain-English description shown before you run
it -- streams its output live inside the app (no dropping to a bare
terminal). Curate surveys GameBanana and shows every candidate as a
checklist (all selected by default) before pinning your picks into
`roster.toml`. Or use `smash-mods <command> --help` for full flag docs on any
of them directly.

| Command | Wraps | Job |
|---|---|---|
| `smash-mods build [--skip-fetch]` | `build.sh` | Fetch + unpack + verify + stage all |
| `smash-mods deploy [--profile NAME] [--target PATH] [--commit] [--base-only]` | `deploy.sh` | Card write: auto-detect, dry-run default, verify-before-write |
| `smash-mods backup [--mode archive\|tree\|image] [--list] [--verify PATH] [--restore PATH] [--commit] [--exact]` | `backup.sh` | Full-card snapshot + verified restore |
| `smash-mods verify [--workspace NAME] [--profile NAME] [--strict]` | `verify.py` | The linter — see below |
| `smash-mods toggle status\|on <glob>\|off <glob>\|batch <file> on\|off\|plugins-off <mod...>\|plugins-on <mod...>` | `toggle_mods.sh` | Instant on/off of mods/plugins on the card, for bisecting |
| `smash-mods curate movesets\|skins\|nsfw [--report] [--write] [--limit N]` | `curate.py` / `curate_skins.py` / `curate_nsfw.py` | Survey GameBanana per category/fighter and pin picks into `roster.toml` |
| `smash-mods dedupe --layer NAME [--against NAME] [--commit]` | `dedupe_layer.py` | Resolve skin-vs-roster conflicts: strips global DB copies, inherited-slot animations, duplicate assets |
| `smash-mods unlock-save <path> [--commit]` | `unlock_save.py` | Unlock all 86 fighters in a JKSV-exported save |
| `smash-mods create-profile NAME --description TEXT [--layers a,b,c \| --selfcontained NAME] [--no-base]` | `profile_edit.py` | Add a new profile (layered or selfcontained) to `profiles.toml` |
| `smash-mods move-mod NAME --from WORKSPACE --to WORKSPACE` (or `--pending --to WORKSPACE` if not fetched yet) | `move_mod.py` | Move a mod to a different workspace, changing which profiles it's part of |
| `smash-mods create-workspace NAME` | `create_workspace.py` | Add a new, empty workspace -- needed before building a truly custom profile |
| `smash-mods profiles` | *(none — reads `profiles.toml` directly)* | Colorized table of all profiles + status |
| `smash-mods` *(no args)* | *(none)* | Full-screen Textual browser: All Mods, workspaces, profiles, roster picks, mod details (with GameBanana descriptions/images), profile creation, and every action above with live in-app output |
| `smash-mods --first-time` | *(none)* | Show the welcome/help tour (shown automatically the first time, and any time via `?` inside the app) |

Not surfaced as a subcommand but still used internally by `build`: `fetch.py`
(download every pinned component; sha256/md5 verified; polite rate-limit
backoff; refuses readme-only payloads) and `unpack.py` (normalise archives —
strip wrappers, pick declared `variant`, apply `exclude`; proves extracted
bytes match the archive's declared total).

Every underlying script in `scripts/` is still directly runnable on its own —
e.g. `./scripts/deploy.sh --profile roster` — for anyone who prefers not to
go through the package.

`verify.py` checks: slot collisions read from each mod's `config.json`
(`new-dir-infos` — the authoritative source; slots are routinely 3-digit),
raw-file conflicts (what ARCropolis actually prompts about; patch formats
exempt), the plugin budget, zero-byte binary assets, moveset-vs-reskin writes
to inherited vanilla slots, display-name typos (`bowser`→`koopa`), FAT32
hazards, nesting, junk. 19 regression fixtures: `python3 tests/test_verify.py`.

## Documentation

This README covers the pipeline and the pinned base stack; the interactive
CLI and its data model have their own focused docs:

- [`docs/data-model.md`](docs/data-model.md) — workspaces, profiles,
  roster.toml, and how a mod moves through them (curate → pin → fetch →
  workspace → profile → deploy). Read this first if "workspace" vs "profile"
  vs "roster.toml" isn't clicking yet.
- [`docs/tui.md`](docs/tui.md) — the full-screen interactive browser: the
  All Mods explorer, navigation, every action, the safety/confirm model, and
  keybindings.
- [`docs/architecture.md`](docs/architecture.md) — for anyone changing the
  code: how `scripts/`, `smash_mods_cli/commands.py`, and `smash_mods_cli/tui/`
  fit together, and the handful of non-obvious design decisions (why actions
  stream output live instead of shelling out to a raw terminal, why
  `textual-image` has to be imported before the app starts, etc).

## Save unlock

Added characters are only selectable if their **host** fighter is unlocked, so
a full unlock is functionally part of the roster. JKSV → back up Smash →
replug card → `smash-mods unlock-save <system_data.bin> --commit` → restore in
JKSV (same user profile!). Keep NSO cloud sync off for Smash. Pre-unlock save
archived at `Shared/switch-backups/`.

## Debugging on-console crashes

Trace logging is enabled (`ultimate/arcropolis/config/<uid>/<uid>/`:
`logging_level=Trace`, `log_to_file` flag). After a crash, replug the card and
read the newest file in `ultimate/arcropolis/logs/` — the last lines name the
phase and usually the file or plugin at fault. This is how every hard failure
here was actually diagnosed. Turn it off once stable (logs are ~14MB/boot).

Field notes, all learned the hard way:

- **A clean "The software was closed because an error occurred"** with no
  crash report = plugin-load failure or OOM, not a data error.
- **`ultimate/arcropolis/cache/` is derived state** — cleared automatically on
  deploy (config is preserved). If mods change by any other route, delete it.
- **A single mod crashing on select is usually an upstream bug.** Check the
  mod's GameBanana comments; roll back via `_aArchivedFiles` (the API lists
  old versions). Example in-tree: Magolor is pinned to 2025-11-16 because both
  newer builds crash on selection (reproduced + reported by others).
- **Extractors lie.** p7zip writes zero-filled trees for RAR5; `unar` silently
  zeroes ~15% of files. Only `unrar` is trusted, and `unpack.py` reconciles
  byte totals against the archive header regardless.
- **The console clock drifts offline** — file timestamps on the card are not
  evidence of when something ran.
- Don't extract to `/tmp` (tmpfs = RAM); the repo uses `.tmp/` on disk.

## Safety

Offline / local-play only. The ban mechanism isn't mod detection — it's
desync → disconnects → reports; this roster is decisively not wifi-safe by the
community's own standard. DNS-MITM (`atmosphere/hosts/emummc.txt`) + 90DNS as
defence in depth; 90DNS is per-network-profile, so re-apply on any new Wi-Fi.
ARCropolis auto-update phones a **non-Nintendo** host — turn it off in its
menu (once; deploys preserve the setting). Never let the console update Smash:
the whole stack is pinned to 13.0.4.

## Adding more characters

Interactively (recommended): `smash-mods` with no args → **ACTIONS → Curate**
→ pick movesets → review the checklist (everything survey found viable is
selected by default; uncheck what you don't want) → pin → you're prompted to
run Build right there.

Or by hand:

```bash
smash-mods curate movesets --report --limit 60   # browse
# add a [[mod]] entry to roster.toml (id + md5), then:
smash-mods build --skip-fetch
smash-mods deploy --profile roster --commit
```

Mind the plugin budget: each added character with a `plugin.nro` spends one of
~30 slots. Prefer merged packs when a mod family offers one. Small batches,
boot between them, keep the trace log on.

## Development

```bash
uv sync
python3 tests/test_verify.py   # regression suite, 19 fixtures
```

The `scripts/` directory has **zero third-party dependencies** — every script
is stdlib-only Python 3.11+ (using `tomllib` for TOML) or POSIX shell, so any
of them can be run directly without the package installed, e.g.
`python3 scripts/verify.py` or `./scripts/build.sh`. The `smash-mods` CLI
(Typer + Rich + Textual) is purely a front end over these scripts.

## License

MIT — see [LICENSE](LICENSE).
