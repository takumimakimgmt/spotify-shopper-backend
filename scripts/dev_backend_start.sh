
#!/usr/bin/env bash
set -euo pipefail

cd "$HOME/dev/spotify-shopper"

VENV="$HOME/dev/.venv/bin/activate"
if [ ! -f "$VENV" ]; then
  echo "[ERR] venv not found: $VENV" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$VENV"

# kill previous (best effort)
pkill -9 -f "uvicorn.*app:app" >/dev/null 2>&1 || true
pkill -9 -f "playwright" >/dev/null 2>&1 || true

export APPLE_DEBUG="${APPLE_DEBUG:-1}"
export APPLE_ARTIFACTS="${APPLE_ARTIFACTS:-0}"

echo "[DEV] starting backend on http://127.0.0.1:8000 (APPLE_DEBUG=$APPLE_DEBUG APPLE_ARTIFACTS=$APPLE_ARTIFACTS)"
exec python -m uvicorn app:app --host 127.0.0.1 --port 8000 --log-level info
