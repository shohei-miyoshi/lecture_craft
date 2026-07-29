# LectureCraft 研究・開発引き継ぎ書（公開版）

- 最終更新: 2026-07-28
- 対象: 研究進捗の共有，開発引き継ぎ，別環境の Codex との共有
- 公開方針: 認証情報，個人情報，内部ネットワーク情報，実データを含めない

## 1．この文書の目的

この文書は，LectureCraft の研究目的，現在のシステム構成，実装済み機能，未完成部分，実験計画，今後の開発順序を1か所にまとめた引き継ぎ資料である．

公開リポジトリで共有することを前提とし，次の情報は記載しない．

- API キー，パスワード，Cookie，セッショントークン．
- 実験参加者の氏名，ユーザ名，メールアドレス，利用ログ．
- 大学・研究室内ネットワークの IP アドレス，サーバ名，SSH 情報．
- 実サーバのユーザ名，絶対パス，gateway 名，公開 URL．
- 未公開の講義 PDF，生成音声，生成動画，研究データ．

## 2．研究の最終目標

LectureCraft は，講義スライド PDF を入力として，学習者にとって分かりやすい講義メディアを半自動生成するシステムである．

単にスライド内の文字を読み上げるのではなく，次の情報を踏まえた「講義として自然な説明」の生成を目指す．

- スライド内の重要概念と補足概念．
- 概念間の前提関係，因果関係，比較関係．
- 図表や数式が伝えている意味．
- 学習者が理解しやすい説明順序．
- 各台本文とスライド領域との対応．
- 詳細度，難易度，提示形態などの学習者要求．

AI が一度で完成品を生成することは前提にしない．AI 生成とユーザ確認を組み合わせ，ユーザの修正を品質保証と将来の生成改善の両方に利用する．

## 3．中心となる研究課題

本研究では，特に次の2点を検証する．

### 3.1 Knowledge Graph の生成利用

スライドをテキストの集合ではなく概念構造を持つ教材として扱い，Knowledge Graph（以下，KG）を台本生成の中間表現として利用する．

検証したい問いは次のとおりである．

- KG を使うことで重要概念の説明漏れが減るか．
- 概念間のつながりと説明順序が自然になるか．
- 図表と台本の対応が改善するか．
- ユーザの台本修正量が減るか．

### 3.2 ユーザ修正ログの次回生成への利用

台本，領域，対応付けの修正を単なる操作履歴ではなく，生成改善に使えるデータとして保存する．

検証したい問いは次のとおりである．

- 過去の類似修正をプロンプトへ反映すると，同じ種類の誤りが減るか．
- ユーザごとの説明傾向や修正傾向を反映できるか．
- 修正文字数，修正時間，操作回数が減るか．
- 十分なデータが得られた場合，SFT や DPO へ発展できるか．

## 4．参考にしている先行研究

### 4.1 ユーザ編集から選好を推定する研究

Gao らの「Aligning LLM Agents by Learning Latent Preference from User Edits」では，過去の編集履歴から自然言語の preference を推定し，類似文脈の次回生成プロンプトへ反映する PRELUDE / CIPHER が提案されている．

- 論文: <https://arxiv.org/abs/2404.15269>
- LectureCraft への示唆: 初期段階ではモデルを再学習せず，類似修正の検索とプロンプト反映から始める．

### 4.2 ユーザ編集を複数の学習信号として扱う研究

Misra らの「Principled Fine-tuning of LLMs from User-Edits」では，`context`，`model output`，`user edit` の組を，SFT の教師データ，DPO の選好ペア，編集コスト学習へ利用する考え方が整理されている．

- 論文: <https://arxiv.org/abs/2601.19055>
- LectureCraft への示唆: 最終文だけでなく，修正前後，文脈，編集距離，モデル・プロンプト版を保存する．

### 4.3 人間の post-edit を逐次反映する研究

Karimova らの「A User-Study on Online Adaptation of Neural Machine Translation to Human Post-Edits」では，人間の修正を逐次的にオンライン適応へ利用し，翻訳品質と編集負担を評価している．

- 論文: <https://arxiv.org/abs/1712.04853>
- LectureCraft への示唆: 生成品質だけでなく，編集時間，編集距離，操作回数などの人間側の負担を測定する．

## 5．システム全体構成

```text
Browser
  |
  v
Frontend Studio
  |  HTTPS / same-origin gateway
  v
Backend API
  |
  +-- Authentication / Authorization
  +-- Project / Draft / Revision
  +-- Generation Run / Job
  +-- Layout / Script / Assignment
  +-- Preview Audio / Final Render
  +-- Research Log / Export
  |
  +--> Database
  |
  +--> Artifact Storage
  |
  +--> Generation Pipeline
       +-- PDF and slide image processing
       +-- LayoutParser
       +-- LLM script generation
       +-- KG prototype
       +-- TTS
       +-- Highlight animation
       +-- Video and audio export
```

### 5.1 Frontend

React + Vite で実装している．主な責務は次のとおりである．

- ログインとプロジェクト一覧．
- PDF 選択と生成条件の入力．
- 領域確認，台本確認，対応付け確認．
- 台本・領域・対応関係の編集．
- 音声付き通常プレビュー．
- シーク，再生速度変更，文クリック再生．
- 最終レンダーと成果物の書き出し．
- 管理者向け実験条件・研究データ確認．

### 5.2 Backend

FastAPI を中心に実装している．主な責務は次のとおりである．

- 認証，認可，CSRF 検証．
- プロジェクト，draft，revision の保存．
- 非同期生成 job と進捗管理．
- PDF，スライド画像，中間成果物の artifact 管理．
- LayoutParser，台本生成，対応付け，TTS，動画生成の実行．
- KG，修正ログ，prompt 条件，研究用 export の管理．

### 5.3 Database と Artifact Storage

DB を台帳，ファイルストレージを PDF・画像・音声・動画の正本として扱う．DB にはファイル本体ではなく，artifact ID，相対 storage key，hash，MIME，所有者，生成 run などを保存する．

ローカル開発は SQLite 互換で動作する．実運用では PostgreSQL を利用する設計だが，本番移行と運用検証は継続課題である．schema 変更には Alembic を使用する．

## 6．現在の生成・確認フロー

### 6.1 プロジェクト作成

1. ユーザがプロジェクトを作成する．
2. PDF を multipart upload する．
3. PDF を artifact として保存し，project と関連付ける．
4. 生成条件と利用区分を指定し，generation run を作成する．

### 6.2 LayoutParser と台本生成

1. LayoutParser の領域結果を先に利用可能にする．
2. ユーザは領域確認を開始する．
3. 領域確認中もバックエンドでは台本生成を並行して進める．
4. これにより，待ち時間を編集時間として利用する．

### 6.3 段階確認

確認ステップを使用する場合，順序は次のとおりである．

1. 領域確認．
2. 台本確認．
3. 領域と台本の対応付け確認．
4. 全体編集とプレビュー．

対応付けは，確認済みの領域 revision と確認済みの台本 revision を入力として実行する．領域確認前の LayoutParser 出力をそのまま使わない．

対応付け LLM へ渡す情報は次のとおりである．

- ユーザ編集後の領域 JSON．
- 編集後の領域を描画したスライド画像．
- 確認済み台本．
- 文ID，領域ID，スライド番号などの参照情報．

### 6.4 プレビュー

台本確認完了時に，文単位 TTS を先行生成する．全体編集画面へ進んだ時点で，音声付きプレビューをすぐ再生できる状態を目指す．

台本編集後は音声を stale とし，再生ボタンが押された時に変更文だけを再生成する．未変更文は文単位キャッシュを再利用する．

通常プレビューでは，次の分担を採用している．

- 音声: バックエンドで生成した実音声．
- ハイライト: フロントエンドのスライドレイヤで同期表示．
- 再生基準: 音声の `currentTime`．
- 文同期: TTS 生成結果の `sentence_id` と実測 `start_sec / end_sec`．

文クリック時には該当文の実測開始位置へシークして再生する．中央台本，右側台本，シークバー，アクティブ文は同じ TTS タイムラインを利用する．

### 6.5 書き出し

提示形態ごとに次の成果物を扱う．

- 音声のみ: 音声ファイル，台本，編集データ，操作ログ．
- ハイライトなし動画: スライド動画，音声，台本，編集データ，操作ログ．
- ハイライトあり動画: ハイライト動画，ハイライトなし動画，音声，台本，編集データ，操作ログ．

動画生成は非同期 job とし，進捗と簡潔な状態メッセージを画面に表示する．

## 7．実装状況

| 項目 | 状態 | 補足 |
|---|---|---|
| ユーザ認証とロール | 実装済み | 一般ユーザと管理者を区別する |
| プロジェクト所有者確認 | 実装済み | project，artifact，job，export で確認する |
| PDF のサーバ保存と再読込 | 実装済み | リロード後も artifact から復元する |
| generation run と job | 実装済み | 生成条件と成果物を run 単位で追跡する |
| 領域確認と並行台本生成 | 実装済み | 領域結果を先行表示する |
| 段階確認の順序制御 | 実装済み | 領域，台本，対応付けの順に進む |
| 編集後領域を使う対応付け | 実装済み | JSON と描画画像を利用する |
| 台本確認後の TTS 先行生成 | 実装済み | 文単位キャッシュを利用する |
| 編集文だけの音声更新 | 実装済み | 再生時に stale 文を更新する |
| 文クリック再生 | 実装済み | TTS 実測タイミングへシークする |
| 音声・中央台本同期 | 実装済み | sentence ID と実測時間を利用する |
| 音声・動画・HL動画の書き出し | 実装済み | 実運用環境での追加 E2E が必要 |
| Storage V2 | 実装済み | DB 台帳 + ArtifactStore |
| 編集イベント保存 | 実装済み | before / after / edit type を保存する |
| correction memory | 試作済み | 同一プロジェクト中心の検索である |
| 匿名 JSONL export | 試作済み | 本番データでの再監査が必要 |
| KG モード切替 | 試作済み | off / slide / global / global_slide |
| 軽量 KG 生成・保存 | 試作済み | 台本生成後の自動抽出が中心である |
| KG-first 台本生成 | 未完成 | 台本生成前の KG 構築と注入が必要 |
| ファインチューニング | 未実装 | データ量と匿名化方針の確立後に検討する |

## 8．保存設計

主要データは次の単位で管理する．

| データ | 役割 |
|---|---|
| `projects` | 所有者，名称，利用区分，現在状態 |
| `project_drafts` | 自動保存される最新編集状態 |
| `project_revisions` | 確認完了・明示保存時の変更不能な状態 |
| `generation_runs` | PDF，条件，model，prompt，実験採否 |
| `jobs` | 非同期処理の状態，進捗，失敗理由 |
| `artifacts` | PDF，画像，JSON，音声，動画の台帳 |
| `artifact_relations` | 入力，出力，派生関係 |
| `review_stage_versions` | 領域，台本，対応付けの確定状態 |
| `edit_events` | 編集前後，対象，編集種別，文脈 |
| `correction_memories` | 次回生成へ再利用する修正傾向 |
| `knowledge_graph_versions` | KG 本体と参照情報 |

ブラウザ保存を正本にしない．draft は debounce 付きでサーバへ同期し，version 不一致は競合として扱う．保存失敗をローカルだけで成功扱いにしない．

## 9．修正ログ活用の現在地

### 9.1 保存形式

将来の検索，SFT，DPO，評価器学習へ展開できるよう，少なくとも次を保持する．

```json
{
  "generation_run_id": "run_xxx",
  "entity_type": "sentence",
  "entity_id": "sentence_xxx",
  "edit_type": "script_rewrite",
  "before": {"text": "before"},
  "after": {"text": "after"},
  "slide_context": {},
  "kg_node_ids": [],
  "region_ids": [],
  "prompt_version": "prompt_v1"
}
```

公開・研究 export では，実ユーザIDや内部パスを匿名識別子へ置換する．

### 9.2 現在の再利用

実験条件でログ再利用が有効な場合，保存済み correction memory を取得し，台本生成用の研究コンテキストへ追加する試作がある．

ただし，現在の検索は同一プロジェクト中心であり，次の研究目標を満たすには拡張が必要である．

- 別プロジェクトを含む類似スライド検索．
- embedding を用いた意味的類似度検索．
- 修正内容から preference summary を抽出する処理．
- 不適切・矛盾・古い memory を除外する品質管理．
- ユーザ単位，実験単位，共通 memory の分離．

## 10．KG 活用の現在地

現在は，生成済み台本から概念語を抽出し，概念の共起，説明順序，スライド・領域参照を持つ軽量 KG を生成・保存できる．

これは実験基盤の試作であり，最終目標である KG-first 台本生成とは異なる．今後は次の順序へ変更する必要がある．

1. LayoutParser 結果とスライド画像・テキストから KG を生成する．
2. 全体概念とスライド概念を分離する．
3. 前提，因果，比較，例示などの edge を検証する．
4. ユーザが必要に応じて KG を確認・修正する．
5. 確定 KG を台本生成プロンプトへ注入する．
6. KG なし条件と同一入力で比較する．

## 11．セキュリティ

コード上で導入している主な対策は次のとおりである．

- パスワードの平文保存を行わず，salt 付き hash を保存する．
- セッションを JavaScript から読めない HttpOnly Cookie で扱う．
- 本番 Cookie では Secure と SameSite を使用する．
- 状態変更 API で CSRF token を検証する．
- project，artifact，job，research export の所有者を確認する．
- 管理者 API と管理者 UI を role で制限する．
- 生成 API に rate limit を設ける．
- API キーをフロントへ渡さず，バックエンド環境変数で管理する．
- secret 検査を commit 前に実行する．

ただし，コードに対策が存在することと，本番環境が安全であることは同義ではない．公開運用前には次を確認する．

- HTTPS reverse proxy と gateway の設定．
- Cookie，CORS，CSRF の実環境検証．
- 権限のない他ユーザによる object access test．
- DB と artifact の別媒体バックアップ．
- ログへの個人情報・秘密情報混入検査．
- 依存パッケージの脆弱性確認．
- エラー画面から内部情報を漏らさないこと．
- 管理者アカウントの強固な認証．

Passkey は将来候補であるが，最低限の認証・認可・Cookie・CSRF・バックアップ・監査を先に完成させる．

## 12．これまでに重点的に修正した問題

- PDF を保存後に再度開くと消える問題．
- ブラウザ状態とサーバ draft が無言でずれる問題．
- 古いプロジェクトが Storage V2 で開けない問題．
- 領域確認前の領域で対応付けが実行される問題．
- 編集後領域の画像が対応付け LLM に渡らない問題．
- 台本確認後すぐに音声プレビューを使えない問題．
- 台本編集後に全音声を再生成する問題．
- シークバー，アクティブ文，中央台本がずれる問題．
- 音声のみ・ハイライトなし動画の処理分岐が壊れる問題．
- 書き出し中の進捗と失敗理由が分かりにくい問題．
- 管理者機能が一般ユーザにも表示される問題．
- 保存先が複数フォルダへ分散する問題．

## 13．実験計画

### 13.1 実験前の成立性確認

最初に，システムが研究データを欠損なく保存できるかを確認する．

- 同じ PDF と条件で再現可能な run が作れること．
- 修正前後と操作時刻が保存されること．
- 一般利用と実験利用を区別できること．
- 実験対象 run を candidate / included / excluded で管理できること．
- 匿名 export に秘密情報が含まれないこと．

### 13.2 KG の効果

比較条件は次の候補から段階的に絞る．

- KG なし．
- スライド KG．
- 全体 KG．
- 全体 + スライド KG．

評価指標は次のとおりである．

- 重要概念の説明漏れ．
- 説明順序の自然さ．
- 図表説明の十分さ．
- 台本修正文字数と編集距離．
- 修正時間と操作回数．

### 13.3 修正ログ再利用の効果

比較条件は次のとおりである．

- 修正ログ反映なし．
- correction memory 反映あり．
- preference summary 反映あり．
- 将来的な fine-tuning / DPO．

最初から全条件を同時に実施せず，検索型プロンプト反映の効果を確認してから学習系へ進む．

### 13.4 確認ステップの分析

- 領域確認での修正数．
- 台本確認での修正数．
- 対応付け確認での修正数．
- 各段階の所要時間．
- 後工程で差し戻された修正数．

## 14．今後の優先順位

1. 公開運用前の E2E とセキュリティ試験を固定する．
2. PostgreSQL，バックアップ，容量監視を実運用環境で確認する．
3. 研究 run の選定と匿名 export を管理画面で完結させる．
4. KG-first 台本生成を実装する．
5. correction memory を意味検索と preference summary へ拡張する．
6. 小規模 pilot で修正ログの欠損と UI 負担を確認する．
7. KG 条件比較を行う．
8. 修正ログ反映条件の比較を行う．
9. 十分なデータ量が得られた後に fine-tuning / DPO を検討する．

## 15．既知の技術的課題

- 現在の軽量 KG はルールベース抽出が中心で，教材構造理解として不十分である．
- correction memory の検索範囲と類似度評価が限定的である．
- SQLite から PostgreSQL への本番切替を継続検証する必要がある．
- job worker の再起動・多重実行・長時間処理の耐障害性を追加検証する必要がある．
- 動画生成は外部依存と処理時間が大きく，失敗時の再開戦略が必要である．
- LayoutParser の品質評価と将来的な fine-tuning 用データ整備が必要である．
- UI のアクセシビリティ，モバイル表示，キーボード操作の体系的試験が不足している．
- 実際の利用者による end-to-end 評価は今後実施する必要がある．

## 16．別PCのCodexへの引き継ぎ

### 16.1 最初に読むファイル

1. `docs/research-progress-design-lecturecraft.md`．
2. `README.md`．
3. `docs/api-contract.md`．
4. `frontend/src/App.jsx`．
5. `frontend/src/hooks/usePreviewPlayback.js`．
6. `frontend/src/store/reducer.js`．
7. `backend/app/main.py`．
8. `backend/app/jobs.py`．
9. `backend/app/storage_persistence.py`．
10. `backend/app/service.py`．

### 16.2 主要ディレクトリ

```text
frontend/
  src/
    components/       UI
    hooks/            preview and playback
    store/            editor state
    utils/            API and project persistence clients

backend/
  app/
    main.py           API endpoints and security boundary
    jobs.py           asynchronous generation jobs
    persistence.py    users, experiments, edit logs, research export
    storage.py        ArtifactStore
    storage_persistence.py
                      Storage V2 projects, drafts, runs, revisions, artifacts
    service.py        generation, TTS, KG prototype, export
  tests/
    test_storage_v2.py
    test_review_assignment_visuals.py
```

### 16.3 開発時の原則

- DB と artifact を正本とし，ブラウザ保存へ戻さない．
- 対応付けは確認済み領域と確認済み台本からのみ実行する．
- 台本変更は音声と対応付けを stale にする．
- 領域変更は対応付けだけを stale にし，音声を再生成しない．
- 通常プレビューで毎回動画を生成しない．
- 音声再生は audio `currentTime` と TTS 実測タイミングを基準にする．
- 一般利用 run と実験 run を混在させない．
- ユーザデータや内部環境情報を公開リポジトリへ追加しない．
- 既存のユーザ変更を確認せずに削除・上書きしない．

### 16.4 基本検証

```bash
cd frontend
npm run lint
npm run build
```

```bash
cd backend
python -m pytest -q
```

秘密情報検査:

```bash
bash scripts/check_secrets.sh --tracked
```

## 17．完了条件

研究システムとしての完了条件は，単に動画が生成できることではない．

- PDF から領域，台本，対応付け，音声，動画まで一貫して生成できる．
- ユーザ修正後の状態が全工程とプレビューへ正しく反映される．
- 入力，条件，中間表現，修正，最終成果物を run 単位で再現できる．
- KG の有無と修正ログ反映の有無を実験条件として比較できる．
- 修正量，修正時間，説明漏れ，説明順序を評価できる．
- 認証・認可・匿名化・バックアップを含め，実運用に耐えられる．
- 利用を重ねることで，同じ種類の修正負担が減ることを実験で示せる．

LectureCraft の最終的な目標は，「スライドを入れると講義メディアが出るシステム」ではなく，「スライド構造を理解し，ユーザの意図を学習しながら，講義として意味のある説明を継続的に生成できるシステム」である．
