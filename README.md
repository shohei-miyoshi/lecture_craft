# LectureCraft

学習者要求に基づく講義スライド起点の講義メディア生成・編集システムのフロントエンドです。
九州大学卒業論文「学習者要求に基づく講義スライド起点の講義メディア生成の設計と評価」（三好祥平）の実験用Webアプリとして開発されました。

---

## 機能概要

- **PDFスライドのアップロード**（ドラッグ＆ドロップ対応）
- **3軸の学習者要求設定**：詳細度（要約的/標準的/精緻）・難易度（入門/基礎/発展）・提示形態（音声/動画/HL動画）
- **バックエンドAPIと連携**して講義台本・ハイライト情報を生成
- **台本編集**：テキスト直接編集 + Claude APIによるAI修正
- **ハイライト編集**：プレビュー上でドラッグ描画・移動・8方向リサイズ
- **書き出し**：JSON / テキスト（フロントのみ）、動画 / 音声（バックエンド連携）

---

## ディレクトリ構成

```
lecturecraft/
├── public/
│   └── favicon.svg
├── src/
│   ├── components/
│   │   ├── AiPanel.jsx        # AI修正パネル
│   │   ├── CenterPanel.jsx    # スライドプレビュー・再生バー
│   │   ├── ExportPanel.jsx    # 書き出しパネル
│   │   ├── HlBox.jsx          # スライド上のHLボックス（移動・リサイズ）
│   │   ├── HlEditor.jsx       # HL設定パネル（種別・座標・描画）
│   │   ├── HlSummaryBar.jsx   # HLサマリーバー（台本カード下部）
│   │   ├── LeftPanel.jsx      # アップロード・軸設定・スライド一覧
│   │   ├── MiniSlide.jsx      # ミニスライドサムネイル（HL位置調整）
│   │   ├── RightPanel.jsx     # 台本＋HL統合編集パネル
│   │   ├── Seg.jsx            # セグメントコントロール
│   │   ├── SentenceCard.jsx   # 台本1文カード
│   │   └── ToastLayer.jsx     # トースト通知
│   ├── hooks/
│   │   ├── usePlayback.js     # 再生タイマーフック
│   │   └── useToast.js        # トースト通知フック
│   ├── store/
│   │   └── reducer.js         # アプリ全状態のReducer
│   ├── utils/
│   │   ├── constants.js       # 定数・API URL
│   │   └── helpers.js         # ユーティリティ関数・デモデータ
│   ├── App.jsx                # ルートコンポーネント
│   ├── index.css              # グローバルCSS（CSS変数定義）
│   └── main.jsx               # ReactDOMエントリポイント
├── .env.example
├── .gitignore
├── index.html
├── package.json
├── vercel.json
└── vite.config.js
```

---

## セットアップ

### 必要なもの

- Node.js 18 以上
- npm 9 以上

### インストール・起動

```bash
# 1. リポジトリをクローン
git clone https://github.com/your-username/lecturecraft.git
cd lecturecraft

# 2. 依存パッケージをインストール
npm install

# 3. 環境変数を設定
cp .env.example .env
# .env を編集して VITE_API_URL にバックエンドのURLを設定

# 4. 開発サーバ起動
npm run dev
# → http://localhost:5173 で起動
```

バックエンドが未接続の場合でも、デモデータ（パターン認識講義・5スライド・10文・5HL）で動作確認できます。

---

## バックエンドAPI仕様

フロントエンドは `VITE_API_URL` で指定したバックエンドサーバと通信します。

### POST `/api/generate`

PDFスライドから台本・ハイライトを生成します。

**リクエスト**
```json
{
  "pdf_base64":  "...",
  "filename":    "lecture.pdf",
  "detail":      "standard",
  "difficulty":  "basic",
  "mode":        "hl"
}
```

| フィールド   | 値                                    |
|-------------|---------------------------------------|
| `detail`    | `"summary"` / `"standard"` / `"detail"` |
| `difficulty`| `"intro"` / `"basic"` / `"advanced"`    |
| `mode`      | `"audio"` / `"video"` / `"hl"`          |

**レスポンス**
```json
{
  "slides": [
    { "id": "sl0", "title": "スライドタイトル", "color": "#1a2340", "image_base64": null }
  ],
  "sentences": [
    { "id": "s1", "slide_idx": 0, "text": "...", "start_sec": 0, "end_sec": 5 }
  ],
  "highlights": [
    { "id": "h1", "sid": "s2", "slide_idx": 0, "kind": "marker", "x": 15, "y": 28, "w": 65, "h": 42 }
  ],
  "total_duration": 65
}
```

### POST `/api/export`

動画・音声ファイルを生成します。

**リクエスト**
```json
{
  "type":       "video_highlight",
  "sentences":  [...],
  "highlights": [...]
}
```

| `type` 値          | 説明                  |
|--------------------|-----------------------|
| `"video_highlight"`| ハイライト付き動画 .mp4 |
| `"video"`          | 通常動画 .mp4          |
| `"audio"`          | 音声のみ .mp3          |

**レスポンス**: バイナリファイル（mp4 / mp3）

---

## Vercel へのデプロイ

### 1. GitHubにプッシュ

```bash
git add .
git commit -m "initial commit"
git push origin main
```

### 2. Vercel でインポート

1. [vercel.com](https://vercel.com) にアクセス → **Add New Project**
2. GitHubリポジトリを選択
3. **Framework Preset**: `Vite` を選択
4. **Environment Variables** に以下を追加：

| 変数名          | 値                                      |
|----------------|-----------------------------------------|
| `VITE_API_URL` | `https://your-backend.example.com`      |

5. **Deploy** をクリック

バックエンドを別途デプロイした場合（Render / Railway / VPS など）、そのURLを `VITE_API_URL` に設定してください。

---

## キーボードショートカット

| キー            | 動作                     |
|----------------|--------------------------|
| `Space`         | 再生 / 停止              |
| `←` / `→`      | 前 / 次のスライドに移動  |
| `Esc`           | 描画モードをキャンセル   |
| `Delete` / `⌫` | 選択中のHLを削除         |

---

## 技術スタック

| 項目           | 内容                          |
|---------------|-------------------------------|
| フレームワーク | React 18                      |
| ビルドツール   | Vite 5                        |
| 状態管理       | `useReducer`（外部ライブラリなし） |
| スタイリング   | CSS変数（ライブラリなし）     |
| デプロイ       | Vercel                        |

---

## ライセンス

研究用途での利用を想定しています。
