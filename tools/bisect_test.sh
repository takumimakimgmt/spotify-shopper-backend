#!/bin/bash
# Git bisect test runner for Apple Music
# Automatically starts backend, runs smoke test, cleans up
# Returns: 0 = good, 1 = bad, 125 = skip (for bisect)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# Fixed port for bisect
PORT=18000
LOG_FILE="/tmp/bisect_backend_${PORT}.log"
VENV="/Users/takumimaki/dev/.venv"
BACKEND_URL="http://127.0.0.1:$PORT"

# Cleanup function
cleanup() {
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  # Kill any leftover uvicorn on the port
  lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
  rm -f "$LOG_FILE" 2>/dev/null || true
}

trap cleanup EXIT

echo "[bisect] Using port $PORT"

# Kill any existing process on the port
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "[bisect] Killing existing process on port $PORT..."
  lsof -ti:$PORT | xargs kill -9 2>/dev/null || true
  sleep 1
fi

# Start backend
echo "[bisect] Starting backend on port $PORT..."
"$VENV/bin/python" -m uvicorn app:app \
  --host 127.0.0.1 --port "$PORT" \
  --log-level error \
  > "$LOG_FILE" 2>&1 &

BACKEND_PID=$!
echo "[bisect] Backend PID: $BACKEND_PID"

# Wait for health check (max 10s)
echo "[bisect] Waiting for /health endpoint..."
BACKEND_READY=0
for i in {1..20}; do
  if curl -s "$BACKEND_URL/health" > /dev/null 2>&1; then
    echo "[bisect] Backend ready"
    BACKEND_READY=1
    break
  fi
  sleep 0.5
done

if [ "$BACKEND_READY" -eq 0 ]; then
  echo "[bisect] Backend failed to start" >&2
  [ -f "$LOG_FILE" ] && tail -20 "$LOG_FILE"
  exit 125
fi

# Run smoke test
echo "[bisect] Running apple_smoke.sh..."
SMOKE_EXIT=0
bash "$SCRIPT_DIR/apple_smoke.sh" "$PORT" || SMOKE_EXIT=$?

echo ""
echo "[bisect] apple_smoke.sh exit code: $SMOKE_EXIT"

# Pass through exit code from smoke test
if [ "$SMOKE_EXIT" -eq 0 ]; then
  echo "[bisect] ✅ GOOD"
  exit 0
elif [ "$SMOKE_EXIT" -eq 125 ]; then
  echo "[bisect] ⚠️ SKIP"
  exit 125
else
  echo "[bisect] ❌ BAD"
  exit 1
fi
