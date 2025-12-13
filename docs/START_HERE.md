# P1.0 Performance Metrics - Start Here

## 📊 何が入ったのか？

フロント・バックエンド両側に **詳細な性能計測機能** を実装しました。

- **フロント**: Network / JSON parse / React rendering の時間を計測
- **バック**: Playlist取得 / ISRC enrichment / Rekordbox照合 の時間を計測

**目的:** 「初回解析が長い」という課題を **推測ではなく実測で改善する**

---

## 🎯 今すぐやること（5分）

### 1. セットアップして計測ログを集める

```bash
# ターミナル1: バックエンド
cd /Users/takumimaki/dev/spotify-shopper
PYTHONPATH=/Users/takumimaki/dev/spotify-shopper \
  /Users/takumimaki/dev/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000

# ターミナル2: フロント
cd /Users/takumimaki/dev/spotify-shopper-web
NEXT_PUBLIC_BACKEND_URL="http://127.0.0.1:8000" npm run dev

# ブラウザ: http://localhost:3000 → DevTools Console (F12)
```

### 2. Spotify プレイリスト URL で解析（cold run）

URL例:
```
https://open.spotify.com/playlist/3cEYpjA9oz9GiPac4AsrlZ
```

→ Console に `[PERF] url=... tracks=... network_ms=... json_ms=... render_ms=...` が出る

### 3. 同じ URL で もう1回（warm run）

→ ログを比較

---

## 📖 ドキュメント

| ファイル | 内容 | 用途 |
|---------|------|------|
| **TEST_CHECKLIST.md** | テスト実行手順 | 5分で cold/warm run を実行 |
| **PERF_TESTING.md** | 詳細テスト＆解釈ガイド | ボトルネック診断 |
| **P1.0_IMPLEMENTATION.md** | 実装の詳細 | 計測コードの説明 |

---

## 🔍 ボトルネック判定（実行後）

ログを見て、どこが遅いか判定：

```
network_ms > 1000ms ?
  → Spotify/Apple fetch 遅い
  → 対策: TTL キャッシュ（6-24h）

render_ms > 500ms ?
  → React 描画遅い
  → 対策: displayedTracks memo化、仮想スクロール

xml_ms > 500ms ?
  → Rekordbox 照合遅い
  → 対策: マッチング最適化（ハッシュ化、インデックス）

すべて < 500ms ?
  → 現状OK。特に改善不要。
```

---

## 🚀 次のステップ

1. TEST_CHECKLIST.md を読んで cold/warm run を実施
2. ログを収集 → ボトルネック特定
3. 該当ドキュメント（PERF_TESTING.md or P1.0_IMPLEMENTATION.md）で詳細確認
4. 改善案を実装（計測ベースで）

---

## ファイル構成

```
spotify-shopper/
  └─ docs/
      ├─ START_HERE.md  ← 今ここ
      ├─ TEST_CHECKLIST.md
      ├─ PERF_TESTING.md
      └─ P1.0_IMPLEMENTATION.md

spotify-shopper-web/
  └─ docs/
      ├─ START_HERE.md  ← 今ここ
      └─ QUICK_PERF_TEST.md
```

---

**👉 まずは TEST_CHECKLIST.md または QUICK_PERF_TEST.md を読んでください！**
