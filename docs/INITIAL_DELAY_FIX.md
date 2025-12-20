# Initial Delay Analysis & Fix

## 目的

初回遅延の原因を「API / Playwright cold start / Frontend処理」の中から特定し、最大ボトルネックを修正する。

## 診断方法

### 1. 既存のPERFログから判定

```bash
# Backend起動
cd /Users/takumimaki/dev/spotify-shopper
uvicorn app:app --reload 2>&1 | tee backend.log

# 別ターミナルでフロント起動
cd /Users/takumimaki/dev/spotify-shopper-web
npm run dev

# テスト実行
# 1. Spotify URL で Analyze（warm up）
# 2. Apple Music URL で Analyze（初回 = cold start）
# 3. 同じApple URL で再度 Analyze（warm）

# ログ分析
bash tools/analyze_bottleneck.sh < backend.log
```

### 2. Client Timing確認

ブラウザのDevTools Consoleで `[PERF]` ログを確認：
- `client_total_ms`: フロント側の総時間
- `client_api_ms`: APIレスポンス待ち時間（=backend処理+network）
- `client_map_ms`: JSON→React state変換時間
- `client_overhead_ms`: その他のフロント処理

### 3. ボトルネック判定基準

| ケース | 判定基準 | 原因 |
|--------|----------|------|
| **Playwright Cold Start** | Apple初回 > 15s, 2回目 < 10s | Browser launch時間 |
| **API Latency** | Spotify > 2s | Spotify API/Network |
| **Frontend Processing** | `client_map_ms` > 500ms | React rendering |
| **Playwright Scraping** | Apple warm > 15s | Scroll/DOM解析が遅い |

## 想定される最大ボトルネック: Playwright Cold Start

### 現状

- Playwrightは**lazy init**（初回Apple Musicリクエストで起動）
- `chromium.launch()`に3-8秒かかる（特にRender/Vercel）
- ユーザーは初回Appleリクエストで10-20秒待たされる

### 修正: Browser Pre-warming

Startup時にブラウザを起動しておくことで、初回リクエストの遅延を削減。

#### 実装

`app.py`:
```python
@app.on_event("startup")
async def _prewarm_playwright():
    """Pre-warm Playwright browser on startup to avoid cold start delay."""
    if os.getenv("APPLE_PREWARM_BROWSER", "1") == "1":
        try:
            from playwright_pool import get_browser
            logger.info("[PREWARM] Starting browser pre-warm...")
            start = time.time()
            await get_browser()
            elapsed = time.time() - start
            logger.info(f"[PREWARM] Browser ready in {elapsed:.1f}s")
        except Exception as e:
            logger.warning(f"[PREWARM] Failed to pre-warm browser: {e}")
```

`playwright_pool.py` (既存コードは変更不要、ログ追加のみ):
```python
async def get_browser() -> Browser:
    global _pw, _browser
    if _browser is not None:
        return _browser

    async with _lock:
        if _browser is not None:
            return _browser
        
        logger.info("[PW_POOL] Launching Chromium browser...")
        start = time.time()
        _pw = await async_playwright().start()
        headless = os.getenv("APPLE_PLAYWRIGHT_HEADLESS", "1") != "0"
        _browser = await _pw.chromium.launch(headless=headless, args=_launch_args())
        elapsed = time.time() - start
        logger.info(f"[PW_POOL] Browser launched in {elapsed:.1f}s")
        return _browser
```

### トレードオフ

**Pros:**
- 初回Appleリクエストが3-8秒高速化
- ユーザー体験向上（待ち時間削減）

**Cons:**
- Startup時間が3-8秒増加
- メモリ使用量+50-100MB（Chromium process）
- Render free tierでtimeout risk（startup < 60s必須）

### 代替案: Conditional Pre-warming

環境変数で制御：
- `APPLE_PREWARM_BROWSER=1`: Render Production（有効）
- `APPLE_PREWARM_BROWSER=0`: 開発環境/free tier（無効）

## 測定結果テンプレート

```
=== Before Fix ===
Apple Music (cold start):  18,500ms
  - TTFB:                   15,200ms
  - Backend processing:     14,800ms
  - Chromium launch:        ~7,000ms (推定)
  - DOM extraction:         ~7,800ms

Apple Music (warm):        10,300ms
  - TTFB:                    8,100ms
  - Backend processing:      7,900ms
  - DOM extraction:          7,900ms

=== After Fix (Browser Pre-warmed) ===
Apple Music (first request): 10,500ms
  - TTFB:                      8,200ms
  - Backend processing:        8,000ms
  - DOM extraction:            8,000ms

Improvement: -8,000ms (-43% on cold start)
Startup time: +5.2s
```

## 実装チェックリスト

- [ ] `tools/analyze_bottleneck.sh` で現状測定
- [ ] ボトルネック特定（cold start / scraping / API）
- [ ] 修正実装（最大ボトルネックのみ）
- [ ] 再測定して効果確認
- [ ] トレードオフをドキュメント化
