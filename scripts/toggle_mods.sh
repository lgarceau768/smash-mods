#!/usr/bin/env bash
#
# Enable/disable mods ON THE CARD instantly, no copying.
#
# ARCropolis skips directories whose names start with a dot, so disabling a mod
# is a rename -- which is how we bisect memory-pressure problems in seconds
# instead of hours of rsync. Plugin files are toggled the same way, by renaming
# plugin.nro <-> plugin.nro.disabled.
#
#   ./scripts/toggle_mods.sh status
#   ./scripts/toggle_mods.sh off 'Skin-*'          # disable by glob
#   ./scripts/toggle_mods.sh on  'Skin-A*'         # enable by glob
#   ./scripts/toggle_mods.sh batch tests/bisect/skins-half1.txt on
#   ./scripts/toggle_mods.sh plugins-off Waluigi-Moveset Silver-Moveset
#   ./scripts/toggle_mods.sh plugins-on  Waluigi-Moveset
#
set -euo pipefail

find_card() {
  for base in "/media/$USER" /media "/run/media/$USER" /mnt; do
    [ -d "$base" ] || continue
    for d in "$base"/*/; do [ -d "$d/Nintendo" ] && { echo "${d%/}"; return; }; done
  done
  echo ""
}
CARD="${SMASH_CARD:-$(find_card)}"
[ -n "$CARD" ] && [ -d "$CARD/ultimate/mods" ] || { echo "no card mounted"; exit 1; }
MODS="$CARD/ultimate/mods"

cmd="${1:-status}"; shift || true
case "$cmd" in
  status)
    on=0; off=0; plug_on=0; plug_off=0
    for d in "$MODS"/*/;  do [ -d "$d" ] && on=$((on+1));  done
    for d in "$MODS"/.*/; do
      b=$(basename "$d"); [ "$b" = "." ] || [ "$b" = ".." ] && continue
      off=$((off+1))
    done
    plug_on=$(find "$MODS" -maxdepth 2 -name plugin.nro -not -path "$MODS/.*" | wc -l)
    plug_off=$(find "$MODS" -maxdepth 2 -name 'plugin.nro.disabled' | wc -l)
    echo "mods enabled : $on      disabled: $off"
    echo "plugins on   : $plug_on      off: $plug_off"
    echo
    echo "disabled mods:"
    for d in "$MODS"/.*/; do
      b=$(basename "$d"); { [ "$b" = "." ] || [ "$b" = ".." ]; } && continue
      echo "  ${b#.}"
    done
    echo "disabled plugins:"
    find "$MODS" -maxdepth 2 -name 'plugin.nro.disabled' | sed "s|$MODS/||; s|/plugin.nro.disabled||; s/^/  /"
    ;;
  off)
    pat="${1:?glob required}"; n=0
    cd "$MODS"
    for d in $pat/; do
      d="${d%/}"; [ -d "$d" ] || continue
      mv "$d" ".$d"; echo "  off: $d"; n=$((n+1))
    done
    sync; echo "$n disabled"
    ;;
  on)
    pat="${1:?glob required}"; n=0
    cd "$MODS"
    for d in .$pat/; do
      d="${d%/}"; [ -d "$d" ] || continue
      mv "$d" "${d#.}"; echo "  on:  ${d#.}"; n=$((n+1))
    done
    sync; echo "$n enabled"
    ;;
  batch)
    file="${1:?batch file}"; action="${2:?on|off}"; n=0
    while IFS= read -r m; do
      [ -z "$m" ] || [ "${m:0:1}" = "#" ] && continue
      if [ "$action" = on ] && [ -d "$MODS/.$m" ]; then mv "$MODS/.$m" "$MODS/$m"; n=$((n+1));
      elif [ "$action" = off ] && [ -d "$MODS/$m" ]; then mv "$MODS/$m" "$MODS/.$m"; n=$((n+1)); fi
    done < "$file"
    sync; echo "$n toggled $action from $(basename "$file")"
    ;;
  plugins-off)
    for m in "$@"; do
      p="$MODS/$m/plugin.nro"
      [ -f "$p" ] && { mv "$p" "$p.disabled"; echo "  plugin off: $m"; } || echo "  no plugin: $m"
    done; sync
    ;;
  plugins-on)
    for m in "$@"; do
      p="$MODS/$m/plugin.nro.disabled"
      [ -f "$p" ] && { mv "$p" "${p%.disabled}"; echo "  plugin on: $m"; } || echo "  not disabled: $m"
    done; sync
    ;;
  *) echo "unknown: $cmd (status|on|off|batch|plugins-off|plugins-on)"; exit 1 ;;
esac