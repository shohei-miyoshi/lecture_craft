# kenkyu_project

フロントエンドとバックエンドを同じ Git リポジトリで管理するための monorepo です。

## 構成

```text
kenkyu/
├── frontend/   # React + Vite の研究フロントエンド
├── backend/    # auto_lecture を移した Python バックエンド
└── docs/       # API 仕様と運用手順
```

## まず見る場所

- フロントエンド: `frontend/`
- バックエンド: `backend/`
- API 契約: `docs/api-contract.md`
- MCP サーバ配置手順: `docs/mcp-server-deploy.md`

## ローカル開発

### 最短手順

ターミナルを2つ使う想定です。

```bash
# 1つ目: backend
rm -rf backend/.venv   # 以前の失敗で Python 3.14 の venv が残っている場合だけ
bash scripts/setup_backend.sh
bash scripts/dev_backend.sh
```

```bash
# 2つ目: frontend
cd frontend
npm install
cp .env.example .env
bash ../scripts/dev_frontend.sh
```

バックエンド確認:

```bash
bash scripts/check_backend.sh
```

生成APIは非同期です。
`POST /api/generate` は即時に `job_id` を返し、フロントエンドは `GET /api/jobs/{job_id}` をポーリングします。

`video` / `video_highlight` まで `backend/.venv` だけで動かしたい場合は、追加で次を実行します。

```bash
bash scripts/setup_backend_full.sh
```

ローカルで `../auto_lecture/.venv` が残っていて、そこに `moviepy` / `detectron2` などが入っている場合、
`bash scripts/dev_backend.sh` は自動的にそちらを優先して使います。

### frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

### backend

```bash
cd backend
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements_min.txt
export OPENAI_API_KEY=...
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

必要に応じて `requirements.txt` を使ってください。研究用の重い依存も含まれます。
動画系を `backend/.venv` にそろえる場合は `requirements_visual_extra.txt` も使います。

API キーはファイルではなく `OPENAI_API_KEY` 環境変数で渡してください。
「私に読ませたくない秘密情報」は、このワークスペース内に置かず、MCP サーバやローカルシェルの環境変数として設定するのが安全です。

プロジェクト保存やユーザ別の編集ログ保存の正本は backend 側に置きます。
データベースそのものは backend の外側にあるストレージですが、
接続設定・テーブル定義・保存 API は `backend/app/` のコードで管理します。
現在の開発環境では `backend/data/kenkyu_app.db` の SQLite を使い、
実運用では `DATABASE_URL` を使って PostgreSQL に切り替える前提で進めます。
本番 DB はコードだけでは自動で生えず、研究室サーバやクラウド側で PostgreSQL を別途用意して、
その接続先を `DATABASE_URL` で backend に渡します。テーブル作成と利用開始は backend が担当します。

ローカルデバッグ用のフォールバックとして、`~/.config/kenkyu/openai_api_key`、
`~/.config/kenkyu/openai_api_key.txt`、`~/.config/kenkyu/apikey.txt` も参照します。
このディレクトリはリポジトリ外なので、秘密情報を手元で分離できます。

### いまのローカルURL

- backend: `http://127.0.0.1:8000`
- frontend: 通常 `http://localhost:5173`

`http://127.0.0.1:8000/api/health` の `capabilities.video_ready` が `true` なら、
動画系の依存までそろっています。

`http://127.0.0.1:8000/api/health` が通っていても、生成処理自体はバックグラウンド worker で進みます。

### 管理画面

フロント右上の `Studio / Admin` 切り替えで、管理ダッシュボードを開けます。
利用状況は `GET /api/admin/overview` を使って表示しており、次を確認できます。

- generate ジョブ数、成功・失敗、キャッシュヒット
- export 利用状況
- 研究セッションの編集傾向、操作種別、日別利用推移

### 認証

- 保存済みプロジェクトはユーザ名 + パスワードでログインして利用します
- 最初に作成されたアカウントは管理者として作成されます
- 管理者だけが `GET /api/admin/overview` や `PATCH /api/admin/review-settings` を利用できます

### Python バージョン注意

`backend` は `Python 3.10` か `3.11` を使ってください。
`Python 3.14` で仮想環境を作ると、`scipy` がソースビルドになって失敗しやすいです。

## 運用方針

- ブラウザのフロントは MCP プロトコルを直接話さず、HTTP API を呼びます
- 研究室の MCP サーバに置く場合も、同じマシン上で HTTP バックエンドを起動する形を推奨します
- 日々の作業は「手元で編集 -> GitHub に push -> サーバで pull」が基本で問題ありません

詳しくは `docs/` を参照してください。
