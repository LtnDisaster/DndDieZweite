#!/usr/bin/env bash
# Restore a vtt-backup.sh archive into VTT_DATA_DIR (default ./data).
# ALWAYS stop the app first:  docker compose stop app
# Usage: scripts/vtt-restore.sh <backup.tar.gz> [data-dir]
set -euo pipefail
cd "$(dirname "$0")/.."
BK="${1:?usage: vtt-restore.sh <backup.tar.gz> [data-dir]}"
DATA="${2:-${VTT_DATA_DIR:-./data}}"
[ -f "$BK" ] || { echo "no such archive: $BK"; exit 1; }

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
tar xzf "$BK" -C "$STAGE"
[ -f "$STAGE/data/vtt.db" ] || { echo "archive has no data/vtt.db"; exit 1; }

mkdir -p "$DATA"
# Safety: never clobber a live db silently.
if [ -f "$DATA/vtt.db" ]; then
  SAFE="${DATA}/vtt.db.pre-restore.$(date +%Y%m%d-%H%M%S)"
  mv "$DATA/vtt.db" "$SAFE"
  echo "existing db kept at: $SAFE"
fi
cp "$STAGE/data/vtt.db" "$DATA/vtt.db"
# A restore must bring the WAL back too — old sidecar files would resurrect
# stale pages over the restored db, so remove them explicitly.
rm -f "$DATA/vtt.db-wal" "$DATA/vtt.db-shm"
[ -f "$STAGE/data/secret.key" ] && cp -p "$STAGE/data/secret.key" "$DATA/secret.key" || true
[ -d "$STAGE/data/uploads" ] && cp -a "$STAGE/data/uploads/." "$DATA/uploads/" 2>/dev/null || mkdir -p "$DATA/uploads"

python3 - "$DATA/vtt.db" <<'PY'
import sqlite3, sys
row = sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()
print("integrity_check:", row[0])
sys.exit(0 if row[0] == "ok" else 1)
PY
echo "restored into $DATA — verify by starting the app and logging in."
echo "(old sessions stay signed-out only if secret.key was NOT part of this backup)"
