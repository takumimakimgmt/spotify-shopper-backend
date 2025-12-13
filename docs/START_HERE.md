# P1.0 / P1.1 Performance Metrics - Start Here

## 📊 Phase P1.0: 計測機能の実装（完了）

フロント・バックエンド両側に **詳細な性能計測機能** を実装。

- **フロント**: Network / JSON parse / React rendering の時間を計測
- **バック**: Playlist取得 / ISRC enrichment / Rekordbox照合 の時間を計測

---

## 🎯 Phase P1.1: ボトルネック特定 & 改善実装（進行中）

### Step 1: テスト実行

1. **QUICK_RUN.md** を読む（10分のテスト手順）
2. cold/warm run を3回実行
3. `[PERF]` ログを **PERF_RESULTS.md** に記入

### Step 2: 分析

1. PERF_RESULTS.md の結果を見て、何が支配的かを判定
2. **P1.1_IMPLEMENTATION_GUIDE.md** で対応する改善案を確認

### Step 3: 改善実装（オプション）

ボトルネック別に最小改善を実装
- Case A: TTL キャッシュ（network_ms が支配）
- Case B: React 最適化（render_ms が支配）
- Case C: マッチング最適化（xml_ms が支配）

---

## 📖 ドキュメント構成

**P1.0 計測:**
- TEST_CHECKLIST.md - テスト実行手順（5分版）
- PERF_TESTING.md - 詳細テストガイド
- P1.0_IMPLEMENTATION.md - 計測コードの説明

**P1.1 改善:**
- QUICK_RUN.md - 実行手順（10分）
- PERF_RESULTS.md - テスト結果テンプレート
- P1.1_IMPLEMENTATION_GUIDE.md - 改善案とコード例

---

**👉 次: QUICK_RUN.md を読んでテストを実行してください！**
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
