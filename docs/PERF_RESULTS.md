# P1.1: Performance Testing - Actual Results

## テスト実行環境

- **Date**: 2025-12-14
- **Backend**: http://127.0.0.1:8000
- **Frontend**: http://localhost:3000
- **Test Playlist**: https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ

---

## 実行手順

### セットアップ（済み）

```bash
# ターミナル1: Backend
cd /Users/takumimaki/dev/spotify-shopper
PYTHONPATH=/Users/takumimaki/dev/spotify-shopper \
  /Users/takumimaki/dev/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000

# ターミナル2: Frontend
cd /Users/takumimaki/dev/spotify-shopper-web
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev
```

### テスト実行（ブラウザ）

1. http://localhost:3000 を開く
2. DevTools を開く（F12 → Console）
3. Playlist URL を入力: `https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ`
4. **Analyze** をクリック
5. Console に `[PERF]` ログが出たらコピペ

---

## テスト結果（手動入力用テンプレート）

### Test 1: Cold Run（サーバ再起動直後）

**ブラウザ Console に出たログをコピペ:**
```
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=... network_ms=... json_ms=... render_ms=... total_ms=... payload_bytes=...
```

**ターミナル Backend に出たログをコピペ:**
```
[PERF] source=spotify url_len=56 fetch_ms=... enrich_ms=... total_backend_ms=... total_api_ms=... tracks=...
```

**Cold Run のメモ:**
- 所要時間: ___ 秒
- 特記事項: _______________

---

### Test 2: Warm Run 1（同じURLで再実行、リロードなし）

**ブラウザ Console:**
```
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=... network_ms=... json_ms=... render_ms=... total_ms=... payload_bytes=...
```

**ターミナル Backend:**
```
[PERF] source=spotify url_len=56 fetch_ms=... enrich_ms=... total_backend_ms=... total_api_ms=... tracks=...
```

**Warm Run 1 のメモ:**
- 所要時間: ___ 秒
- Cold Run との差: _______________

---

### Test 3: Warm Run 2（3回目、同じURL）

**ブラウザ Console:**
```
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=... network_ms=... json_ms=... render_ms=... total_ms=... payload_bytes=...
```

**ターミナル Backend:**
```
[PERF] source=spotify url_len=56 fetch_ms=... enrich_ms=... total_backend_ms=... total_api_ms=... tracks=...
```

**Warm Run 2 のメモ:**
- 所要時間: ___ 秒
- Warm Run 1 との差: _______________

---

## 分析

### ボトルネック判定

```
□ network_ms が支配的（1000ms以上）
□ render_ms が支配的（500ms以上）
□ 全体的に遅い（>1500ms）
□ 特に問題なし（<1000ms）
```

**結論:**

---

## 改善案

基づき、以下の改善を提案します:

### 案1: TTL キャッシュ（network_ms 短縮）

**対象:** Spotify API フェッチ結果

**実装:**
- Playlist URL を正規化（パラメータ削除）
- Redis or インメモリ TTL cache を使用
- TTL: 6-24時間

**期待効果:** network_ms を 10-50ms に削減（2回目以降）

---

### 案2: React 最適化（render_ms 短縮）

**対象:** displayedTracks フィルタ・レンダリング

**実装:**
- `displayedTracks` を useMemo でメモ化
- TrackRow コンポーネント化＋React.memo
- 大量トラック時は仮想スクロール（react-window）

**期待効果:** render_ms を 50-100ms 以下に抑制

---

### 案3: Rekordbox マッチング最適化（xml_ms 短縮）

**対象:** mark_owned_tracks() 処理

**実装:**
- マッチングキーをハッシュ化
- 4段階マッチを段階的（fail-fast）に実装
- インデックスデータ構造の改善

**期待効果:** xml_ms を 50%短縮

---

## 推奨実装順序

1. **優先度 HIGH**: TTL キャッシュ（最小コストで最大効果）
2. **優先度 MEDIUM**: React 最適化（大量トラック時の応答性向上）
3. **優先度 LOW**: Rekordbox 最適化（XML がない場合は不要）

---

## 次のステップ

テスト結果をもらったら:
1. ボトルネックを判定
2. 優先度が最も高い改善案を実装（P1.1）
3. 改善前後で計測して効果を確認
