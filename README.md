# lecture_craft

講義メディア生成システムの monorepo です。  
React + Vite のフロントエンドと、FastAPI + `auto_lecture` ベースのバックエンドを同じリポジトリで管理します。

この README は、最終的に `main` に統合される前提の標準構成として書いています。  
まだ `main` に統合されていない期間は、必要に応じて対応する作業ブランチを checkout して利用してください。

## このリポジトリで管理するもの

- `frontend/`: 講義生成・編集 UI、管理画面、認証画面
- `backend/`: API、認証、保存、ジョブ管理、生成・export 処理
- `docs/`: API 契約、デプロイ・運用メモ
- `scripts/`: ローカル開発用のセットアップ・起動補助

## まず見る場所

- [README.md](README.md): monorepo 全体の入口
- [frontend/README.md](frontend/README.md): フロントエンド補足
- [backend/README.md](backend/README.md): バックエンド補足
- [docs/api-contract.md](docs/api-contract.md): フロントとバックエンドの API 契約
- [docs/mcp-server-deploy.md](docs/mcp-server-deploy.md): MCP サーバ配置時のメモ

## フォルダ構造

代表的なファイルだけを抜粋して書いています。

```text
lecture_craft/
├── frontend/
│   ├── public/
│   │   └── favicon.svg                 # ブラウザ用アイコン
│   ├── src/
│   │   ├── components/
│   │   │   ├── AdminDashboard.jsx      # 管理ダッシュボード
│   │   │   ├── AuthScreen.jsx          # ログイン / ゲスト導線
│   │   │   ├── ProjectHome.jsx         # プロジェクト一覧・新規作成画面
│   │   │   ├── LeftPanel.jsx           # アップロード・生成設定
│   │   │   ├── CenterPanel.jsx         # スライドプレビュー・再生バー
│   │   │   ├── RightPanel.jsx          # 台本・ハイライト編集
│   │   │   ├── SlideCanvas.jsx         # スライドプレビュー＋描画
│   │   │   ├── SentenceCard.jsx        # 台本1文カード
│   │   │   ├── HlEditor.jsx            # HL設定パネル
│   │   │   ├── ExportPanel.jsx         # 書き出しパネル
│   │   │   ├── AiPanel.jsx             # AI修正パネル
│   │   │   ├── AudioView.jsx           # 音声モード専用ビュー
│   │   │   └── ...                     # そのほかのUI部品
│   │   ├── hooks/
│   │   │   ├── useConfirm.js           # カスタム確認ダイアログフック
│   │   │   ├── usePlayback.js          # 再生タイマー
│   │   │   ├── useResizableLayout.js   # パネル幅リサイズ
│   │   │   └── useToast.js             # トースト通知フック
│   │   ├── store/
│   │   │   └── reducer.js              # アプリ全状態のReducer
│   │   └── utils/
│   │       ├── constants.js            # 定数・API URL
│   │       ├── projectStore.js         # プロジェクト保存
│   │       ├── sessionStore.js         # セッション保存
│   │       ├── research.js             # 研究ログ補助
│   │       └── ...                     # 描画・補助ユーティリティ
│   │   ├── App.jsx                     # アプリ全体
│   │   ├── index.css                   # 全体スタイル
│   │   └── main.jsx                    # エントリポイント
│   ├── .env.example                    # フロント用環境変数例
│   ├── README.md                       # フロント補足
│   ├── index.html                      # HTML エントリ
│   ├── package.json                    # npm scripts / 依存
│   ├── vercel.json                     # Vercel 設定
│   └── vite.config.js                  # Vite 設定
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI エントリポイント
│   │   ├── models.py                   # API 入出力モデル
│   │   ├── db.py                       # DB 接続と初期化
│   │   ├── persistence.py              # ユーザ・プロジェクト保存
│   │   ├── jobs.py                     # 非同期生成ジョブ管理
│   │   ├── service.py                  # generate / export 本体
│   │   ├── admin.py                    # 管理ダッシュボード集計
│   │   └── cache.py                    # 生成キャッシュ補助
│   ├── src/
│   │   └── auto_lecture/               # 講義生成パイプライン本体
│   ├── scripts/
│   │   ├── run_all.py                  # 動画系一括生成
│   │   ├── run_audio_only_lecture.py   # 音声のみ生成
│   │   ├── run_lp.py                   # LayoutParser 実行
│   │   └── ...                         # 実験用スクリプト
│   ├── README.md                       # バックエンド補足
│   ├── requirements_min.txt            # API 最小依存
│   ├── requirements_visual_extra.txt   # 動画系追加依存
│   ├── requirements.txt                # 研究用込みの重い依存
│   └── tree_*.txt                      # 出力構造の参考
├── docs/
│   ├── api-contract.md                 # API 契約
│   └── mcp-server-deploy.md            # MCP サーバ配置メモ
├── scripts/
│   ├── setup_backend.sh                # backend 最小セットアップ
│   ├── setup_backend_full.sh           # backend 動画系追加セットアップ
│   ├── dev_backend.sh                  # backend 起動
│   ├── dev_frontend.sh                 # frontend 起動
│   └── check_backend.sh                # backend health check
├── .gitignore                          # 生成物・秘密情報の除外
├── Makefile                            # よく使うコマンドのショートカット
└── README.md                           # monorepo 全体の入口
```

## クローン後のセットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/shohei-miyoshi/lecture_craft.git
cd lecture_craft
```

### 2. monorepo 構成のブランチへ切り替える

将来的にはこの構成が `main` に統合される前提ですが、まだ統合前の期間は対応ブランチへ切り替えてください。

```bash
git fetch origin
git switch feature/monorepo-backend-integration
```

統合後はこの手順は不要になります。

### 3. 前提を確認する

- `git`
- `Node.js 18 以上` と `npm`
- `Python 3.10` または `3.11`
- `ffmpeg`
- 生成確認をする場合は `OPENAI_API_KEY`

確認例:

```bash
node -v
npm -v
python3.10 --version || python3.11 --version || python3 --version
ffmpeg -version
```

## 最短セットアップ

backend を先に起動し、その後 frontend を起動します。  
ターミナルを 2 つ使うのが分かりやすいです。

### ターミナル 1: backend

```bash
# 以前の失敗で backend/.venv が不正な Python で作られている場合だけ削除
rm -rf backend/.venv

# 最小構成のセットアップ
bash scripts/setup_backend.sh

# OpenAI を使う場合
export OPENAI_API_KEY=YOUR_OPENAI_API_KEY

# backend 起動
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
- frontend: `http://localhost:5173`

## backend セットアップ詳細

### `scripts/setup_backend.sh` がやること

1. `python3.10` を優先して探す
2. なければ `python3.11`、それもなければ `python3` を使う
3. `backend/.venv` を作る
4. `backend/requirements_min.txt` をインストールする

### 動画系依存まで入れる場合

```bash
bash scripts/setup_backend_full.sh
```

このスクリプトは `backend/requirements_visual_extra.txt` を追加で入れます。  
`video` / `video_highlight` まで `backend/.venv` だけで完結して試したいときに使います。

### 既存の `../auto_lecture/.venv` を使う場合

`scripts/dev_backend.sh` は、`backend/.venv` に動画系依存が無いときでも、
`../auto_lecture/.venv` に `moviepy` / `detectron2` / `imageio_ffmpeg` がそろっていれば、
そちらを優先して起動します。

### API キーの渡し方

推奨:

```bash
export OPENAI_API_KEY=YOUR_OPENAI_API_KEY
```

ローカルファイルで持つ場合:

```bash
mkdir -p ~/.config/lecture_craft
printf '%s\n' 'YOUR_OPENAI_API_KEY' > ~/.config/lecture_craft/apikey.txt
```

backend は次の順でキーを見に行く前提です。

- `OPENAI_API_KEY`
- `~/.config/lecture_craft/openai_api_key`
- `~/.config/lecture_craft/openai_api_key.txt`
- `~/.config/lecture_craft/apikey.txt`
- 互換用の `~/.config/kenkyu/...`

### DB の扱い

- 開発時の既定値: `sqlite:///backend/data/lecture_craft_app.db`
- 実装場所: `backend/app/db.py`
- 本番想定: `DATABASE_URL` を設定して PostgreSQL に切り替え

起動時に `backend/app/db.py` が DB を初期化し、必要なテーブルを作成します。

### backend で主に増えるもの

- `backend/.venv/`
- `backend/data/lecture_craft_app.db`
- `backend/outputs/...`
- `backend/teachingmaterial/pdf/...`
- `backend/teachingmaterial/img/...`

## frontend セットアップ詳細

frontend は `frontend/` 以下の Vite アプリです。

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

`frontend/.env.example`:

```bash
VITE_API_URL=http://localhost:8000
```

この値は `frontend/src/utils/constants.js` で読み込まれ、未設定時の既定値も `http://localhost:8000` です。

### frontend で主に増えるもの

- `frontend/node_modules/`
- `frontend/.env`
- `frontend/dist/` (`npm run build` 実行後)

### frontend の主要ファイル

- `frontend/src/App.jsx`: 画面全体の組み立て
- `frontend/src/main.jsx`: React のエントリポイント
- `frontend/src/index.css`: 全体スタイル
- `frontend/src/store/reducer.js`: 主要 state
- `frontend/src/utils/projectStore.js`: プロジェクト保存
- `frontend/src/utils/sessionStore.js`: セッション保存
- `frontend/src/utils/research.js`: 研究ログ関係
- `frontend/src/components/ProjectHome.jsx`: プロジェクトホーム
- `frontend/src/components/AdminDashboard.jsx`: 管理画面
- `frontend/src/components/AuthScreen.jsx`: 認証画面
- `frontend/src/components/LeftPanel.jsx`: 入力・生成導線
- `frontend/src/components/CenterPanel.jsx`: プレビュー中心
- `frontend/src/components/RightPanel.jsx`: 編集導線

## Makefile での起動

```bash
make backend-setup
make backend
make frontend
make check-backend
```

## API の見取り図

主な API は `backend/app/main.py` にあります。

- `GET /api/health`: 起動確認
- `POST /api/auth/register`: ユーザ登録
- `POST /api/auth/login`: ログイン
- `POST /api/auth/logout`: ログアウト
- `GET /api/auth/me`: セッション確認
- `POST /api/auth/guest`: ゲストセッション発行
- `POST /api/experiments/join`: 実験参加
- `GET /api/projects`: プロジェクト一覧
- `POST /api/projects`: プロジェクト作成
- `GET /api/projects/{project_id}`: プロジェクト取得
- `PATCH /api/projects/{project_id}`: プロジェクト更新
- `DELETE /api/projects/{project_id}`: プロジェクト削除
- `POST /api/projects/{project_id}/events`: 操作ログ保存
- `POST /api/projects/{project_id}/layout-review`: レイアウトレビュー保存
- `POST /api/projects/{project_id}/script-review`: 台本レビュー保存
- `GET /api/projects/{project_id}/review-state`: レビュー状態取得
- `POST /api/generate`: 非同期講義生成開始
- `GET /api/jobs/{job_id}`: 生成ジョブ進捗取得
- `POST /api/jobs/{job_id}/cancel`: 生成ジョブ停止
- `GET /api/admin/overview`: 管理ダッシュボード集計
- `GET /api/admin/review-settings`: レビュー設定取得
- `PATCH /api/admin/review-settings`: レビュー設定更新
- `POST /api/research/session`: 研究セッション保存
- `POST /api/export`: mp3 / mp4 export

`POST /api/generate` は即時に `job_id` を返し、実処理はバックグラウンドで進みます。  
frontend は `GET /api/jobs/{job_id}` をポーリングして進捗を追います。

## 動作確認

### backend だけ確認する

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

### frontend を開いて確認する

- `http://localhost:5173` が開く
- ログインまたはゲスト利用の導線が見える
- `Studio / Admin` 切り替えが見える
- project home から新規作成や既存プロジェクト選択ができる

## 管理画面と認証

- 保存済みプロジェクトは backend 側でユーザ単位に保存されます
- 最初に登録されたアカウントは管理者になります
- 管理者は `GET /api/admin/overview` と `PATCH /api/admin/review-settings` を利用できます
- frontend では `Studio / Admin` 切り替えで管理画面に入れます

## 詰まりやすい点

- `backend/.venv` が Python 3.14 などで作られていて壊れている  
  `rm -rf backend/.venv` の後に `bash scripts/setup_backend.sh` をやり直してください。
- `bash scripts/dev_backend.sh` が動画依存不足を表示する  
  `bash scripts/setup_backend_full.sh` を実行するか、既存の `../auto_lecture/.venv` を使ってください。
- `OPENAI_API_KEY` が無い  
  health check は通っても生成時に失敗します。
- frontend から backend に接続できない  
  `frontend/.env` の `VITE_API_URL` と backend の URL を確認してください。
- `npm run lint` に失敗する  
  `frontend/package.json` に script はありますが、依存導入状況は別途確認してください。まずは `npm run dev` と `npm run build` を優先してください。

## 関連ドキュメント

- [frontend/README.md](frontend/README.md)
- [backend/README.md](backend/README.md)
- [docs/api-contract.md](docs/api-contract.md)
- [docs/mcp-server-deploy.md](docs/mcp-server-deploy.md)
