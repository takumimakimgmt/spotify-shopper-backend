# Apple Music Production Stability: Metrics & Resilience

## 目的

Render相当の条件で失敗率と平均時間を測定し、必要に応じてリトライ/バックオフ/キャッシュ戦略を実装する。
**重要**: DOM抽出ロジック自体は変更しない（scroll loop, selector等は既に安定）。

## 現状

- DOM-first抽出が実装済み（scroll loop with content-change detection）
- Matrix testで10/10プレイリスト成功（100%）
- 平均抽出時間: ~18秒（Apple Music）
- ただし、**ローカル環境**での結果

## Render環境の特徴

1. **Cold Start**: 初回リクエストでPlaywright起動（+3-8秒）
2. **Network Latency**: US East → Japanで+100-300ms
3. **CPU制限**: Free tier (0.5 CPU) → scroll/DOMが遅い可能性
4. **Memory制限**: 512MB → Chromiumメモリ不足のリスク
5. **Timeout**: 95秒でタイムアウト（`APPLE_PLAYWRIGHT_TIMEOUT_S=95`）

## 測定計画

### 1. Baseline Metrics (Render Production)

**目標**: 20-30 URLで失敗率と平均時間を測定

```bash
# Render Production backend URL
BACKEND_URL="https://your-app.onrender.com"

# Matrix test with extended canary list
bash tools/apple_matrix_render.sh > render_metrics.txt

# 分析
bash tools/analyze_bottleneck.sh < render_metrics.txt
```

**測定項目**:
- Success率: `ok / (ok + fail + skip)` (目標: >95%)
- Timeout率: `skip reason=timeout` (目標: <5%)
- Avg time: median of `elapsed_ms` (目標: <25s)
- P95 time: 95th percentile (目標: <40s)

### 2. Extended Canary URLs

`tools/apple_canary_urls_extended.txt` を作成（20-30 URL）:

```
# Small (40-100 tracks)
https://music.apple.com/jp/playlist/ampm-thinking-may/pl.024712183de946b7be5ba1267d94e035
https://music.apple.com/jp/playlist/alt-ctrl/pl.0b593f1142b84a50a2c1e7088b3fb683
...

# Medium (100-200 tracks)
https://music.apple.com/jp/playlist/me-and-bae/pl.a13aca4f4f2c45538472de9014057cc0
...

# Large (300+ tracks)
https://music.apple.com/jp/playlist/beatstrumentals/pl.f54198ad42404535be13eabf3835fb22
...
```

### 3. Render Matrix Test Script

`tools/apple_matrix_render.sh`:

```bash
#!/usr/bin/env bash
# Run matrix test against Render production
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-https://your-app.onrender.com}"
CANARY_FILE="${CANARY_FILE:-tools/apple_canary_urls_extended.txt}"

echo "[matrix-render] Backend: $BACKEND_URL"
echo "[matrix-render] Canary file: $CANARY_FILE"
echo ""

# Warmup: wake up Render instance
curl -sSf "$BACKEND_URL/health" > /dev/null || echo "[warn] Backend not responding"
sleep 2

# Run matrix
while IFS= read -r url || [ -n "$url" ]; do
  [[ -z "$url" || "$url" =~ ^# ]] && continue
  
  start_ms=$(date +%s%3N)
  response=$(curl -sSf -w '\nHTTP_CODE:%{http_code}\n' \
    "${BACKEND_URL}/api/playlist?url=${url}&source=apple&refresh=1" \
    2>&1 || echo "CURL_FAILED")
  end_ms=$(date +%s%3N)
  elapsed_ms=$((end_ms - start_ms))
  
  # Parse response
  if echo "$response" | grep -q "CURL_FAILED"; then
    echo "fail url=$url reason=curl_failed elapsed_ms=$elapsed_ms"
  elif echo "$response" | grep -q "HTTP_CODE:200"; then
    body="$(echo "$response" | sed '/^HTTP_CODE:/d')"
    tracks=$(echo "$body" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('tracks',[])))" 2>/dev/null || echo "0")
    echo "ok url=$url tracks=$tracks elapsed_ms=$elapsed_ms"
  else
    http_code=$(echo "$response" | sed -n 's/^HTTP_CODE://p')
    echo "skip url=$url reason=http_$http_code elapsed_ms=$elapsed_ms"
  fi
done < "$CANARY_FILE"
```

## 安定化戦略

### Strategy 1: Browser Pre-warming (Cold Start削減)

**現状**: Lazy init（初回リクエストで+3-8秒）
**対策**: Startup時にブラウザ起動

**実装** (`app.py`):

```python
import os
import time

@app.on_event("startup")
async def _prewarm_playwright():
    """Pre-warm Playwright browser to eliminate cold start delay."""
    if os.getenv("APPLE_PREWARM_BROWSER", "1") == "1":
        try:
            from playwright_pool import get_browser
            logger.info("[PREWARM] Starting browser...")
            start = time.time()
            await get_browser()
            elapsed = time.time() - start
            logger.info(f"[PREWARM] Browser ready in {elapsed:.1f}s")
        except Exception as e:
            logger.warning(f"[PREWARM] Failed: {e}")
```

**効果**: 初回リクエスト -5秒
**トレードオフ**: Startup +5秒, Memory +80MB

### Strategy 2: TTL Cache for Playlists

**現状**: `refresh=1` で毎回スクレイピング
**対策**: Apple Musicプレイリスト結果をキャッシュ（TTL 6-24h）

**実装** (`core.py`):

```python
from cachetools import TTLCache
import hashlib

# Apple Music playlist cache (URL → result, TTL 6h)
_apple_cache = TTLCache(maxsize=100, ttl=21600)

def _cache_key_apple(url: str) -> str:
    """Generate cache key from normalized Apple Music URL."""
    normalized = url.split('?')[0].lower()  # Strip query params
    return hashlib.md5(normalized.encode()).hexdigest()

async def fetch_apple_music_tracks(url: str, app: Any = None, ...) -> Dict[str, Any]:
    # Check cache first (unless refresh=1)
    if not refresh:
        cache_key = _cache_key_apple(url)
        if cache_key in _apple_cache:
            logger.info(f"[Apple] Cache hit for {url}")
            cached = _apple_cache[cache_key]
            cached["meta"]["cache_hit"] = True
            return cached
    
    # Scrape (existing logic)
    result = await _scrape_apple_playlist(url, app, ...)
    
    # Cache successful results (tracks >= 5)
    if len(result.get("items", [])) >= 5:
        _apple_cache[_cache_key_apple(url)] = result
        result["meta"]["cache_hit"] = False
    
    return result
```

**効果**: 2回目以降 <100ms
**トレードオフ**: プレイリスト更新が反映されない（6-24h）

### Strategy 3: Retry with Exponential Backoff

**現状**: 1回失敗したら即エラー
**対策**: タイムアウト/ネットワークエラーは3回までリトライ

**実装** (`core.py`):

```python
import asyncio

async def _fetch_apple_with_retry(
    url: str, 
    app: Any, 
    max_retries: int = 3,
    base_delay: float = 2.0
) -> Dict[str, Any]:
    """Fetch Apple Music playlist with exponential backoff retry."""
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = await fetch_apple_music_tracks(url, app, ...)
            if attempt > 0:
                logger.info(f"[Apple] Retry succeeded on attempt {attempt + 1}")
            return result
        except asyncio.TimeoutError as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # 2s, 4s, 8s
                logger.warning(f"[Apple] Timeout on attempt {attempt + 1}, retrying in {delay}s...")
                await asyncio.sleep(delay)
            else:
                logger.error(f"[Apple] Failed after {max_retries} attempts")
        except Exception as e:
            # Non-retryable errors (geo-block, 404, etc.)
            raise
    
    raise last_error
```

**効果**: Timeout失敗率 -50%
**トレードオフ**: 失敗時の待ち時間 +14秒（3回リトライ）

### Strategy 4: Circuit Breaker (Advanced)

**現状**: Appleダウン時も全リクエストが95秒待つ
**対策**: 連続失敗でAppleエンドポイントを一時遮断

**実装** (Optional, 複雑):

```python
from datetime import datetime, timedelta

class CircuitBreaker:
    def __init__(self, failure_threshold=5, timeout_seconds=300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timedelta(seconds=timeout_seconds)
        self.opened_at = None
    
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if datetime.now() - self.opened_at > self.timeout:
            self.reset()
            return False
        return True
    
    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.opened_at = datetime.now()
            logger.warning(f"[Circuit Breaker] Opened for {self.timeout.seconds}s")
    
    def record_success(self):
        self.reset()
    
    def reset(self):
        self.failure_count = 0
        self.opened_at = None

_apple_circuit = CircuitBreaker()
```

**効果**: Apple障害時にfast-fail（<1s）
**トレードオフ**: 実装が複雑、誤検知リスク

## 実装優先度

### Phase 1: 測定 (必須)

- [ ] Extended canary URLs作成（20-30 URL）
- [ ] Render matrix test実行（`apple_matrix_render.sh`）
- [ ] 失敗率・平均時間・P95を記録

### Phase 2: Quick Wins (推奨)

**条件**: 失敗率 >5% or 平均時間 >25s

- [ ] **Browser Pre-warming** (cold start削減)
- [ ] **TTL Cache** (頻繁なプレイリスト向け)

### Phase 3: Advanced (必要に応じて)

**条件**: タイムアウト率 >10%

- [ ] **Retry with Backoff** (ネットワーク不安定時)
- [ ] Circuit Breaker (Apple障害時のfast-fail)

### Phase 4: 再測定

- [ ] 修正後にRender matrix再実行
- [ ] 改善効果を数値で確認（Before/After比較）

## 測定結果テンプレート

```
=== Render Production Metrics ===

Date: ____-__-__
Backend: https://your-app.onrender.com
Canary URLs: 25

Before Fix:
- Success率: 88% (22/25)
- Timeout: 8% (2 urls)
- Network fail: 4% (1 url)
- Avg time: 28.4s
- P95 time: 45.2s

Applied Fixes:
- ✅ Browser pre-warming
- ✅ TTL cache (6h)
- ❌ Retry/backoff (not needed)

After Fix:
- Success率: 96% (24/25)
- Timeout: 0%
- Network fail: 4% (1 url, geo-block)
- Avg time: 22.1s (↓6.3s, -22%)
- P95 time: 38.5s (↓6.7s, -15%)

Conclusion:
- Cold start penalty eliminated (-5s on first request)
- Cache hit率 30% on 2nd+ runs
- No retry needed (network stable)
- Recommend: Keep current config
```

## チェックリスト

- [ ] Extended canary URLs準備（20-30 URL, varied sizes）
- [ ] `apple_matrix_render.sh` 作成・テスト
- [ ] Render production測定（baseline）
- [ ] 失敗率・平均時間を記録
- [ ] ボトルネック特定（cold start / timeout / network）
- [ ] Quick Wins実装（pre-warm / cache）
- [ ] 再測定（improvement確認）
- [ ] Before/After比較レポート作成

## 完了条件

- ✅ 失敗率 <5%
- ✅ 平均時間 <25s
- ✅ P95時間 <40s
- ✅ タイムアウト率 <3%
- ✅ Before/Afterレポート完成
