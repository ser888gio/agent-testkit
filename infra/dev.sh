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

# Default: FastAPI on :8001 for /api, Vite on :5173 for the SPA with HMR.
# vite.config.ts already proxies /api, /static, /login, /logout and /auth to
# :8001, so :5173 is the address to open.
"$PYTHON" -m agentaudit.cli ui --port 8001 "$@" &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT

echo "open http://127.0.0.1:5173 (not :8001 -- that serves the last build)"
npm --prefix frontend/spa run dev
