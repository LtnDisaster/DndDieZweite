#!/usr/bin/env bash
# D143 live smoke (TODO P1): start -> health -> real registration + room over
# HTTP -> stop. Own temp data dir, ephemeral loopback port, pidfile, no docker,
# no shared state. Exit code 0 = the server is alive and speaks the API.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${SMOKE_PORT:-39017}"
TMP="$(mktemp -d)"
DB_DIR="$TMP/data" PORT_URL="http://127.0.0.1:${PORT}"
export VTT_DATA_DIR="$DB_DIR"

cleanup() {
  if [ -f "$TMP/smoke.pid" ]; then kill "$(cat "$TMP/smoke.pid")" 2>/dev/null || true; fi
  wait 2>/dev/null || true
  rm -rf "$TMP"
}
trap cleanup EXIT

python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  >"$TMP/server.log" 2>&1 &
echo $! > "$TMP/smoke.pid"

for _ in $(seq 1 100); do
  curl -fsS "$PORT_URL/api/health" >/dev/null 2>&1 && break
  sleep 0.2
done
test "$(curl -fsS "$PORT_URL/api/health")" = '{"ok":true}'

CREDS='{"username":"smoketester","password":"smoke-pass-1"}'
LOGIN="$(curl -fsS -c "$TMP/cookies" -X POST "$PORT_URL/api/register" \
  -H 'Content-Type: application/json' -d "$CREDS")"
test -n "$LOGIN"
CODE="$(curl -fsS -b "$TMP/cookies" -X POST "$PORT_URL/api/rooms" \
  -H 'Content-Type: application/json' -d '{"name":"Smoke"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["code"])')"
test "${#CODE}" -ge 4
echo "smoke ok: health, register, room $CODE"
