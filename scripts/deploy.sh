#!/usr/bin/env bash
#
# Copy a staged profile onto the Switch SD card.
#
# This is the only step that touches removable media, so it is deliberately
# hard to point at the wrong thing: it refuses any target that does not look
# like a Switch SD root, it is a dry run unless you pass --commit, and it only
# ever deletes inside the two directories this repo owns. Your saves, NAND
# backups and other homebrew live on that card and are never touched.
#
#   ./scripts/deploy.sh                      # dry run, auto-detected card
#   ./scripts/deploy.sh --commit             # actually write
#   ./scripts/deploy.sh --profile list      # show available profiles
#   ./scripts/deploy.sh --profile hdr --commit
#   ./scripts/deploy.sh --target /mnt/sd --commit
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TITLE_ID="01006A800016E000"

STALE_TITLES=()
PROFILE="roster"
TARGET=""
COMMIT=0
BASE_ONLY=0

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; BLU=$'\033[34m'; BLD=$'\033[1m'; OFF=$'\033[0m'
[[ -t 1 ]] || { RED=""; YEL=""; GRN=""; BLU=""; BLD=""; OFF=""; }

info() { printf '%s::%s %s\n' "$BLU" "$OFF" "$*"; }
ok()   { printf '%sOK%s %s\n' "$GRN" "$OFF" "$*"; }
warn() { printf '%sWARN%s %s\n' "$YEL" "$OFF" "$*"; }
die()  { printf '%sERROR%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

usage() { sed -n '3,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)   PROFILE="${2:?--profile needs a value}"; shift 2 ;;
    --target)    TARGET="${2:?--target needs a path}"; shift 2 ;;
    --commit)    COMMIT=1; shift ;;
    --base-only) BASE_ONLY=1; shift ;;
    -h|--help)   usage ;;
    *)           die "unknown argument: $1 (try --help)" ;;
  esac
done

KNOWN_PROFILES="$(python3 -c "
import sys; sys.path.insert(0,'$ROOT/scripts')
from common import load_profiles
print(' '.join(sorted(load_profiles())))" 2>/dev/null)"
[[ -n "$KNOWN_PROFILES" ]] || die "could not read profiles.toml"

if [[ "$PROFILE" == "list" ]]; then
  python3 -c "
import sys; sys.path.insert(0,'$ROOT/scripts')
from common import load_profiles
for n,p in sorted(load_profiles().items()):
    tag = 'self-contained' if p.get('selfcontained') else 'layers: '+', '.join(p.get('layers',[]))
    st = p.get('status','untested')
    mark = {'working':'[TESTED]','broken':'[BROKEN]'}.get(st,'[untested]')
    print(f'  {n:<12} {mark:<11} {p.get(\"description\",\"\")}')
    print(f'  {\"\":<12} {\"\":<11} {tag}')
    if p.get('tested_on'): print(f'  {\"\":<12} {\"\":<11} tested {p[\"tested_on\"]}: {p.get(\"tested_notes\",\"\")[:90]}')"
  exit 0
fi

grep -qw -- "$PROFILE" <<<"$KNOWN_PROFILES" \
  || die "unknown profile '$PROFILE'.
    Known: $KNOWN_PROFILES
    ('./scripts/deploy.sh --profile list' describes each one)"

SRC="$ROOT/build/$PROFILE"
[[ -d "$SRC" ]] || die "profile '$PROFILE' is not staged. Run: ./scripts/build.sh"

# --- locate the card -------------------------------------------------------
# A Switch SD root always has Nintendo/ (created by the console itself). Using
# that as the signature means a mistyped path cannot resolve to a home dir or
# the wrong disk.
looks_like_switch_sd() { [[ -d "$1/Nintendo" ]]; }

if [[ -z "$TARGET" ]]; then
  info "looking for a mounted Switch SD card ..."
  mapfile -t CANDIDATES < <(
    for base in "/media/$USER" /media /run/media/"$USER" /mnt; do
      [[ -d "$base" ]] || continue
      for d in "$base"/*; do
        [[ -d "$d" ]] && looks_like_switch_sd "$d" && echo "$d"
      done
    done | sort -u
  )
  case "${#CANDIDATES[@]}" in
    0) die "no Switch SD card found.
    Mount the card, or pass --target /path/to/card.
    (Looked under /media/$USER, /media, /run/media/$USER, /mnt for a
     directory containing Nintendo/.)" ;;
    1) TARGET="${CANDIDATES[0]}"; ok "found card: $TARGET" ;;
    *) printf '%s\n' "${CANDIDATES[@]}" >&2
       die "multiple candidate cards found -- disambiguate with --target" ;;
  esac
else
  looks_like_switch_sd "$TARGET" \
    || die "'$TARGET' does not look like a Switch SD root (no Nintendo/ directory).
    Refusing to write. Pass the card's mount point, not a subdirectory."
fi

[[ -w "$TARGET" ]] || die "no write permission on $TARGET"

# --- filesystem sanity -----------------------------------------------------
FSTYPE="$(findmnt -no FSTYPE --target "$TARGET" 2>/dev/null || echo unknown)"
case "$FSTYPE" in
  vfat|msdos) ok "filesystem: FAT32 ($FSTYPE)" ;;
  exfat)      warn "filesystem is exFAT. The Switch corrupts exFAT cards with
     some regularity, and this writes thousands of small files. FAT32 is
     strongly preferred. Continuing, but back the card up first." ;;
  *)          warn "unrecognised filesystem '$FSTYPE' -- expected vfat/FAT32" ;;
esac

AVAIL_KB="$(df -Pk "$TARGET" | awk 'NR==2{print $4}')"

# --- verify before writing -------------------------------------------------
# Never copy an unverified tree, even if the caller ran build.sh earlier and
# then edited a workspace by hand.
# Verify the union of the profile's layers -- that combination is what ships,
# and a conflict between a reskin layer and the roster only shows up there.
PROFILE_STATUS="$(python3 -c "
import sys; sys.path.insert(0,'$ROOT/scripts')
from common import load_profiles
print(load_profiles().get('$PROFILE',{}).get('status','untested'))" 2>/dev/null)"
case "$PROFILE_STATUS" in
  working) ok "profile '$PROFILE' is marked TESTED on hardware" ;;
  broken)  warn "profile '$PROFILE' is marked BROKEN. Deploying anyway is your call." ;;
  *)       warn "profile '$PROFILE' has never been tested on hardware.
     Verification only proves the files are consistent -- it cannot prove the
     game boots. Keep a known-good profile to fall back to." ;;
esac

info "re-verifying profile '$PROFILE' before writing ..."
python3 "$ROOT/scripts/verify.py" --profile "$PROFILE" \
  || die "verification failed -- refusing to deploy. Fix the errors above."

# --- the copy --------------------------------------------------------------
# Only these two paths are owned by this repo. --delete is scoped to them so
# stale mods from the other profile are removed without ever touching
# Nintendo/, bootloader/, switch/, or other titles under atmosphere/contents/.
# Derive owned paths from what the profile actually contains. HDR ships a
# patch for title 0100000000000013 (the `hid` system module) in addition to the
# game's own title. Hardcoding one title id meant that patch was never
# installed with HDR, and -- far worse -- never REMOVED when switching back to
# roster, leaving a system-module exefs patch resident on every boot of the
# console. A version-mismatched sysmodule patch is a classic boot-loop cause.
OWNED=()
if [[ -d "$SRC/atmosphere/contents" ]]; then
  for d in "$SRC/atmosphere/contents"/*/; do
    [[ -d "$d" ]] && OWNED+=( "atmosphere/contents/$(basename "$d")/" )
  done
fi
# Also claim title dirs a PREVIOUS deploy of the other profile left behind, so
# switching profiles cleans up rather than accumulating.
for tid in "$TITLE_ID" 0100000000000013; do
  [[ -d "$TARGET/atmosphere/contents/$tid" ]] || continue
  [[ " ${OWNED[*]} " == *" atmosphere/contents/$tid/ "* ]] && continue
  # Present on the card, absent from this profile. rsync cannot remove it --
  # there is no source directory to sync from, so the loop would skip it
  # entirely. It has to be deleted explicitly.
  STALE_TITLES+=( "$tid" )
done
(( BASE_ONLY )) || OWNED+=( "ultimate/" )

# Size check, now that OWNED is known. Doing this against the whole of $SRC
# demanded 8.2GB of headroom to copy 2.6MB of plugins with --base-only, and
# ignored the space --delete is about to reclaim, so re-deploying a roster onto
# a card already holding that same roster was refused for space it did not need.
NEED_KB=0
for path in "${OWNED[@]}"; do
  [[ -d "$SRC/$path" ]] || continue
  NEED_KB=$(( NEED_KB + $(du -sk "$SRC/$path" | awk '{print $1}') ))
done
for path in "${OWNED[@]}"; do
  [[ -d "$TARGET/$path" ]] || continue
  AVAIL_KB=$(( AVAIL_KB + $(du -sk "$TARGET/$path" | awk '{print $1}') ))
done
if (( NEED_KB > AVAIL_KB )); then
  die "not enough space: need $((NEED_KB/1024))MB, have $((AVAIL_KB/1024))MB usable on $TARGET"
fi

# Preserve ARCropolis's own config and runtime state across deploys. Both live
# inside paths we own with --delete on, so they were being wiped every commit:
# the auto-update setting reverted to ON each time (a step that undid itself),
# in-game per-mod enable/disable choices were lost, and conflicts.json -- the
# only on-console diagnostic naming a file conflict -- was destroyed.
# Preserve the USER'S SETTINGS, not ARCropolis's derived state.
#
# Excluding all of arcropolis/ was too broad: it also preserved
# cache/<ver>/config_merged.cache plus share.lut and unshare.lut, which are
# generated by merging every mod's config.json. Those describe the arc
# filesystem for the mod set that produced them, so carrying a stale copy across
# a mod-set change hands ARCropolis a layout that no longer matches what is on
# the card. Only config/ holds user choices; cache/ must be rebuilt.
RSYNC_FLAGS=( -rlt --delete --human-readable --stats
              --exclude 'arcropolis.toml'
              --exclude 'arcropolis/config/'
              --exclude 'arcropolis/logs/' )
(( COMMIT )) || RSYNC_FLAGS+=( --dry-run )
(( COMMIT )) && RSYNC_FLAGS+=( --info=progress2 )

echo
info "profile:  ${BLD}$PROFILE${OFF}"
info "source:   $SRC"
info "target:   $TARGET"
info "size:     $((NEED_KB/1024))MB"
(( COMMIT )) || warn "DRY RUN -- nothing will be written. Add --commit to apply."
echo

for path in "${OWNED[@]}"; do
  [[ -d "$SRC/$path" ]] || continue
  info "syncing $path"
  # Only create directories when actually committing -- a dry run must not
  # touch the card at all. Written as an if-block, not `(( COMMIT )) && ...`,
  # because that expression evaluates to 1 on a dry run and `set -e` would
  # abort the script.
  if (( COMMIT )); then mkdir -p "$TARGET/$path"; fi
  # An earlier version piped rsync into grep with `|| true`, which discarded
  # rsync's exit status entirely. A card that filled up, threw I/O errors, or
  # was pulled mid-copy still reported "done. Safe to unmount." -- the worst
  # possible outcome for the one operation that touches removable media.
  if ! rsync "${RSYNC_FLAGS[@]}" "$SRC/$path" "$TARGET/$path"; then
    die "rsync FAILED on $path.
    The card is now in an inconsistent state -- do NOT boot it.
    Re-run this deploy, or restore with:
      ./scripts/backup.sh --restore <backup> --commit"
  fi
done

# --base-only means "base stack, no mods" -- the isolation test in the bring-up
# sequence and the first move when debugging a black screen. Simply omitting
# ultimate/ from OWNED left every previously-deployed mod in place, making it a
# no-op in exactly the situation you reach for it.
if (( BASE_ONLY )) && [[ -d "$TARGET/ultimate/mods" ]]; then
  n=$(find "$TARGET/ultimate/mods" -mindepth 1 -maxdepth 1 | wc -l)
  if (( n > 0 )); then
    if (( COMMIT )); then
      info "clearing $n mod(s) from the card for base-only isolation"
      rm -rf "${TARGET:?}/ultimate/mods"
      mkdir -p "$TARGET/ultimate/mods"
    else
      warn "would clear $n mod(s) from ultimate/mods for base-only isolation"
    fi
  fi
fi

# Title patches the other profile installed that this one does not use. HDR
# patches 0100000000000013 (the `hid` system module); leaving that behind means
# a sysmodule patch loads on every boot of the console, not just in Smash, and
# a version-mismatched one is a classic boot-loop cause.
for tid in "${STALE_TITLES[@]:-}"; do
  [[ -n "$tid" ]] || continue
  if (( COMMIT )); then
    warn "removing title patch left by the other profile: $tid"
    rm -rf "${TARGET:?}/atmosphere/contents/$tid"
  else
    warn "would remove title patch left by the other profile: $tid"
  fi
done

if (( ! COMMIT )); then
  echo
  warn "dry run complete. Re-run with --commit to write."
  exit 0
fi

echo
info "flushing writes to card (this can take a while) ..."
sync
ok "done. ${BLD}Safe to unmount.${OFF}"
echo
cat <<EOF
Next steps:
  1. Unmount the card cleanly, then put it back in the Switch.
  2. Launch Smash. The title screen should show an ARCropolis version string.
  3. FIRST BOOT ONLY: open the ARCropolis menu and turn OFF auto-update.
     It defaults to ON and can pull a build that no longer matches your
     pinned game version.
EOF
