# P1.0 Performance Testing - Quick Start

## 1️⃣ セットアップ（2分）

### ターミナル1: バックエンド起動

```bash
cd /Users/takumimaki/dev/spotify-shopper
PYTHONPATH=/Users/takumimaki/dev/spotify-shopper \
  /Users/takumimaki/dev/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

✅ 出力: `INFO:     Uvicorn running on http://127.0.0.1:8000`

### ターミナル2: フロント起動

```bash
cd /Users/takumimaki/dev/spotify-shopper-web
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev
```

✅ 出力: `ready - started server on 0.0.0.0:3000`

### ブラウザ

- http://localhost:3000 を開く
- **DevTools を開く** (F12 → Console タブ)

---

## 2️⃣ テスト実行（3分）

### Test A: Spotify - Cold Run

1. ブラウザで **Cmd+Shift+R** でハード更新
2. このSpotifyプレイリストURLを入力:
   ```
   https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ
   ```
3. **"Analyze"** をクリック
4. Console に `[PERF]` ログが出る（下の "ログ例" 参照）

**Console から以下をコピペ:**
```
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=... network_ms=... json_ms=... render_ms=... total_ms=... payload_bytes=...
```

**ターミナル1 から以下をコピペ:**
```
[PERF] source=spotify url_len=... fetch_ms=... enrich_ms=... total_backend_ms=... total_api_ms=... tracks=...
```

### Test B: Spotify - Warm Run

1. **ページ内で** (リロードなし) 同じURLを再度入力
2. **"Analyze"** をクリック
3. 同じようにログをコピペ

### Optional Test C: Rekordbox XML

Rekordbox XML がある場合:
1. XMLファイル選択
2. Spotify URL + XML で "Analyze"
3. ログをコピペ（`xml_ms` を確認）

---

## 3️⃣ ログ解釈（1分）

### ログ例1: 高速（OK✅）

```
Cold Run:
[Front] [PERF] ... network_ms=450 json_ms=28 render_ms=120 total_ms=598
[Back]  [PERF] ... fetch_ms=445 enrich_ms=0 total_backend_ms=445 total_api_ms=448

→ 診断: Spotify fetch（445ms）が大部分。JSON/render高速。正常です。
```

### ログ例2: Apple Music（遅い🟡）

```
[Front] [PERF] ... network_ms=3200 json_ms=42 render_ms=98 total_ms=3340
[Back]  [PERF] ... fetch_ms=2100 enrich_ms=1050 total_backend_ms=3150 total_api_ms=3154

→ 診断: Playwright scraping（2100ms）+ enrichment（1050ms）。Apple は遅い。
対策: キャッシュ（TTL 1-6h）
```

### ログ例3: 描画遅い🔴

```
[Front] [PERF] ... network_ms=450 json_ms=28 render_ms=1500 total_ms=1978
[Back]  [PERF] ... fetch_ms=445 total_backend_ms=445 total_api_ms=448 tracks=500

→ 診断: render_ms=1500（React rendering遅い）。tracks多い可能性。
対策: displayedTracks memo化、仮想スクロール検討
```

### ログ例4: XML照合遅い🔴

```
[Front] [PERF] ... network_ms=450 json_ms=26 render_ms=135 total_ms=611
[Back]  [PERF] ... fetch_ms=478 xml_ms=1200 total_ms=1700 tracks=100

→ 診断: xml_ms=1200（Rekordbox照合遅い）。マッチング最適化検討。
```

---

## 4️⃣ 結果レポート

**テンプレート:**

```
=== Cold Run (Spotify, no XML) ===
Frontend:  [PERF] url=... tracks=X network_ms=Y json_ms=Z render_ms=W total_ms=T payload_bytes=B
Backend:   [PERF] source=spotify ... fetch_ms=X enrich_ms=Y total_backend_ms=Z total_api_ms=T tracks=N

=== Warm Run (same URL) ===
Frontend:  [PERF] url=... tracks=X network_ms=Y json_ms=Z render_ms=W total_ms=T payload_bytes=B
Backend:   [PERF] source=spotify ... fetch_ms=X enrich_ms=Y total_backend_ms=Z total_api_ms=T tracks=N

🔍 診断:
- network_ms が大きい？ → Spotify/Apple fetch 遅い → キャッシュ検討
- render_ms が大きい？ → React 描画遅い → memo化・仮想スクロール
- xml_ms が大きい？ → Rekordbox照合遅い → マッチング最適化
- 全体OK？ → 特に最適化不要。現在の仕様範囲で問題なし。
```

---

## 参考ドキュメント

- **詳細テスト手順**: `docs/PERF_TESTING.md` (backend)
- **実装の詳細**: `docs/P1.0_IMPLEMENTATION.md` (backend)

---

## トラブルシューティング

| 問題 | 解決 |
|------|------|
| `[PERF]` ログが出ない | Console が [PERF] を除外してないか確認。ページリロード後に analyze 実行。 |
| バックエンド起動エラー | `PYTHONPATH` 設定確認。`python -c "from app import app"` で syntax check。 |
| フロント起動エラー | `NEXT_PUBLIC_BACKEND_URL` 環境変数確認。 |
| Connection refused | バックエンド/フロント両方起動確認。 |

---

**🚀 実行準備完了。テストを回してください！**
