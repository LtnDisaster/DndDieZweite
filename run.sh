#!/usr/bin/env bash
# Start the D&D VTT server.
#   HOST=0.0.0.0 PORT=9000 ./run.sh
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv || true
  ./.venv/bin/pip install -r requirements.txt
fi

exec ./.venv/bin/python -m uvicorn app.main:app \
  --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"
