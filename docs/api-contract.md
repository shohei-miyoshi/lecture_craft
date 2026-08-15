# LectureCraft API Contract

この文書は，現行のStorage V2とrun中心フローでフロントエンドが利用するHTTP APIの概要です．詳細なschemaは`backend/app/models.py`，実装は`backend/app/main.py`を正とします．

## 基本方針

- ローカル開発の標準Base URLは`http://127.0.0.1:8000`です．
- フロントエンドは`VITE_API_URL`で接続先を設定します．
- PDF本体をBase64 JSONとして送る旧方式は使用しません．
- 生成と書き出しは非同期jobとして開始し，job APIをポーリングします．
- project，run，job，artifactは所有者または管理者だけが参照できます．
- 状態変更APIはセッションCookieに加えてCSRFヘッダを必要とします．

gateway経由で公開する場合も，内部の契約は`/api/...`のままです．gateway adapterがmethodとpathを転送形式へ変換します．

## 認証

### Endpoints

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/auth/guest`

`register`と`login`は次のJSONを受け取ります．

```json
{
  "username": "example_user",
  "password": "example-password"
}
```

ブラウザでは`credentials: "include"`を指定し，`HttpOnly`セッションCookieを利用します．JavaScriptからセッショントークンを直接保存・参照しません．

状態変更APIでは，認証レスポンスの`csrf_token`を次のヘッダへ設定します．

```http
X-LectureCraft-CSRF: <csrf_token>
```

## プロジェクト

### `GET /api/projects`

ログイン中ユーザのプロジェクト一覧を返します．

### `POST /api/projects`

最初にプロジェクトIDを発行します．

```json
{
  "name": "講義プロジェクト",
  "usage_context": "general"
}
```

`usage_context`は`general | research`です．通常利用と実験利用をrun作成前から区別します．

### `GET /api/projects/{project_id}`

最新draft，現在のrun，確認状態，artifact参照をまとめて返します．

### `DELETE /api/projects/{project_id}`

プロジェクトを物理削除せずarchiveします．

## PDF

### `PUT /api/projects/{project_id}/source-pdf`

`multipart/form-data`の`file`へPDFを設定します．サーバはPDF検証，hash計算，保存，source artifact登録を一つの処理として行います．

```bash
curl -X PUT \
  -F "file=@slides.pdf;type=application/pdf" \
  http://127.0.0.1:8000/api/projects/project_id/source-pdf
```

実際のブラウザ呼び出しには認証CookieとCSRFヘッダが必要です．

### 閲覧用Endpoints

#### `GET /api/projects/{project_id}/preferences`

台本編集からLLMで抽出した preference memory を，新しい順に返す．`limit` は 1〜200．所有者だけが取得できる．レスポンスには件数，平均編集距離比率，preference 文，抽出状態，分類，適用範囲，利用文脈を含む．KGは別の生成コンテキストとして管理する．二回目以降の生成への反映は実験条件 `log_reuse_enabled` が有効な場合に行う．

- `GET /api/projects/{project_id}/pdf`
- `GET /api/projects/{project_id}/slides/{slide_idx}/image`
- `GET /api/artifacts/{artifact_id}/content`

いずれも所有者・管理者確認を通してファイルを返します．

## DraftとRevision

### `PUT /api/projects/{project_id}/draft`

編集中の最新状態を保存します．

```json
{
  "base_version": 3,
  "name": "講義プロジェクト",
  "data": {
    "slides": [],
    "sentences": [],
    "highlights": []
  }
}
```

- `base_version`は現在のdraft versionです．
- 一致しない場合は`409 Conflict`とし，無言の上書きを行いません．
- フロントエンドは編集をdebounceして同期します．

### `POST /api/projects/{project_id}/revisions`

最新draftから変更不能なrevisionを作成します．

```json
{
  "revision_kind": "manual_save"
}
```

`revision_kind`は次のいずれかです．

- `manual_save`
- `generation_completed`
- `layout_confirmed`
- `script_confirmed`
- `assignment_confirmed`
- `rendered`

## Generation Run

### `POST /api/projects/{project_id}/runs`

保存済みsource artifactから新しい生成runを開始します．

```json
{
  "source_artifact_id": "artifact_id",
  "detail": "standard",
  "difficulty": "basic",
  "mode": "hl",
  "usage_context": "research",
  "layout_review_enabled": true,
  "script_review_enabled": true
}
```

- `detail`: `summary | standard | detail`
- `difficulty`: `intro | basic | advanced`
- `mode`: `audio | video | hl`
- `usage_context`: `general | research`

サーバはユーザ・実験に設定されたKG条件と修正ログ反映条件を解決し，runへ固定します．正常に受理した場合は`202 Accepted`とjob情報を返します．

### `GET /api/runs/{run_id}`

runの工程状態，進捗，失敗理由，生成条件，artifact一覧を返します．

## Job

### `GET /api/jobs/{job_id}`

非同期処理の状態を返します．

```json
{
  "job_id": "job_id",
  "status": "running",
  "progress": 45,
  "message": "台本を生成しています"
}
```

`status`は主に`queued | running | completed | failed | cancelled`です．完了時は`result`を含みます．

### `POST /api/jobs/{job_id}/cancel`

キャンセル可能なjobへキャンセルを要求します．

## 確認フロー

確認順序は，領域，台本，対応付けです．対応付けは確認済み領域revisionと確認済み台本revisionを入力にします．

### 編集記録

- `POST /api/projects/{project_id}/layout-review`
- `POST /api/projects/{project_id}/script-review`
- `POST /api/projects/{project_id}/events`

before，after，対象ID，操作種別，run IDなどを保存します．

### 確定

`POST /api/projects/{project_id}/review-stages/{stage}`

`stage`は`layout | script | assignment`です．

```json
{
  "run_id": "run_id",
  "draft_version": 4
}
```

### 対応付け

`POST /api/projects/{project_id}/review-assignment`

```json
{
  "run_id": "run_id"
}
```

対応付けは非同期jobです．サーバ側で確認済みrevisionと，編集後領域を描画した画像artifactを取得します．

## 音声プレビュー

### `POST /api/preview/audio`

文単位TTSを生成またはキャッシュから取得し，結合音声と文タイミングを作ります．

```json
{
  "project_id": "project_id",
  "run_id": "run_id",
  "scope": "all",
  "sentences": [],
  "settings": {
    "play_speed": 1.0
  }
}
```

- `scope`: `slide | range | all`
- 台本確認完了時に初版を作成します．
- 台本編集後は変更文だけTTSを再生成します．
- 領域変更だけでは音声を再生成しません．

正常に受理した場合は`202 Accepted`とjob情報を返します．

### `GET /api/preview/audio/{preview_id}/media`

所有者確認後，結合済みプレビュー音声を返します．

## 最終書き出し

### `POST /api/preview/final-render`

固定したproject，run，draft versionから本番相当の動画生成jobを開始します．

```json
{
  "project_id": "project_id",
  "run_id": "run_id",
  "type": "video_highlight",
  "draft_version": 4
}
```

`type`は`video | video_highlight`です．音声のみ成果物は音声プレビュー側のartifactを利用します．

staleな対応付け，音声，revisionの組み合わせでは最終成果物を作らないことを前提にします．

## 実験条件とKG

- `POST /api/experiments/join`
- `GET /api/experiments/current-condition`
- `GET /api/projects/{project_id}/knowledge-graphs/latest`

実験条件には次を含みます．

```json
{
  "kg_mode": "global_slide",
  "log_reuse_enabled": true,
  "review_flow_enabled": true,
  "prompt_strategy_version": "baseline_v1"
}
```

`kg_mode`は`off | slide | global | global_slide`です．クライアント指定ではなく，サーバで解決した条件をrunへ保存します．

## 管理者API

- `GET /api/admin/overview`
- `GET /api/admin/review-settings`
- `PATCH /api/admin/review-settings`
- `GET /api/admin/experiment-conditions`
- `PATCH /api/admin/experiment-conditions`
- `GET /api/admin/artifacts`
- `GET /api/admin/runs`
- `PATCH /api/admin/runs/{run_id}/analysis-status`

runの`analysis_status`は`candidate | included | excluded`です．これにより，通常利用のrunと実験結果として採用するrunを区別します．

## 研究データ

- `POST /api/research/session`
- `POST /api/research/export-jsonl`
- `GET /api/research/exports/{export_id}/content`

JSONL出力と取得は管理者専用です．出力対象はexperiment，project，run ID，採否で絞り込みます．Cookie，セッショントークン，APIキー，内部絶対パスは出力しません．

## Error Format

APIエラーは原則として次の形式です．

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "利用者向けメッセージ"
  }
}
```

代表的なHTTP statusは次のとおりです．

- `400`: 入力不正
- `401`: 未認証
- `403`: 権限不足またはCSRF不正
- `404`: 対象なし
- `409`: draft version競合またはstale状態
- `429`: rate limit
- `500`: 処理失敗
