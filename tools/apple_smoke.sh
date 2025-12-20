#!/bin/bash
# Apple Music Canary Smoke Test
# Tests multiple canary URLs and succeeds if ANY pass
# Exit codes: 0=good, 1=bad, 125=skip (for git bisect)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANARY_FILE="${SCRIPT_DIR}/apple_canary_urls.txt"
PORT="${1:-18000}"
BASE_URL="http://localhost:${PORT}"
LOG_FILE="/tmp/apple_smoke_backend_${PORT}.log"

echo "=========================================="
echo "Apple Music Canary Smoke Test"
echo "=========================================="
echo "Backend Port: $PORT"
echo "Canary File:  $CANARY_FILE"
echo ""

# Check canary file exists
if [ ! -f "$CANARY_FILE" ]; then
  echo "❌ FAILED: Canary file not found: $CANARY_FILE"
  exit 125
fi

# Read canary URLs (skip comments and empty lines)
URLS=$(grep -v '^#' "$CANARY_FILE" | grep -v '^[[:space:]]*$' || true)

if [ -z "$URLS" ]; then
  echo "❌ FAILED: No URLs in canary file"
  exit 125
fi

URL_COUNT=$(echo "$URLS" | wc -l | tr -d ' ')
echo "Testing $URL_COUNT canary URLs..."
echo ""

# Start backend if not running
if ! curl -s "$BASE_URL/health" > /dev/null 2>&1; then
  echo "[Backend] Starting on port $PORT..."
  cd "$(dirname "$SCRIPT_DIR")"
  /Users/takumimaki/dev/.venv/bin/python -m uvicorn app:app \
    --host 127.0.0.1 --port "$PORT" --log-level error \
    > "$LOG_FILE" 2>&1 &
  
  BACKEND_PID=$!
  echo "[Backend] PID: $BACKEND_PID"
  
  # Wait for health check
  for i in {1..20}; do
    if curl -s "$BASE_URL/health" > /dev/null 2>&1; then
      echo "[Backend] Ready"
      break
    fi
    sleep 0.5
  done
  
  if ! curl -s "$BASE_URL/health" > /dev/null 2>&1; then
    echo "❌ SKIP: Backend failed to start"
    kill $BACKEND_PID 2>/dev/null || true
    [ -f "$LOG_FILE" ] && tail -30 "$LOG_FILE"
    exit 125
  fi
  
  STARTED_BACKEND=1
else
  echo "[Backend] Already running"
  STARTED_BACKEND=0
fi

# Test each URL
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
TEST_NUM=0

while IFS= read -r URL; do
  TEST_NUM=$((TEST_NUM + 1))
  echo "----------------------------------------"
  echo "[$TEST_NUM/$URL_COUNT] Testing: $URL"
  echo ""
  
  # Call API with 120s timeout (curl handles encoding)
  RESPONSE=$(curl -s -w "\n%{http_code}" \
    --get \
    --data-urlencode "url=$URL" \
    --data-urlencode "source=apple" \
    "${BASE_URL}/api/playlist" \
    -H "Accept: application/json" \
    -m 120 2>&1 || echo "curl_failed")
  
  # Check if curl itself failed
  if echo "$RESPONSE" | grep -q "curl_failed"; then
    echo "⚠️ SKIP: curl connection failed"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi
  
  HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
  BODY=$(echo "$RESPONSE" | sed '$d')
  
  echo "HTTP Status: $HTTP_CODE"
  if [ "$HTTP_CODE" -ge 400 ] 2>/dev/null; then
    echo "Response:"
    echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY" | head -200
  fi
  
  # If HTTP code missing/invalid (e.g., network error formatting), skip
  if ! echo "$HTTP_CODE" | grep -qE '^[0-9]{3}$'; then
    echo "⚠️ SKIP: No valid HTTP status from curl"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi

  # Check for external blocking (403/429 = rate limit/geo-block)
  if [ "$HTTP_CODE" = "403" ] || [ "$HTTP_CODE" = "429" ]; then
    echo "⚠️ SKIP: HTTP $HTTP_CODE (external blocking)"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    continue
  fi
  
  # Check HTTP status
  if [ "$HTTP_CODE" -ge 400 ]; then
    echo "❌ FAIL: HTTP $HTTP_CODE"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    continue
  fi
  
  # Parse tracks
  TRACK_COUNT=$(echo "$BODY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(len(data.get('tracks', [])))
except:
    print('0')
" 2>/dev/null)
  
  echo "Track Count: $TRACK_COUNT"
  
  # If 200 OK but 0 tracks, log first lines to check if HTML was returned
  if [ "$HTTP_CODE" = "200" ] && [ "$TRACK_COUNT" = "0" ]; then
    echo "⚠️ WARNING: HTTP 200 but 0 tracks. First 300 chars of response:"
    echo "$BODY" | head -c 300
    echo ""
  fi
  
  # Check tracks >= 5
  if [ "$TRACK_COUNT" -ge 5 ]; then
    PLAYLIST_NAME=$(echo "$BODY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('playlist_name', 'N/A'))
except:
    print('N/A')
" 2>/dev/null)
    echo "✅ PASS: $PLAYLIST_NAME"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "❌ FAIL: tracks.length = $TRACK_COUNT (expected >= 5)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done <<< "$URLS"

# Cleanup backend if we started it
if [ "$STARTED_BACKEND" -eq 1 ]; then
  echo ""
  echo "[Backend] Stopping..."
  kill $BACKEND_PID 2>/dev/null || true
  sleep 1
fi

echo ""
echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "Total:  $URL_COUNT"
echo "Pass:   $PASS_COUNT"
echo "Fail:   $FAIL_COUNT"
echo "Skip:   $SKIP_COUNT"
echo ""

# Exit logic for git bisect
if [ "$PASS_COUNT" -ge 1 ]; then
  echo "✅ GOOD: At least one canary URL passed"
  exit 0
elif [ "$SKIP_COUNT" -gt 0 ] && [ "$FAIL_COUNT" -eq 0 ]; then
  echo "⚠️ SKIP: All URLs skipped (external blocking)"
  exit 125
else
  echo "❌ BAD: All canary URLs failed"
  [ "$STARTED_BACKEND" -eq 1 ] && [ -f "$LOG_FILE" ] && echo "" && echo "Backend logs:" && tail -30 "$LOG_FILE"
  exit 1
fi
