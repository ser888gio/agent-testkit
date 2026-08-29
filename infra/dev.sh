#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -x ".venv/Scripts/python.exe" ]]; then
  PYTHON=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python"
fi

# --api-only serves the pre-built spa_dist bundle from FastAPI alone. That is
# what this script used to do unconditionally, and it is why editing
# frontend/spa/src never showed up in the browser: nothing rebuilt the bundle.
if [[ "${1:-}" == "--api-only" ]]; then
  shift
  exec "$PYTHON" -m agentaudit.cli ui "$@"
fi

# FastAPI for /api, Vite on :5173 for the SPA with HMR. `--port N` moves both.
API_PORT=8000
for ((i = 1; i <= $#; i++)); do
  if [[ "${!i}" == "--port" ]]; then
    next=$((i + 1))
    API_PORT="${!next:-8000}"
  fi
done

"$PYTHON" -m agentaudit.cli ui "$@" &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT

sleep 2
if ! kill -0 "$API_PID" 2>/dev/null; then
  echo "ERROR: API on :$API_PORT exited -- port in use? Try: bash infra/dev.sh --port 8001" >&2
  exit 1
fi

echo "open http://127.0.0.1:5173 (not :$API_PORT -- that serves the last build)"
AGENTAUDIT_API_URL="http://127.0.0.1:$API_PORT" npm --prefix frontend/spa run dev
