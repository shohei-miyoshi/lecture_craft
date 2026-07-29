# LectureCraft Frontend

講義スライドPDFから生成した領域，台本，対応付け，音声，動画を段階的に確認・編集するReact + Viteフロントエンドです．

## 主な機能

- ログイン，新規登録，ユーザ単位のプロジェクト一覧
- PDFアップロードとサーバ保存
- 領域確認，台本確認，対応付け確認
- ハイライト領域の追加，移動，リサイズ，削除
- 台本文の編集，追加，削除，タイミング調整
- 音声と同期した台本・ハイライトプレビュー
- 文クリックによる該当時刻へのシーク
- 音声のみ，ハイライトなし動画，ハイライト付き動画の書き出し
- 保存状態，生成job，書き出し進捗の表示
- 管理者向け実験run・研究データ確認

## 構成

```text
frontend/
├── public/
├── scripts/
├── src/
│   ├── components/   # 編集，確認，管理UI
│   ├── hooks/        # 再生，確認，レイアウト
│   ├── store/        # reducer
│   └── utils/        # API，保存，同期，研究ログ
├── .env.example
├── package.json
└── vite.config.js
```

## セットアップ

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

標準のローカルURLは`http://localhost:5173`です．

## 環境変数

```dotenv
VITE_API_URL=http://localhost:8000
```

サブパスで配信する場合は`VITE_BASE_PATH`も設定します．

`VITE_*`はブラウザへ公開されます．APIキー，パスワード，内部専用トークンは絶対に設定しないでください．

## プレビューの考え方

- 台本確認完了時に，確認済み台本から初版の文単位TTSを作ります．
- 通常プレビューは音声をバックエンドから取得し，ハイライトをフロントのレイヤで同期表示します．
- 台本変更後は，プレビュー再生時に変更文だけを再生成します．
- 領域や対応付けだけの変更では音声を再生成しません．
- 再生時刻はaudio要素を正本とし，台本，スライド，ハイライトを同じ時刻へ同期します．
- 音声取得に失敗しても，音声なしの簡易プレビューへ切り替えて編集を継続できます．

## 保存の考え方

- プロジェクト本体はバックエンドを正本とします．
- 編集中のdraftはdebounceしてサーバへ同期します．
- `base_version`が一致しない更新は競合として扱い，無言で上書きしません．
- PDFや生成物はartifact URLから復元します．
- ブラウザの保存領域は認証情報の正本やプロジェクト本体に使いません．

## 検証

```bash
cd frontend
npm run lint
npm run build
```

APIの概要は[`docs/api-contract.md`](../docs/api-contract.md)，研究全体の現状は[引き継ぎ書](../docs/research-progress-design-lecturecraft.md)を参照してください．
