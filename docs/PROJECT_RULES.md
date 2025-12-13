# Project Permanent Rules (Spotify Shopper)

## 0) 絶対ルール（虚偽禁止）
- 実行していないコマンドを「実行した」と書かない。
- 変更していないのに「Made changes」と言わない。
- できない/未確認は「未確認」と明示し、次に何を確認するかを具体的に書く。

## 1) 方針（プロダクトの核）
- UI/機能は “To Buy / Owned” の2軸に集中。
- Share / Buy modal / Undo / Status / purchaseState 等の系統は追加しない（復活も不可）。
- Ownedの定義は統一：Owned = `owned === true`、To Buy = `owned !== true`（false/null/undefined全部）。
- 体感改善を最優先：初回解析の遅さは、まず計測→原因分離→キャッシュ/描画最適化の順で潰す。

## 2) 変更の進め方（毎回これで）
- まず「影響範囲」を3点で出す：①触るファイル ②消す/足す要素 ③壊れやすい箇所（state/merge/key等）
- そのあと “最小差分” で直す。新規ファイル追加は必要な場合のみ。
- UIの数値/ローディング/バナーは重複表示させない（同じ意味の表示は1箇所）。
- ローディングは **1系統に集約**（busy phase等）。バー/スピナーが二重に出る実装は禁止。

## 3) 非同期安全（必須）
- fetch系は基本 AbortController + requestIdガード。
- `finally` を含め、state更新は “最新requestIdのときだけ” 実行。
- AbortError はユーザーキャンセル扱い（エラー表示しない）。ただしUIは必ず復帰させる。
- Analyze と Re-analyze（XML）は同時実行禁止（busy中はdisable or returnで統一）。

## 4) パフォーマンスの扱い
- perfログは残す（consoleだけでも可）。削る場合は理由と代替を提示。
- backendはURL正規化 + TTL cacheを基本線。必要なら refresh=1 を使える導線はUIを増やさずに入れる（例：Shift+Analyze）。
- “遅い” の改善は、まず network_ms / render_ms / xml_ms どれが支配的かで分岐する。

## 5) 型・データ整合（壊れやすいので丁寧に）
- trackのキー（trackKeyPrimary等）まわりは事故の温床。マージの一貫性を崩さない。
- backendレスポンス形が変わると壊れるので、必要ならruntime validation（Zod等）を提案してよい（ただし最小差分で）。

## 6) ドキュメント生成の制限
- 新しいmdを増やさない（頼まれた時だけ）。
- 既存mdは重複を作らず、入口（START_HERE）を中心に短く保つ。

## 7) 仕上げ（Definition of Done）
- 変更後は必ず：
  - `npm run lint`
  - `npm run build`
  - （backend変更なら）`python -m py_compile ...`
- 完了報告は必ずこの形式：
  1) 何を変えた（箇条書き）
  2) どのファイル（パス付き）
  3) どう確認した（実行したコマンドをそのまま）
  4) 残タスク/リスク（あれば）

## 8) コミット運用
- コミットメッセージは “目的 + 変更点” が分かる短文。
- 1コミット = 1目的（UI整理とキャッシュ追加を混ぜない）。
