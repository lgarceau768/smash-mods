#!/usr/bin/env bash
#
# Build both SD-card profiles from scratch: fetch -> unpack -> verify -> stage.
#
# Everything is reproducible from a clean checkout; downloads are cached and
# checksum-verified, so re-running is cheap.
#
#   ./scripts/build.sh              # full build
#   ./scripts/build.sh --skip-fetch # rebuild from what is already downloaded
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_FETCH=0
[[ "${1:-}" == "--skip-fetch" ]] && SKIP_FETCH=1

BLU=$'\033[34m'; BLD=$'\033[1m'; OFF=$'\033[0m'
[[ -t 1 ]] || { BLU=""; BLD=""; OFF=""; }
step() { printf '\n%s==>%s %s%s%s\n' "$BLU" "$OFF" "$BLD" "$*" "$OFF"; }

step "1/5  fetch pinned components"
if (( SKIP_FETCH )); then
  echo "  skipped"
else
  python3 scripts/fetch.py
fi

step "2/5  normalise mod layouts"
python3 scripts/unpack.py --all

step "3/5  verify roster workspace"
python3 scripts/verify.py --workspace roster

step "4/5  self-test the linter"
python3 tests/test_verify.py

step "5/5  stage SD profiles"
python3 scripts/stage.py

step "build complete"
cat <<EOF
Staged profiles:
$(du -sh build/* 2>/dev/null | sed 's/^/  /')

Next: plug in the SD card and run
  ./scripts/deploy.sh                 # dry run first
  ./scripts/deploy.sh --commit
EOF
