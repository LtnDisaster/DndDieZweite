#!/usr/bin/env bash
# Create a clean, reviewable SOURCE archive (no git, no runtime data).
# Usage: scripts/make_release.sh [output-dir]   -> writes dnd-vtt-src-<date>.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-..}"
STAMP="$(date +%Y%m%d)"
NAME="dnd-vtt-src-${STAMP}"
mkdir -p "$OUT"
tar czf "${OUT}/${NAME}.tar.gz" \
  --exclude='./.git' --exclude='./.venv' --exclude='./venv' \
  --exclude='./data' --exclude='./tmp' --exclude='./dist' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' \
  --exclude='./app/static/uploads' --exclude='./.env' \
  --exclude='*.zip' --exclude='*.tar.gz' --exclude='*Zone.Identifier' \
  .
echo "wrote ${OUT}/${NAME}.tar.gz"
# Guard: fail loudly if anything forbidden slipped in.
if tar tzf "${OUT}/${NAME}.tar.gz" | grep -E '^\./(\.git/|data/|\.venv/|\.env$|app/static/uploads/)' ; then
  echo "ERROR: archive contains forbidden paths" >&2
  exit 1
fi
echo "verified: no git/data/venv/uploads entries"
