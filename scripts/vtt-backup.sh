#!/usr/bin/env bash
# WAL-safe backup of everything persistent: SQLite db (via sqlite3 backup API,
# safe while the app is writing), secret.key, uploads/.
# Usage: scripts/vtt-backup.sh [output-dir]        (default: ../backups)
# The app does NOT need to be stopped for a consistent DATABASE snapshot; for an
# atomically consistent db+uploads PAIR stop the app (docker compose stop).
set -euo pipefail
cd "$(dirname "$0")/.."
DATA="${VTT_DATA_DIR:-./data}"
OUT="${1:-../backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$OUT" "$STAGE/data"

[ -f "$DATA/vtt.db" ] || { echo "no database at $DATA/vtt.db"; exit 1; }

# 1) consistent DB snapshot (handles WAL correctly, app may stay running)
python3 - "$DATA/vtt.db" "$STAGE/data/vtt.db" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with src:
    src.backup(dst)          # online backup API, WAL-aware
dst.close()
PY

# 2) integrity-check the snapshot BEFORE it goes into the archive
python3 - "$STAGE/data/vtt.db" <<'PY'
import sqlite3, sys
ok = sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0]
sys.exit(0 if ok == "ok" else ("integrity_check: " + str(ok), 1)[1])
PY

# 3) secret + uploads (skip quietly if absent)
[ -f "$DATA/secret.key" ] && cp -p "$DATA/secret.key" "$STAGE/data/" || true
[ -d "$DATA/uploads" ] && cp -a "$DATA/uploads" "$STAGE/data/uploads" || true

tar czf "${OUT}/dnd-vtt-backup-${STAMP}.tar.gz" -C "$STAGE" data
echo "backup: ${OUT}/dnd-vtt-backup-${STAMP}.tar.gz"
echo "contains: vtt.db (integrity-checked), secret.key, uploads/ (when present)"
