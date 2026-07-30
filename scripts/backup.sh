#!/usr/bin/env bash
#
# Create and restore a full snapshot of the Switch SD card.
#
# Run this BEFORE ./scripts/deploy.sh --commit. It gives you a restore point
# covering everything on the card: saves, NAND backups, other homebrew, and
# whatever mod state is already there.
#
# Creating a backup NEVER writes to the card -- every operation in backup mode
# is a read. Only --restore writes, and only with --commit.
#
#   ./scripts/backup.sh                      # create a backup (archive mode)
#   ./scripts/backup.sh --mode tree          # plain directory mirror instead
#   ./scripts/backup.sh --mode image         # raw block image (needs sudo)
#   ./scripts/backup.sh --list               # show existing backups
#   ./scripts/backup.sh --verify <path>      # re-check a backup's integrity
#   ./scripts/backup.sh --restore <path>     # dry run
#   ./scripts/backup.sh --restore <path> --commit
#
set -euo pipefail

# Re-exec from a private copy before doing anything else.
#
# Bash reads a script incrementally from disk by byte offset, so editing this
# file while it is running shifts everything after the current read position and
# the process dies on garbage -- which is exactly what happened during a 3-hour
# backup: the archive finished, then the script hit "syntax error near
# unexpected token" and never wrote its manifest or verified anything.
# Running from a copy makes the original safe to edit at any time.
if [[ -z "${SMASH_BACKUP_REEXEC:-}" ]]; then
  _self_copy="$(mktemp -t backup-sh-XXXXXX)"
  cat "${BASH_SOURCE[0]}" > "$_self_copy"
  trap 'rm -f "$_self_copy"' EXIT
  SMASH_BACKUP_REEXEC=1 exec bash "$_self_copy" "$@"
fi

BACKUP_ROOT="${SWITCH_BACKUP_DIR:-$HOME/switch-sd-backups}"
MODE="archive"
ACTION="create"
ARG=""
COMMIT=0
EXACT=0
TARGET=""

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; BLU=$'\033[34m'; BLD=$'\033[1m'; OFF=$'\033[0m'
[[ -t 1 ]] || { RED=""; YEL=""; GRN=""; BLU=""; BLD=""; OFF=""; }
info() { printf '%s::%s %s\n' "$BLU" "$OFF" "$*"; }
ok()   { printf '%sOK%s %s\n' "$GRN" "$OFF" "$*"; }
warn() { printf '%sWARN%s %s\n' "$YEL" "$OFF" "$*"; }
die()  { printf '%sERROR%s %s\n' "$RED" "$OFF" "$*" >&2; exit 1; }

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)    MODE="${2:?}"; shift 2 ;;
    --target)  TARGET="${2:?}"; shift 2 ;;
    --list)    ACTION="list"; shift ;;
    --verify)  ACTION="verify"; ARG="${2:?--verify needs a backup path}"; shift 2 ;;
    --restore) ACTION="restore"; ARG="${2:?--restore needs a backup path}"; shift 2 ;;
    --commit)  COMMIT=1; shift ;;
    --exact)   EXACT=1; shift ;;
    -h|--help) usage ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

# --- locate the card (same signature as deploy.sh) -------------------------
find_card() {
  local base d
  for base in "/media/$USER" /media "/run/media/$USER" /mnt; do
    [[ -d "$base" ]] || continue
    for d in "$base"/*; do
      [[ -d "$d/Nintendo" ]] && echo "$d"
    done
  done | sort -u
}

resolve_card() {
  if [[ -n "$TARGET" ]]; then
    [[ -d "$TARGET/Nintendo" ]] || die "'$TARGET' has no Nintendo/ -- not a Switch SD root"
    CARD="$TARGET"
    return
  fi
  mapfile -t found < <(find_card)
  case "${#found[@]}" in
    0) die "no Switch SD card found.
    Plug the card in and wait for it to mount, then re-run.
    (Looked under /media/$USER, /media, /run/media/$USER, /mnt for a
     directory containing Nintendo/.)  Or pass --target /path/to/card." ;;
    1) CARD="${found[0]}" ;;
    *) printf '%s\n' "${found[@]}" >&2; die "multiple cards found -- use --target" ;;
  esac
}

# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------
if [[ "$ACTION" == "list" ]]; then
  [[ -d "$BACKUP_ROOT" ]] || die "no backups yet ($BACKUP_ROOT does not exist)"
  info "backups in $BACKUP_ROOT"
  for d in "$BACKUP_ROOT"/*/; do
    [[ -f "$d/manifest.txt" ]] || continue
    printf '\n%s%s%s\n' "$BLD" "$(basename "$d")" "$OFF"
    sed 's/^/  /' "$d/manifest.txt"
  done
  exit 0
fi

# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
# Accept either the backup directory or the payload file inside it -- pasting
# the path zstd printed is the obvious thing to do, and rejecting it is just
# rude.
if [[ -f "$ARG" ]]; then
  ARG="$(dirname "$ARG")"
fi

if [[ "$ACTION" == "verify" ]]; then
  [[ -d "$ARG" ]] || die "no such backup: $ARG"
  [[ -f "$ARG/manifest.txt" ]] || die "$ARG has no manifest.txt -- not a backup"
  info "verifying $ARG"
  cat "$ARG/manifest.txt" | sed 's/^/  /'
  echo
  if [[ -f "$ARG/sdcard.tar.zst" ]]; then
    # One pass, not two: zstd verifies its checksums while decompressing, so a
    # separate `zstd -t` beforehand just re-reads the whole archive for nothing.
    # On a 169GB backup that was ~20 wasted minutes.
    info "verifying archive (one pass; reads the whole archive) ..."
    n=$(set -o pipefail; zstd -dc "$ARG/sdcard.tar.zst" | tar -tf - | wc -l) \
      || die "archive is CORRUPT -- do not rely on this backup"
    ok "checksums validated during decompression"
    want=$(grep -oP 'entries:\s*\K[0-9]+' "$ARG/manifest.txt" || echo "")
    echo "  entries now: $n  recorded: ${want:-?}"
    # tar records a './' root entry that `find -mindepth 1` does not count, so
    # the archive legitimately holds one more entry than the card did. Fewer
    # entries than recorded is the real failure.
    if [[ -n "$want" ]] && (( n < want )); then
      die "archive has fewer entries than recorded ($n < $want) -- backup is incomplete"
    fi
    ok "archive verified"
  elif [[ -f "$ARG/sdcard.img.zst" ]]; then
    zstd -t "$ARG/sdcard.img.zst" || die "image is CORRUPT"
    ok "image verified"
  elif [[ -d "$ARG/tree" ]]; then
    n=$(find "$ARG/tree" | wc -l)
    echo "  entries now: $n"
    ok "tree present"
  else
    die "no backup payload found in $ARG"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------
if [[ "$ACTION" == "restore" ]]; then
  [[ -d "$ARG" ]] || die "no such backup: $ARG"
  resolve_card
  echo
  warn "${BLD}RESTORE${OFF} — this writes to the card and overwrites its contents."
  info "backup: $ARG"
  info "card:   $CARD"
  (( EXACT )) && warn "--exact: files on the card that are NOT in the backup will be DELETED"
  cat "$ARG/manifest.txt" 2>/dev/null | sed 's/^/  /'
  echo

  if (( ! COMMIT )); then
    warn "DRY RUN — nothing written. Add --commit to actually restore."
    if [[ -d "$ARG/tree" ]]; then
      rsync -rlt --dry-run --stats $( ((EXACT)) && echo --delete ) \
        "$ARG/tree/" "$CARD/" | tail -12
    else
      info "archive restore would extract $(basename "$ARG"/sdcard.*) over $CARD"
    fi
    exit 0
  fi

  read -r -p "Type RESTORE to confirm: " reply
  [[ "$reply" == "RESTORE" ]] || die "aborted"

  if [[ -f "$ARG/sdcard.tar.zst" ]]; then
    info "extracting archive to card ..."
    zstd -dc "$ARG/sdcard.tar.zst" | tar -xf - -C "$CARD"
  elif [[ -d "$ARG/tree" ]]; then
    info "mirroring tree to card ..."
    rsync -rlt --info=progress2 $( ((EXACT)) && echo --delete ) \
      "$ARG/tree/" "$CARD/"
  elif [[ -f "$ARG/sdcard.img.zst" ]]; then
    imgdev="$(cat "$ARG/image-device.txt" 2>/dev/null || echo "/dev/sdX")"
    die "raw image restore must be done deliberately with dd.
    This image was taken from: $imgdev  (whole device, including partition table)
    Confirm the card's CURRENT device with lsblk -- it may differ between
    sessions -- then:
      zstd -dc '$ARG/sdcard.img.zst' | sudo dd of=<device> bs=4M status=progress
    Write to the whole device (/dev/sdb), NOT a partition (/dev/sdb1).
    This overwrites the ENTIRE device."
  else
    die "no payload in $ARG"
  fi
  sync
  ok "restore complete. Safe to unmount."
  exit 0
fi

# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------
resolve_card
FSTYPE="$(findmnt -no FSTYPE --target "$CARD" 2>/dev/null || echo unknown)"
SRCDEV="$(findmnt -no SOURCE --target "$CARD" 2>/dev/null || echo unknown)"
LABEL="$(basename "$CARD")"

# Create the backup root first: df on a non-existent path fails, and under
# `set -e` that aborts the script before anything is printed.
mkdir -p "$BACKUP_ROOT" || die "cannot create backup directory $BACKUP_ROOT"

USED_KB=$(df -Pk "$CARD" | awk 'NR==2{print $3}')
CARD_KB=$(df -Pk "$CARD" | awk 'NR==2{print $2}')
HOST_KB=$(df -Pk "$BACKUP_ROOT" | awk 'NR==2{print $4}')
[[ -n "$HOST_KB" ]] || die "cannot determine free space at $BACKUP_ROOT"

echo
info "card:        $CARD"
info "device:      $SRCDEV  ($FSTYPE)"
info "capacity:    $((CARD_KB/1024/1024)) GB"
info "used:        $((USED_KB/1024/1024)) GB"
info "host free:   $((HOST_KB/1024/1024)) GB   (backups go to $BACKUP_ROOT)"
echo

case "$MODE" in
  archive|tree)
    NEED_KB=$USED_KB
    # Game assets (nutexb/nus3audio/nuanmb) are already compressed, so assume
    # only ~10% shrink rather than the 40% a generic estimate would suggest.
    [[ "$MODE" == "archive" ]] && NEED_KB=$((USED_KB * 90 / 100))
    ;;
  image)
    NEED_KB=$((CARD_KB * 90 / 100))
    warn "image mode copies the ENTIRE partition ($((CARD_KB/1024/1024)) GB), not just used space."
    warn "It needs sudo and is only worth it if you want a bit-exact restore."
    ;;
  *) die "unknown mode '$MODE' (archive|tree|image)" ;;
esac

if (( NEED_KB > HOST_KB )); then
  die "not enough room for the backup.
    estimated need: $((NEED_KB/1024/1024)) GB
    host free:      $((HOST_KB/1024/1024)) GB
    Free some space, or set SWITCH_BACKUP_DIR to a bigger disk, e.g.
      SWITCH_BACKUP_DIR=/mnt/BigBeanDrive/switch-backups ./scripts/backup.sh"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$STAMP"
mkdir -p "$DEST"

info "counting files on card (read-only) ..."
ENTRIES=$(find "$CARD" -mindepth 1 2>/dev/null | wc -l)
info "$ENTRIES entries to back up"
echo

START=$(date +%s)
case "$MODE" in
  archive)
    info "creating compressed archive (nothing is written to the card) ..."
    # -C into the card so paths in the archive are relative to its root,
    # which makes restore a plain extract with no path surgery.
    tar -cf - -C "$CARD" . \
      | zstd -T0 -3 -o "$DEST/sdcard.tar.zst"
    PAYLOAD="$DEST/sdcard.tar.zst"
    ;;
  tree)
    info "mirroring card to a plain directory ..."
    mkdir -p "$DEST/tree"
    rsync -rlt --info=progress2 "$CARD/" "$DEST/tree/"
    PAYLOAD="$DEST/tree"
    ;;
  image)
    [[ "$SRCDEV" == /dev/* ]] || die "cannot determine block device for $CARD"
    # findmnt reports the PARTITION (/dev/sdb1). Imaging the partition but
    # restoring to the whole device -- as the restore hint used to say -- writes
    # filesystem data over the MBR and partition table, leaving an unpartitioned
    # card the Switch cannot read. Image the whole device so that the image and
    # the restore target describe the same thing.
    PARENT_NAME="$(lsblk -no PKNAME "$SRCDEV" 2>/dev/null || true)"
    if [[ -n "$PARENT_NAME" ]]; then
      IMGDEV="/dev/$PARENT_NAME"
      info "imaging whole device $IMGDEV (partition was $SRCDEV)"
    else
      IMGDEV="$SRCDEV"
      warn "could not resolve a parent device; imaging $IMGDEV directly"
    fi
    info "reading raw image from $IMGDEV (requires sudo) ..."
    sudo dd if="$IMGDEV" bs=4M status=progress \
      | zstd -T0 -3 -o "$DEST/sdcard.img.zst"
    echo "$IMGDEV" > "$DEST/image-device.txt"
    PAYLOAD="$DEST/sdcard.img.zst"
    ;;
esac
ELAPSED=$(( $(date +%s) - START ))

SIZE_H=$(du -sh "$PAYLOAD" | cut -f1)
{
  echo "created:   $(date -Is)"
  echo "mode:      $MODE"
  echo "card:      $CARD"
  echo "label:     $LABEL"
  echo "device:    $SRCDEV"
  echo "fstype:    $FSTYPE"
  echo "capacity:  $((CARD_KB/1024/1024)) GB"
  echo "used:      $((USED_KB/1024/1024)) GB"
  echo "entries:   $ENTRIES"
  echo "payload:   $(basename "$PAYLOAD")"
  echo "size:      $SIZE_H"
  echo "duration:  ${ELAPSED}s"
} > "$DEST/manifest.txt"

echo
ok "backup complete: $DEST  ($SIZE_H in ${ELAPSED}s)"
echo
info "verifying now — a backup you haven't checked isn't a backup"
if [[ "$MODE" == "archive" ]]; then
  zstd -t "$PAYLOAD" || die "archive failed integrity check"
  n=$(zstd -dc "$PAYLOAD" | tar -tf - | wc -l)
  echo "  archive entries: $n   card entries: $ENTRIES"
  # tar adds the './' root entry, so allow a difference of one.
  if (( n < ENTRIES )); then
    die "archive has fewer entries than the card -- backup is INCOMPLETE"
  fi
  ok "archive verified"
elif [[ "$MODE" == "image" ]]; then
  zstd -t "$PAYLOAD" || die "image failed integrity check"
  ok "image verified"
else
  ok "tree written"
fi

cat <<EOF

${BLD}Restore point ready.${OFF}

  list:     ./scripts/backup.sh --list
  verify:   ./scripts/backup.sh --verify "$DEST"
  restore:  ./scripts/backup.sh --restore "$DEST"            # dry run
            ./scripts/backup.sh --restore "$DEST" --commit

You can now safely run:
  ./scripts/deploy.sh --commit
EOF
