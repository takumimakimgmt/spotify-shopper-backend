# Performance Testing Guide

## 計測機能の概要

フロント・バックエンド両側で詳細な性能計測を実装しました。

### フロント側計測（browser console）

```
[PERF] url=... tracks=N network_ms=X.X json_ms=Y.Y render_ms=Z.Z total_ms=T.T payload_bytes=B
```

- **network_ms**: fetch開始～APIレスポンス受信まで
- **json_ms**: JSON parse時間
- **render_ms**: React state update～React rendering完了（requestAnimationFrame 2回）
- **total_ms**: 全体（network + json + render）
- **payload_bytes**: JSONペイロードのバイト数

### バックエンド側計測（server logs）

```
[PERF] source=spotify url_len=XX fetch_ms=X.X enrich_ms=Y.Y total_backend_ms=Z.Z total_api_ms=T.T tracks=N
```

- **fetch_ms**: プレイリスト取得（Spotify API or Apple Playwright）
- **enrich_ms**: ISRC enrichment時間（AppleのみISRC enrichment実施）
- **total_backend_ms**: core.py処理合計
- **total_api_ms**: app.py内での全処理（fetch～playlist_result_to_dict～ログ出力）
- **tracks**: トラック数

Rekordbox XML upload時:
```
[PERF] source=spotify url_len=XX fetch_ms=X.X xml_ms=Y.Y total_ms=Z.Z tracks=N
```

- **xml_ms**: Rekordbox照合～owned付与の時間

---

## テスト手順

### 事前準備

1. **バックエンド起動**
```bash
cd /Users/takumimaki/dev/spotify-shopper
PYTHONPATH=/Users/takumimaki/dev/spotify-shopper \
  /Users/takumimaki/dev/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

2. **フロント起動**
```bash
cd /Users/takumimaki/dev/spotify-shopper-web
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev
```

3. ブラウザで `http://localhost:3000` を開く
4. DevToolsの Console を開く（F12 → Console タブ）

---

### テストシナリオ

#### シナリオ1: Spotify プレイリスト（XML なし）- Cold Run

1. 任意のSpotifyプレイリストURL（例: `https://open.spotify.com/playlist/37i9dQZEVXbLRQxzhuKfJ2`）をコピー
   - または、小さい公開プレイリストを作成 & URLを取得
2. **ハード更新**（Cmd+Shift+R）してページをリロード
3. URLをテキストボックスに貼り付け
4. 「Analyze」ボタンをクリック
5. Console に `[PERF]` ログが出現するまで待つ
6. 以下の情報をキャプチャ：
   - **Front** `[PERF] url=... network_ms=... json_ms=... render_ms=... total_ms=... payload_bytes=...`
   - **Back** (ターミナル) `[PERF] source=spotify fetch_ms=... total_api_ms=... tracks=...`

**期待される値の目安（Spotify, small playlist 50〜100 tracks）:**
- network_ms: 200〜1000ms（バックエンドAPI+Spotify fetch）
- json_ms: 10〜50ms（小さいペイロード）
- render_ms: 50〜200ms（React state + rendering）
- total_ms: 300〜1500ms
- payload_bytes: 数十KB〜100KB程度

#### シナリオ2: Spotify プレイリスト（XML なし）- Warm Run

1. **同じページ内で**、同じプレイリストURLを再度入力
2. 「Analyze」をクリック
3. Console logs をキャプチャ
4. Cold Run との差を確認（network_ms が同程度 or 減少していることを期待）

#### シナリオ3: Apple Music プレイリスト（XML なし）

1. Apple Music プレイリストURL（例: `https://music.apple.com/jp/playlist/...`）を用意
2. URLを入力 → 「Analyze」
3. Console logs をキャプチャ（Playwright scraping が遅い可能性あり）

**期待される値（Apple Music, with Spotify enrichment）:**
- network_ms: 1000〜5000ms以上（Playwrightスクレイピング＋Spotify enrichment）
- render_ms: 50〜200ms（フロント側は通常と同じ）

#### シナリオ4: Rekordbox XML 照合

1. Rekordbox collection XML ファイルをダウンロード & 用意
2. 任意のSpotifyプレイリストURL＋XMLを同時にアップロード
3. 「Analyze」をクリック
4. Console + ターミナル logs をキャプチャ

**期待される値（Spotify + Rekordbox）:**
- network_ms: 200〜1000ms（Spotify fetch）
- json_ms: 10〜50ms
- render_ms: 50〜200ms
- xml_ms: 200〜2000ms（XMLパース＋照合、ファイルサイズ依存）
- total_backend_ms: network_ms + xml_ms + overhead

---

## ログ解釈ガイド

### 問題判別フロー

```
total_ms が想定より遅い（例: 3000ms以上）
  ├─ network_ms が大きい（>1000ms）
  │   ├─ source=spotify かつ Apple URL なら → Spotify enrichment待ち（期待値）
  │   └─ source=apple なら → Playwright scraping が遅い（最適化検討）
  │
  ├─ json_ms が大きい（>100ms）
  │   └─ ペイロードサイズが大きい → tracks が多すぎる可能性
  │
  ├─ render_ms が大きい（>500ms）
  │   └─ React rendering が遅い
  │       └─ displayedTracks filtering/sorting の複雑さか、
  │           state update の度重なり、Reconciliation 複雑度
  │
  └─ total_backend_ms が大きい（>1000ms）
      └─ xml_ms が関係しているか？ XML照合が重い
```

### 最適化のヒント

1. **network_ms が支配的**
   - Spotify fetch: TTL cache（6〜24h、playlist URL正規化）
   - Apple scraping: TTL cache（shorter TTL、maybe 1h）

2. **render_ms が支配的**
   - displayedTracks memo 最適化
   - Track row component の memo化（必要に応じてコンポーネント化）
   - 大量トラック時は仮想スクロール検討

3. **xml_ms が支配的**
   - Rekordbox 照合ロジックの最適化（インデックス化、キャッシュ）
   - frontend での lazy load（"Load owned links" みたいに）

---

## 実行例

### Cold Run（Spotify, 100 tracks, no XML）

```
Console Output:
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=100 network_ms=450.3 json_ms=28.5 render_ms=120.7 total_ms=599.5 payload_bytes=87543

Terminal Output:
[PERF] source=spotify url_len=56 fetch_ms=445.1 enrich_ms=0.0 total_backend_ms=445.1 total_api_ms=448.8 tracks=100
```

→ Network fetch が大部分（445ms）。JSON/render は高速。OK。

### Warm Run（同じ URL）

```
Console Output:
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=100 network_ms=468.2 json_ms=25.1 render_ms=115.3 total_ms=608.6 payload_bytes=87543

Terminal Output:
[PERF] source=spotify url_len=56 fetch_ms=462.8 enrich_ms=0.0 total_backend_ms=462.8 total_api_ms=466.5 tracks=100
```

→ network_ms がほぼ同じ（Spotify は cache なし）。キャッシュが有効でないことを確認。

### Apple Music（Slow）

```
Console Output:
[PERF] url=https://music.apple.com/jp/playlist/pl.u-jV8DZq0S1Pl6Nqv tracks=75 network_ms=3200.5 json_ms=42.1 render_ms=98.3 total_ms=3340.9 payload_bytes=65123

Terminal Output:
[PERF] source=apple url_len=46 fetch_ms=2100.3 enrich_ms=1050.2 total_backend_ms=3150.5 total_api_ms=3154.2 tracks=75
```

→ network_ms が 3200ms と長い（Playwright + enrichment）。Apple Music は遅いことを確認。

### Rekordbox XML upload

```
Console Output:
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=100 network_ms=480.1 json_ms=26.3 render_ms=135.4 total_ms=641.8 payload_bytes=87543

Terminal Output:
[PERF] source=spotify url_len=56 fetch_ms=478.2 xml_ms=580.5 total_ms=1065.7 tracks=100
```

→ xml_ms が 580ms（XML照合）。Spotify fetch は 478ms。キャッシュ検討の価値あり。

---

## 次のステップ（結果を見た後）

1. 上記テストシナリオを実行
2. 結果をこのドキュメントの "実行例" セクションに追加
3. ボトルネックを特定
4. 最適化案を作成（キャッシュ、frontend 遅延ロード、etc）
