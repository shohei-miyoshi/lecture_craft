# KG 比較基盤メモ

この branch では、助教コードベースの `raw` KG 抽出を LectureCraft に最小統合した上で、**同一 branch 内で複数 variant を比較するための土台**を追加した。

## 1. backend 側の整理

対象ファイル:

- [backend/app/kg_preview_service.py](/Users/shohei/Documents/dev/lecture_craft/backend/app/kg_preview_service.py)
- [backend/app/main.py](/Users/shohei/Documents/dev/lecture_craft/backend/app/main.py)
- [backend/app/models.py](/Users/shohei/Documents/dev/lecture_craft/backend/app/models.py)

追加したもの:

- `KgVariantSpec`
  - variant の `id / label / description / kind / enabled / runner` を持つ registry 用定義。
- `KgRunContext`
  - 同じ PDF, 同じ model, 同じ画像列を各 variant に共有するための実行コンテキスト。
- variant registry
  - `raw`
  - `evidence_proto`
  - `normalized_json`
  - `multirel_proto`
  - `order_plan_proto`

ポイント:

- `raw` は助教コード由来の prerequisite 抽出をそのまま比較 payload に載せる baseline。
- `evidence_proto` は `raw` の edge をそのまま土台にしつつ、各 node / edge に `slide_refs`, `evidence_text`, `importance`, `rationale` を付与する改良版。
- `normalized_json` は **新しい LLM 呼び出しを増やさず**、`raw` の結果を再利用して重複・自己ループを整理する比較用 variant。
- `multirel_proto` は **概念集合を固定したまま** `explains / example_of / contrasts_with / part_of / used_for / step_before` などの relation を許し、説明向けのつながりへ拡張する variant。
- `order_plan_proto` は **KG と説明順を分離** して、後段の台本生成へ渡しやすい step 列を別 payload として返す variant。
- compare 実行では **同じ model** を共有し、差分は variant 実装由来に限定する。

## 2. catalog 保存

保存先:

- `backend/outputs/kg_preview/catalog/<result_id>/`

各 result に保存するもの:

- `result.json`
- `triplets.csv`
- `raw_response.txt`
- `prompt.txt`
- `metadata.json`
- `knowledge_graph.dot`
- `knowledge_graph.png/svg`（Graphviz がある環境のみ）

`result.json` に入る主な情報:

- `result_id`
- `variant`
- `summary`
- `triplets`
- `graph`
- `artifacts`
- `raw_response`
- `material_fingerprint`

ここで `material_fingerprint` は PDF bytes の SHA-256 で、**同一 PDF の過去結果を引くキー**として使う。

## 3. 新しい API

- `GET /api/kg-preview/variants`
  - registry 一覧と default model を返す。
- `POST /api/kg-preview/compare`
  - 複数 variant を同時実行して `results[]` を返す。
- `GET /api/kg-preview/results`
  - catalog の要約一覧を返す。
- `GET /api/kg-preview/results/{result_id}`
  - 保存済み詳細 payload を返す。
- `POST /api/kg-preview`
  - 互換用。内部では `raw` 1件 compare の wrapper。

## 4. frontend 側の整理

対象ファイル:

- [frontend/src/components/KgPreviewPanel.jsx](/Users/shohei/Documents/dev/lecture_craft/frontend/src/components/KgPreviewPanel.jsx)
- [frontend/src/components/RightPanel.jsx](/Users/shohei/Documents/dev/lecture_craft/frontend/src/components/RightPanel.jsx)
- [frontend/src/components/LeftPanel.jsx](/Users/shohei/Documents/dev/lecture_craft/frontend/src/components/LeftPanel.jsx)
- [frontend/src/store/reducer.js](/Users/shohei/Documents/dev/lecture_craft/frontend/src/store/reducer.js)

状態管理:

- `kgVariants`
- `kgSelectedVariantIds`
- `kgSelectedResultIds`
- `kgComparisonResults`
- `kgCatalog`
- `kgBusy`
- `kgError`
- `kgDefaultModel`

変更内容:

- `KG` タブは単発 preview から **比較ビュー**へ変更。
- variant は最大 3 件まで選択可能。
- `比較実行` で selected variants を batch 実行。
- `保存済み結果` から同一 PDF 優先で catalog を引き、過去結果を比較面に追加可能。
- Graphviz がなくても、triplet から **ブラウザ内 SVG** を描いて比較できる。

## 5. 実装上の線引き

今回まだ入れていないもの:

- スライド領域単位の根拠
- relation 自体を人手編集する UI
- KG 編集 UI

今回入れたものは、**raw / 根拠付き / JSON整形 / 多関係 / 説明順分離** を同一 branch で比較するための基盤。
