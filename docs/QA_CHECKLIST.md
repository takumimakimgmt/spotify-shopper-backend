# QA Checklist: Cache / Concurrency / UI

## 前提条件

- Backend: `http://127.0.0.1:8000` 起動確認（`GET /health` で `{"status": "ok"}`）
- Frontend: `http://localhost:3000` 起動確認
- **Spotify user playlist URL** を用意（editorial `37i9...` はNG）
  - または Apple Music playlist URL

---

## A) キャッシュ効いてる？

### 手順

1. **ブラウザ DevTools → Network タブを開く**
2. **URL入力欄** に Spotify playlist URL を貼る
3. **[Analyze] クリック** → 完了まで待つ
   - 🔴 **Backend ログを見て**: `[PERF]` 行で `cache_hit=false` を確認
   - 📊 **Network**: `GET /api/playlist?url=...` リクエストの時間を記録（例：`1200ms`）
4. **同じ URL で再び [Analyze] クリック** → 完了まで待つ
   - 🟢 **Backend ログ**: `cache_hit=true` を確認
   - 📊 **Network**: 同じリクエストの時間を記録（例：`50ms`）

### 期待値

| 実行 | cache_hit | 時間 | 理由 |
|------|-----------|------|------|
| 1回目 | `false` | ~1000ms+ | Spotify API 呼び出し |
| 2回目 | `true` | ~50ms以下 | キャッシュヒット |

### ✅ 合否判定

- [ ] 2回目の `cache_hit=true` が確認できた
- [ ] 2回目の時間が **10倍以上高速化** された

---

## B) refresh bypass 効く？

### 手順

1. **ブラウザコンソール**（F12 → Console）を開く
2. **URLが入った状態で [Analyze] → 完了**
   - Backend ログで `cache_hit=true` を確認
3. **再度 [Analyze] → 完了**
4. **以下のいずれかで refresh=1 を送信：**
   - **オプション A**: フロント側に Shift+Click サポートを追加（未実装）
   - **オプション B**: URL に `?refresh=1` を手動追加
     ```
     GET http://127.0.0.1:8000/api/playlist?url=<url>&source=spotify&refresh=1
     ```
   - **オプション C**: 開発者向け fetch コマンドをコンソールで実行
     ```javascript
     fetch('http://127.0.0.1:8000/api/playlist?url=<url>&source=spotify&refresh=1')
       .then(r => r.json())
       .then(d => console.log('Tracks:', d.tracks.length));
     ```

### 期待値

| refresh パラメータ | cache_hit | 動作 |
|------------------|-----------|------|
| なし（3回目） | `true` | キャッシュ使用 |
| `?refresh=1` | `false` | キャッシュバイパス，新フェッチ |

### ✅ 合否判定

- [ ] refresh=1 でキャッシュがバイパスされた（cache_hit=false）
- [ ] refresh=1 で新しいプレイリスト内容が返された

---

## C) 混線防止（Concurrency Safety）

### 手順

1. **異なる 2つの URL を用意** したら以下実行：
   - URL1（A）: Spotify playlist
   - URL2（B）: 別の Spotify playlist
2. **URL1 を入力 → [Analyze] クリック**（ボタン無効化されるはず）
3. **すぐに** URL欄を URL2 に変更
4. **[Analyze] クリック**（既に実行中なので disable？）
5. **処理中に [Cancel] ボタンが出ていれば** クリック
6. **処理完了を待つ**
7. **最終的に表示される結果を確認**

### 期待値

| 段階 | 期待動作 |
|------|---------|
| Analyze実行中 | 他のボタン/フォーム無効化（disabled） |
| キャンセル後 | スピナー/プログレスバー消える、ボタン有効化される |
| 最終結果 | 最後に [Analyze] した URL の結果だけ表示（混在なし） |

### ✅ 合否判定

- [ ] Analyze 中は Analyze ボタン無効
- [ ] Cancel で正しく中断される
- [ ] 最終結果は 1つの URL だけ（混線なし）
- [ ] コンソール エラーなし

---

## D) Processing表示が1本か？

### 手順

1. **ブラウザで DevTools → Elements タブを開く** （DOMを監視）
2. **Analyze 中：**
   - プログレスバー / スピナーが **1つだけ** 表示されているか確認
   - テキストは "Analyzing..." または同等
3. **XML ファイルを選択 → Re-analyze クリック：**
   - 同じバー / スピナーが再利用される（新たには出ない）
   - テキストが "Re-analyzing..." に変わるか確認
4. **処理完了 → すぐに**
   - バー / スピナー消える
   - UI が前の状態に戻る

### 期待値

| フェーズ | 表示状態 |
|---------|---------|
| Idle | ローディング UI なし |
| Analyze中 | プログレスバー 1本 + "Analyzing..." |
| Re-analyze中 | 同じプログレスバー + "Re-analyzing..." |
| 完了 | ローディング UI 消える |

### ✅ 合否判定

- [ ] Analyze中に **バー/スピナーが1つだけ** 表示
- [ ] Re-analyze でも **バー/スピナーは1つ**（重複なし）
- [ ] テキスト表示が正しく切り替わる
- [ ] 完了すぐにローディング UI が消える

---

## 合格基準（All-or-Nothing）

### Go to Production 前
- **A) キャッシュ**: ✅ 2回目が10倍高速
- **B) Refresh**: ✅ ?refresh=1 でバイパス確認
- **C) 混線防止**: ✅ キャンセル + 最後の結果反映
- **D) UI統一**: ✅ バー1本 + テキスト切り替え

**すべての項目が ✅ なら本番OK**

---

## トラブル時

| 症状 | 原因 | 対応 |
|------|------|------|
| キャッシュが効かない | TTLCache が初期化されていない | Backend 再起動 |
| cache_hit が null | ログ出力がない | Backend `logging.basicConfig` 確認 |
| Analyze ボタンが何回も有効に | AbortController ガードが壊れた | `requestIdRef` の更新ロジック確認 |
| バー2本出ている | ProcessingBar が重複レンダー | `page.tsx` で duplicate <div> 確認 |
| キャンセル後に結果が混在 | `finally` の requestId チェック漏れ | `handleAnalyze` の finally ブロック確認 |
| XML size exceeds limit | ファイルが 50MB を超えている | Rekordbox から小さい範囲で XML エクスポート（docs/REKORDBOX_XML_LIMITS.md 参照） |

---

## XML サイズ制限

- **上限**: 50 MB
- **理由**: メモリ効率とパフォーマンス（~50,000 曲目安）
- **エラー時の対応**: Rekordbox から個別プレイリストまたは小範囲の XML をエクスポート
- **詳細**: `docs/REKORDBOX_XML_LIMITS.md` 参照
