# P1.1: Quick Test Run

## 📝 実行手順（10分）

### Step 1: サーバ起動確認

両方が起動しているか確認（ターミナルに `uvicorn running` / `ready - started server` が出ているか）

```bash
# バックエンド起動（ターミナル1）
cd /Users/takumimaki/dev/spotify-shopper
PYTHONPATH=/Users/takumimaki/dev/spotify-shopper \
  /Users/takumimaki/dev/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000

# フロント起動（ターミナル2）
cd /Users/takumimaki/dev/spotify-shopper-web
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev
```

### Step 2: ブラウザを開く

- URL: http://localhost:3000
- DevTools 開く（F12）→ Console タブ

### Step 3: Cold Run テスト

1. **ハード更新** (Cmd+Shift+R)
2. Playlist URL を入力:
   ```
   https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ
   ```
3. **Analyze** をクリック
4. Console に `[PERF]` ログが出たら **スクリーンショット or コピペ**

**コピペ対象:**
- ブラウザ Console: `[PERF] url=... tracks=... network_ms=...` の行
- ターミナル1: `[PERF] source=spotify ...` の行

### Step 4: Warm Run 1 テスト

1. **ページリロードなし** で、同じ URL を再度入力
2. **Analyze** をクリック
3. 同じようにログをコピペ

### Step 5: Warm Run 2 テスト

1. もう1回 Analyze（3回目）
2. ログをコピペ

---

## 📋 結果を記入する場所

`spotify-shopper/docs/PERF_RESULTS.md` の以下の場所に貼り付け:

```markdown
## テスト結果（手動入力用テンプレート）

### Test 1: Cold Run（サーバ再起動直後）

**ブラウザ Console に出たログをコピペ:**
```
[PERF] ... ← ここに貼り付け
```

**ターミナル Backend に出たログをコピペ:**
```
[PERF] ... ← ここに貼り付け
```
```

---

## 💡 期待される [PERF] ログ

**ブラウザ Console:**
```
[PERF] url=https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ tracks=70 network_ms=450.3 json_ms=28.5 render_ms=120.7 total_ms=599.5 payload_bytes=87543
```

**ターミナル Backend:**
```
[PERF] source=spotify url_len=56 fetch_ms=445.1 enrich_ms=0.0 total_backend_ms=445.1 total_api_ms=448.8 tracks=70
```

---

## ⏱️ タイムアウト時の対処

- Console に `[PERF]` が出ない → ページリロード試す
- ターミナルで [PERF] が出ない → Analyze クリック時にターミナルを見ておく
- 30秒以上かかる → バックエンドのログを確認（エラーがないか）

---

**👉 さあ、テストを実行してください！**
