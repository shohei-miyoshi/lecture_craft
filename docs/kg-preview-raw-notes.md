# KG Preview Raw Branch Notes

このブランチは、助教コードの prerequisite KG 抽出を LectureCraft に最小統合して、
既存の台本生成にはまだ混ぜずに結果確認だけできるようにしたものです。

## 何をそのまま持ち込んだか

- prerequisite triplet を抽出する発想
- `Is-a-Prerequisite-of` 固定の出力形式
- triplet の正規表現パース
- DAG 判定と cycle correction の流れ

## LectureCraft 側で変えた点

- 独立 API `/api/kg-preview` として呼べるようにした
- 入力は `pdf_base64 + filename` に合わせた
- 既存の PDF キャッシュと画像化処理を再利用した
- 結果確認をしやすいように frontend に `KG` タブを追加した
- Graphviz の Python 依存は増やさず、`.dot` は必ず保存し、`dot` コマンドがある環境だけ PNG/SVG を生成するようにした

## この段階でまだやっていないこと

- 既存の `/api/generate` への統合
- 台本生成プロンプトへの KG 注入
- multi-relation KG への拡張
- slide evidence / provenance の追加
- KG 編集 UI
