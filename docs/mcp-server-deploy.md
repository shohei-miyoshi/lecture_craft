# MCP Server Deployment

## 重要な整理

研究室の MCP サーバに配置するとしても、フロントエンドが直接 MCP を叩く構成にはしません。

推奨構成は次です。

```text
Browser
  -> Frontend (Vercel or static hosting)
  -> HTTP Backend on the lab server
  -> auto_lecture pipeline
```

MCP サーバは「配置先のマシン」であって、ブラウザ向け API は HTTP で出します。

## おすすめ運用

はい、基本は次の流れで大丈夫です。

1. 手元で `frontend/` と `backend/` を編集する
2. ローカルで動作確認する
3. GitHub に push する
4. 研究室サーバで `git pull` する
5. バックエンドのプロセスを再起動する

## サーバ側の配置例

```text
/opt/kenkyu/kenkyu
  ├── frontend/
  ├── backend/
  └── docs/
```

## サーバ初回セットアップ例

```bash
git clone <your-repo-url> /opt/kenkyu/kenkyu
cd /opt/kenkyu/kenkyu/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements_min.txt
export OPENAI_API_KEY=...
```

必要なら重い依存を含む `requirements.txt` を使います。

## 推奨サービス分離

- フロント
  - Vercel に置けるなら `frontend/` だけ Vercel デプロイでよい
  - その場合、サーバで pull が必要なのは主に `backend/`
- バック
  - 研究室サーバ上で `FastAPI + uvicorn` などの HTTP API として常駐
  - `systemd` 管理を推奨

## 秘密情報の持ち方

- 実運用: `OPENAI_API_KEY` をサーバ環境変数で渡す
- 手元デバッグ: `~/.config/kenkyu/openai_api_key`、
  `~/.config/kenkyu/openai_api_key.txt`、
  `~/.config/kenkyu/apikey.txt` を使ってよい
- どちらの場合も、秘密情報はリポジトリ内に置かない

## 更新運用

### もっとも簡単な形

サーバで毎回手動更新します。

```bash
cd /opt/kenkyu/kenkyu
git pull
cd backend
source .venv/bin/activate
pip install -r requirements_min.txt
sudo systemctl restart kenkyu-backend
```

### 一段よい形

- GitHub に push
- サーバ側は `main` を pull
- `systemd` で backend を再起動
- 必要なら `frontend` は Vercel が自動デプロイ

## systemd のイメージ

バックエンドは次のような常駐サービスにします。

```ini
[Unit]
Description=Kenkyu Backend API
After=network.target

[Service]
WorkingDirectory=/opt/kenkyu/kenkyu/backend
Environment="PATH=/opt/kenkyu/kenkyu/backend/.venv/bin"
Environment="OPENAI_API_KEY=YOUR_REAL_KEY"
ExecStart=/opt/kenkyu/kenkyu/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

このリポジトリでは `backend/app/main.py` に HTTP API エントリポイントを置いているので、
上の `app.main:app` のままで起動できます。

## 先に決めておくと良いこと

- GitHub の単一リポジトリで進める
- サーバで動かすのは `backend/`
- フロントは `VITE_API_URL` をサーバの公開 URL に向ける
- 秘密情報はワークスペース内ファイルではなく、サーバの環境変数で持つ
