# lecture_craft

`feature/monorepo-backend-integration` ブランチ向けの monorepo README です。  
React + Vite の研究フロントエンドと、FastAPI + `auto_lecture` ベースのバックエンドを同じリポジトリで管理します。

## このブランチで何が変わるか

- `frontend/` に UI アプリを集約
- `backend/` に API、保存、ジョブ管理、講義生成パイプラインを集約
- `docs/` に API 契約と運用メモを配置
- ルート `scripts/` から backend / frontend の起動をまとめて呼び出せるように整理

`main` はこの構成より古く、最新の開発状態はこの feature ブランチ側にあります。

## まず見る場所

- [README.md](README.md): monorepo 全体の入口
- [frontend/README.md](frontend/README.md): フロントエンドの補足説明
- [backend/README.md](backend/README.md): バックエンドの補足説明
- [docs/api-contract.md](docs/api-contract.md): フロントとバックの API 契約
- [docs/mcp-server-deploy.md](docs/mcp-server-deploy.md): MCP サーバへ置くときのメモ

## リポジトリ構成

```text
lecture_craft/
├── frontend/                  # React + Vite アプリ
├── backend/                   # FastAPI + lecture generation backend
├── docs/                      # API 契約と運用ドキュメント
├── scripts/                   # セットアップ・起動補助スクリプト
├── Makefile                   # よく使うコマンドのショートカット
├── .gitignore                 # 生成物・秘密情報の除外
└── README.md                  # このファイル
```

## クローン直後の最初の手順

### 1. リポジトリをクローン

```bash
git clone https://github.com/shohei-miyoshi/lecture_craft.git
cd lecture_craft
```

### 2. この feature ブランチに切り替える

default branch が `main` のままでも、最新の開発内容を触るならこのブランチへ切り替えてください。

```bash
git fetch origin
git switch feature/monorepo-backend-integration
```

### 3. 必要な前提を確認する

- `git`
- `Node.js 18 以上` と `npm`
- `Python 3.10` または `3.11`
- `ffmpeg` があると音声・動画 export の確認がしやすい
- OpenAI を使う生成確認をするなら `OPENAI_API_KEY`

確認例:

```bash
node -v
npm -v
python3.10 --version || python3.11 --version || python3 --version
ffmpeg -version
```

## 最短セットアップ

ターミナルを 2 つ使う想定です。  
backend を先に起動し、その後 frontend を起動します。

### ターミナル 1: backend

```bash
# backend/.venv が Python 3.14 などで壊れている場合だけ削除
rm -rf backend/.venv

# API 最小構成のセットアップ
bash scripts/setup_backend.sh

# OpenAI キーを使う場合はどちらかで設定
export OPENAI_API_KEY=YOUR_OPENAI_API_KEY
# または ~/.config/lecture_craft/apikey.txt に置く

# backend を起動
bash scripts/dev_backend.sh
```

### ターミナル 2: frontend

```bash
cd frontend
npm install
cp .env.example .env
bash ../scripts/dev_frontend.sh
```

### 起動確認

```bash
bash scripts/check_backend.sh
```

期待する URL:

- backend: `http://127.0.0.1:8000`
- frontend: 通常 `http://localhost:5173`

## セットアップを詳しく

### backend セットアップの流れ

`scripts/setup_backend.sh` は次を行います。

1. `python3.10` があれば優先して使う
2. なければ `python3.11`、それもなければ `python3` を使う
3. `backend/.venv` を作成する
4. `backend/requirements_min.txt` をインストールする

最小構成で入るもの:

- FastAPI / uvicorn
- DB 接続に必要な最小依存
- API と音声系の基本機能に必要なライブラリ

#### 動画系まで backend/.venv でそろえる場合

```bash
bash scripts/setup_backend_full.sh
```

このスクリプトは `backend/requirements_visual_extra.txt` を追加で入れます。  
`video` / `video_highlight` を backend 側だけで完結して試したいときに使います。

#### 既存の `../auto_lecture/.venv` を使う場合

`scripts/dev_backend.sh` は、`backend/.venv` に動画系依存が無くても、
隣にある `../auto_lecture/.venv` に `moviepy` / `detectron2` / `imageio_ffmpeg` がそろっていれば、
そちらを優先して起動します。

#### API キーの渡し方

推奨:

```bash
export OPENAI_API_KEY=YOUR_OPENAI_API_KEY
```

ローカルフォールバック:

```bash
mkdir -p ~/.config/lecture_craft
printf '%s\n' 'YOUR_OPENAI_API_KEY' > ~/.config/lecture_craft/apikey.txt
```

backend 側は次の順でキーを見に行く前提です。

- `OPENAI_API_KEY`
- `~/.config/lecture_craft/openai_api_key`
- `~/.config/lecture_craft/openai_api_key.txt`
- `~/.config/lecture_craft/apikey.txt`
- 互換用の `~/.config/kenkyu/...`

秘密情報はリポジトリ内に置かず、環境変数かホームディレクトリ配下の設定ファイルで管理してください。

#### DB の扱い

- 開発時の既定値: `sqlite:///backend/data/lecture_craft_app.db`
- 実装場所: `backend/app/db.py`
- 本番想定: `DATABASE_URL` を設定して PostgreSQL に切り替え

`backend/app/db.py` は起動時に DB を初期化し、テーブルを必要に応じて作成します。

### frontend セットアップの流れ

frontend は `frontend/` 以下の Vite アプリです。

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

`frontend/.env.example` の中身:

```bash
VITE_API_URL=http://localhost:8000
```

この値は `frontend/src/utils/constants.js` で読み込まれ、未設定なら `http://localhost:8000` が使われます。

#### frontend でよく触るファイル

- `frontend/package.json`: npm scripts と依存関係
- `frontend/vite.config.js`: 開発サーバ設定
- `frontend/src/App.jsx`: 画面全体の組み立て
- `frontend/src/store/reducer.js`: 主要 state の一元管理
- `frontend/src/utils/constants.js`: API URL と UI 定数
- `frontend/src/utils/projectStore.js`: プロジェクト保存まわり
- `frontend/src/utils/sessionStore.js`: セッション保存まわり
- `frontend/src/components/ProjectHome.jsx`: プロジェクトホーム画面
- `frontend/src/components/AdminDashboard.jsx`: 管理ダッシュボード
- `frontend/src/components/AuthScreen.jsx`: ログイン画面

### Makefile での起動

同じことを Makefile 経由でも実行できます。

```bash
make backend-setup
make backend
make frontend
make check-backend
```

## セットアップ後に増えるファイル

`.gitignore` で無視している主な生成物は次のとおりです。

- `frontend/node_modules/`
- `frontend/dist/`
- `frontend/.env`
- `backend/.venv/`
- `backend/data/`
- `backend/outputs/`
- `backend/teachingmaterial/img/`
- `backend/teachingmaterial/pdf/`
- `backend/models/`
- `backend/weights/`
- `backend/checkpoints/`

つまり、セットアップ直後に主に増えるのは次です。

- `frontend/node_modules/`
- `frontend/.env`
- `backend/.venv/`
- `backend/data/lecture_craft_app.db`

生成や export を回すと、さらに次が増えます。

- `backend/outputs/...`
- `backend/teachingmaterial/pdf/...`
- `backend/teachingmaterial/img/...`

## 主要ファイルの役割

### ルート

- `README.md`: monorepo 全体の入口
- `.gitignore`: 開発生成物や秘密情報の除外
- `Makefile`: backend / frontend 起動ショートカット
- `scripts/setup_backend.sh`: backend 最小セットアップ
- `scripts/setup_backend_full.sh`: 動画系依存の追加セットアップ
- `scripts/dev_backend.sh`: backend 起動
- `scripts/dev_frontend.sh`: frontend 起動
- `scripts/check_backend.sh`: health check

### `docs/`

- `docs/api-contract.md`: frontend と backend 間の API 取り決め
- `docs/mcp-server-deploy.md`: MCP サーバ配置時の手順

### `frontend/`

```text
frontend/
├── .env.example
├── package.json
├── package-lock.json
├── vite.config.js
├── public/
│   └── favicon.svg
└── src/
    ├── components/
    ├── hooks/
    ├── store/
    └── utils/
```

主な責務:

- `components/`: 画面部品
- `hooks/`: UI 状態の補助ロジック
- `store/`: reducer ベースの状態管理
- `utils/`: API URL、保存、研究ログ、ハイライト補助

### `backend/`

```text
backend/
├── app/                       # FastAPI アプリ本体
├── src/auto_lecture/          # 講義生成パイプライン
├── scripts/                   # 実験・生成系の CLI スクリプト
├── requirements_min.txt       # API 最小依存
├── requirements_visual_extra.txt
├── requirements.txt           # 研究用込みの重い依存
└── README.md
```

主な責務:

- `backend/app/main.py`: API エントリポイント
- `backend/app/db.py`: SQLite / PostgreSQL 接続と初期化
- `backend/app/persistence.py`: ユーザ、セッション、プロジェクト保存
- `backend/app/jobs.py`: 非同期 generate job 管理
- `backend/app/service.py`: generate / export の本体ロジック
- `backend/app/admin.py`: 管理ダッシュボード用集計
- `backend/src/auto_lecture/`: 既存講義生成コード群

## API の見取り図

backend の主な API は `backend/app/main.py` にあります。

- `GET /api/health`: 起動確認と capability 確認
- `POST /api/auth/register`: ユーザ登録
- `POST /api/auth/login`: ログイン
- `POST /api/auth/logout`: ログアウト
- `GET /api/auth/me`: 現在のセッション確認
- `POST /api/auth/guest`: ゲストセッション作成
- `GET /api/projects`: 保存プロジェクト一覧
- `POST /api/projects`: プロジェクト保存
- `PATCH /api/projects/{project_id}`: プロジェクト更新
- `POST /api/generate`: 非同期講義生成開始
- `GET /api/jobs/{job_id}`: 生成ジョブ進捗確認
- `POST /api/jobs/{job_id}/cancel`: 生成キャンセル
- `POST /api/export`: mp3 / mp4 の export
- `GET /api/admin/overview`: 管理ダッシュボード集計

`POST /api/generate` は即時に `job_id` を返し、実際の処理はバックグラウンドで進みます。  
フロントエンドは `GET /api/jobs/{job_id}` をポーリングして進捗を追います。

## 動作確認のポイント

### backend だけ先に確認する

```bash
bash scripts/check_backend.sh
```

または:

```bash
curl -fsS http://127.0.0.1:8000/api/health
```

見たいポイント:

- `ok: true`
- `service: lecture-craft-backend-api`
- `capabilities.audio_ready`
- `capabilities.video_ready`

`capabilities.video_ready` が `false` でも、音声中心の API 確認自体は可能です。

### frontend を開いて確認する

- `http://localhost:5173` が開く
- `Studio / Admin` の切り替えが見える
- ログインやゲスト利用の導線が出る
- project home から新規作成や既存プロジェクト選択ができる

## 管理画面と認証

- 保存済みプロジェクトはユーザ単位で backend 側に保存されます
- 最初に登録されたアカウントは管理者になります
- 管理者は `GET /api/admin/overview` と `PATCH /api/admin/review-settings` を利用できます
- frontend では `Studio / Admin` 切り替えで管理ダッシュボードへ入れます

## セットアップで詰まりやすい点

- `backend/.venv` が Python 3.14 で作られていて壊れている  
  `rm -rf backend/.venv` の後に `bash scripts/setup_backend.sh` をやり直してください。
- `bash scripts/dev_backend.sh` が動画依存不足を表示する  
  `bash scripts/setup_backend_full.sh` を実行するか、既存の `../auto_lecture/.venv` を使ってください。
- `OPENAI_API_KEY` を設定していない  
  health check は通っても生成時に失敗します。環境変数か `~/.config/lecture_craft/apikey.txt` を設定してください。
- frontend から backend に接続できない  
  `frontend/.env` の `VITE_API_URL` と backend の起動 URL が一致しているか確認してください。
- `npm run lint` に失敗する  
  `frontend/package.json` には `lint` script がありますが、このブランチでは eslint の導入状態を別途確認してください。まずは `npm run dev` と `npm run build` を優先してください。

## 運用メモ

- ブラウザの frontend は MCP を直接話さず、backend の HTTP API を呼びます
- MCP サーバ上へ置く場合も、同じマシンで backend を起動する形が基本です
- 日々の作業は「手元で編集 -> GitHub に push -> サーバで pull」で進められます

詳しくは [frontend/README.md](frontend/README.md)、[backend/README.md](backend/README.md)、[docs/](docs/) を参照してください。
