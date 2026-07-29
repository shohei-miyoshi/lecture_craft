# LectureCraft Backend

LectureCraftの認証，プロジェクト保存，生成ジョブ，研究ログ，プレビュー音声，動画書き出しを担当するFastAPIバックエンドです．

## 主な責務

- ユーザ認証，CSRF検証，所有者・管理者の認可
- プロジェクト，draft，revision，review stageの保存
- PDF，スライド画像，JSON，音声，動画のartifact管理
- LayoutParser，台本生成，対応付け，TTS，動画生成のジョブ実行
- 文単位TTSキャッシュとプレビュー音声の作成
- generation run，編集イベント，実験条件の記録
- 管理者向け集計と匿名化した研究用JSONLの出力

## 構成

```text
backend/
├── alembic/              # DB migration
├── app/
│   ├── main.py           # FastAPI entrypoint
│   ├── db.py             # DB接続
│   ├── persistence.py    # 認証・プロジェクト保存
│   ├── storage.py        # ArtifactStore
│   ├── storage_persistence.py
│   ├── jobs.py           # 非同期job
│   ├── service.py        # 生成・書き出し
│   └── admin.py          # 管理者向け集計
├── src/auto_lecture/     # 講義生成パイプライン
├── scripts/              # 生成・運用補助
└── tests/
```

## セットアップ

リポジトリルートから実行します．

```bash
bash scripts/setup_backend.sh
```

動画生成を含む依存関係が必要な場合は，追加セットアップを行います．

```bash
bash scripts/setup_backend_full.sh
```

APIを利用する場合は，秘密値をファイルへ書かず，実行環境の環境変数として設定します．

```bash
export OPENAI_API_KEY="set-in-your-shell"
```

## 起動

```bash
bash scripts/dev_backend.sh
```

標準のローカルURLは`http://127.0.0.1:8000`です．

```bash
curl http://127.0.0.1:8000/api/health
```

## DBと保存領域

- ローカル開発ではSQLiteを利用できます．
- 実運用では`DATABASE_URL`でPostgreSQLへ接続します．
- migrationはAlembicで管理します．
- PDFや生成物はDBへ直接入れず，ArtifactStore配下へ保存します．
- DBには相対storage key，hash，MIME，所有者，runとの関係を保存します．
- 保存先は`LECTURE_CRAFT_STORAGE_ROOT`で変更できます．
- 指定しない場合は，バックエンドのローカルデータ領域を利用します．

本番モードはPostgreSQL，書き込み可能なartifact領域，バックアップ先を前提とします．

## 認証

- ブラウザ認証は`HttpOnly` Cookieを利用します．
- 本番Cookieには`Secure`と`SameSite`を設定します．
- 状態変更APIはCSRFヘッダを検証します．
- project，run，job，artifactは所有者または管理者だけが参照できます．
- bootstrap管理者の情報は環境変数で渡し，ソースや`.env`へコミットしません．

## 生成フロー

1. プロジェクトを作成します．
2. PDFをmultipartでアップロードし，source artifactとして登録します．
3. generation runを作成します．
4. LayoutParser結果を先に公開し，領域確認中も台本生成を続けます．
5. 確認済み領域と確認済み台本から対応付けを作ります．
6. 台本確認後，文単位TTSを生成します．
7. 編集された文だけTTSを再生成し，未変更文はキャッシュを再利用します．
8. 固定したrevisionとartifactから最終成果物を生成します．

## テスト

開発用依存を入れる場合は，次を利用できます．

```bash
cd backend
.venv/bin/python -m pip install -r requirements_dev.txt
```

```bash
cd backend
.venv/bin/python -m pytest -q
```

公開APIの概要は[`docs/api-contract.md`](../docs/api-contract.md)，研究全体の現状は[引き継ぎ書](../docs/research-progress-design-lecturecraft.md)を参照してください．
