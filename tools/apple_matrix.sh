#!/usr/bin/env bash
set -uo pipefail

# Run Apple canary URLs and summarize outcomes.
PORT="${1:-8000}"
BASE_URL="http://127.0.0.1:${PORT}"
CANARY_FILE=${CANARY_FILE:-tools/apple_canary_urls.txt}
PY_BIN=${PY_BIN:-/Users/takumimaki/dev/.venv/bin/python}
CURL_MAX_TIME=${CURL_MAX_TIME:-75}

echo "[matrix] BASE_URL=$BASE_URL"

now_ms() {
  "$PY_BIN" - <<'PY'
import time
print(int(time.time() * 1000))
PY
}

i=0
while IFS= read -r url || [ -n "$url" ]; do
  # Strip CRLF, trim whitespace, skip comments
  url="${url%%$'\r'}"
  url="${url#"${url%%[![:space:]]*}"}"
  url="${url%"${url##*[![:space:]]}"}"
  [[ -z "$url" || "$url" =~ ^# ]] && continue
  
  i=$((i + 1))
  start_ms=$(now_ms)

  resp="$(curl -sS --max-time "$CURL_MAX_TIME" \
    -H "Accept: application/json" \
    -w $'\nHTTP_CODE:%{http_code}\n' \
    -G "${BASE_URL}/api/playlist" \
    --data-urlencode "url=$url" \
    --data-urlencode "source=apple" \
    --data-urlencode "refresh=1" \
    2>&1
  )"
  curl_status=$?
  end_ms=$(now_ms)
  elapsed_ms=$(( end_ms - start_ms ))

  if [ $curl_status -ne 0 ]; then
    echo "skip idx=$i tracks=0 reason=curl_exit_$curl_status elapsed_ms=$elapsed_ms url=$url"
    continue
  fi

  http_code="$(printf "%s" "$resp" | sed -n 's/^HTTP_CODE://p' | tail -n1)"
  body="$(printf "%s" "$resp" | sed '/^HTTP_CODE:/d')"

  if [ "$http_code" != "200" ]; then
    echo "skip idx=$i tracks=0 reason=http_$http_code elapsed_ms=$elapsed_ms url=$url"
    continue
  fi

  if [ -z "$body" ]; then
    echo "skip idx=$i tracks=0 reason=empty_body elapsed_ms=$elapsed_ms url=$url"
    continue
  fi

  # Check if body is HTML instead of JSON
  head200="$(printf "%s" "$body" | head -c 200 | LC_ALL=C tr '\n' ' ')"
  if echo "$head200" | grep -qiE '<!doctype|<html|<head|<body'; then
    echo "skip idx=$i tracks=0 reason=html_body elapsed_ms=$elapsed_ms url=$url"
    continue
  fi

  # Use a temp file to avoid stdin piping issues with large JSON bodies
  tmpfile="/tmp/apple_matrix_body_$$_$i.json"
  printf "%s" "$body" > "$tmpfile"
  result=$($PY_BIN - "$i" "$url" "$elapsed_ms" "$tmpfile" <<'PY'
import json, sys
idx = sys.argv[1]
url = sys.argv[2]
elapsed = None
if len(sys.argv) > 3:
    try:
        elapsed = int(sys.argv[3])
    except Exception:
        elapsed = None
tmpfile_path = sys.argv[4] if len(sys.argv) > 4 else None
try:
    if tmpfile_path:
        with open(tmpfile_path, 'r') as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)
except Exception as e:
    print(f"fail idx={idx} url={url} reason=json_error:{e} elapsed_ms={elapsed}")
    sys.exit(0)

tracks = len(data.get("tracks", [])) if isinstance(data, dict) else 0
meta = data.get("meta", {}) if isinstance(data, dict) else {}
method = meta.get("apple_extraction_method")
row_prog = meta.get("apple_row_count_progression")
uniq_prog = meta.get("apple_unique_track_keys_progression")
last_track = meta.get("apple_last_track_key_progression")
reason = meta.get("reason") or meta.get("apple_reason")
status = "ok" if tracks >= 5 else "fail"

def should_skip(reason_text: str | None) -> bool:
    if not reason_text:
        return False
    lower = str(reason_text).lower()
    skip_keywords = [
        "403",
        "429",
        "captcha",
        "robot",
        "consent",
        "blocked",
        "forbidden",
        "access denied",
        "geo",
        "region",
    ]
    return any(kw in lower for kw in skip_keywords)

if tracks == 0 and should_skip(reason):
    status = "skip"

print(
    f"{status} idx={idx} url={url} tracks={tracks} method={method} "
    f"row_prog={row_prog} uniq_prog={uniq_prog} last_track={last_track} reason={reason} "
    f"elapsed_ms={elapsed}"
)
PY
)
  rm -f "$tmpfile"
  echo "$result"
done < "$CANARY_FILE"
