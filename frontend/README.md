# LectureCraft

学習者要求に基づく講義スライド起点の講義メディア生成・編集システムのフロントエンドです。  
九州大学卒業論文「学習者要求に基づく講義スライド起点の講義メディア生成の設計と評価」（三好祥平）の実験用Webアプリとして開発されました。

---

## 機能概要

- **PDFスライドのアップロード**（ドラッグ＆ドロップ対応）
- **3軸の学習者要求設定**：詳細度・難易度・提示形態（音声 / 動画 / HL動画）
- **提示形態は生成後ロック** — 学習者要求が変わると全く異なる講義が生成されるため、生成後のモード切替を制限。別モードで再生成する場合はリセットが必要
- **台本編集**：テキスト直接編集・Claude AI修正・タイミング編集（音声モード）
- **ハイライト編集**：プレビュー上でドラッグ描画・移動・8方向リサイズ
- **再生プレビュー**：rAF実時間ベース、シークバードラッグ対応、再生速度変更、自動スライド切替
- **HL再生表示**：バウンディングボックスを維持しつつ塗りつぶしのみ pulse アニメーション
- **カスタム確認ダイアログ**：ブラウザ標準 confirm() を使わないアプリ独自ダイアログ
- **JSONエクスポート / インポート**：複数の講義データを保持・切り替え可能
- **書き出し**：JSON / テキスト（フロントのみ）、動画 / 音声（バックエンド連携）

---

## 複数講義の保持・切り替え

講義スライドや学習者要求が異なる複数の講義データを保持したい場合は、**JSONエクスポート／インポート機能**を使います。

```
1. 講義Aを生成・編集する
2. 「書き出し」→「編集データ（JSON）」でエクスポートし、ファイルを保存
3. 「↺ リセット」でアプリを初期化
4. 講義Bを生成・編集する
5. 講義Aに戻りたいとき → 左パネル「📂 保存済みJSONをインポート」
```

インポートすると、生成時の提示形態（audio / video / hl）も含めて復元されます。

---

## ディレクトリ構成

```
lecturecraft/
├── public/
│   └── favicon.svg
├── src/
│   ├── components/
│   │   ├── AiPanel.jsx          # AI修正パネル
│   │   ├── AudioView.jsx        # 音声モード専用ビュー（波形・台本スクロール）
│   │   ├── CenterPanel.jsx      # スライドプレビュー・再生バー
│   │   ├── ConfirmDialog.jsx    # カスタム確認ダイアログ
│   │   ├── ExportPanel.jsx      # 書き出しパネル
│   │   ├── HlBox.jsx            # スライド上のHLボックス（移動・リサイズ・再生アニメ）
│   │   ├── HlEditor.jsx         # HL設定パネル（種別・座標・描画）
│   │   ├── HlSummaryBar.jsx     # HLサマリーバー（台本カード下部）
│   │   ├── LeftPanel.jsx        # アップロード・軸設定・スライド一覧・インポート
│   │   ├── MiniSlide.jsx        # ミニスライドサムネイル（HL位置調整）
│   │   ├── Playbar.jsx          # 再生コントロール（ドラッグシーク・残り時間・速度）
│   │   ├── RightPanel.jsx       # 台本＋HL統合編集パネル
│   │   ├── Seg.jsx              # セグメントコントロール
│   │   ├── SentenceCard.jsx     # 台本1文カード
│   │   ├── SlideCanvas.jsx      # スライドプレビュー＋描画
│   │   └── ToastLayer.jsx       # トースト通知
│   ├── hooks/
│   │   ├── useConfirm.js        # カスタム確認ダイアログフック
│   │   ├── usePlayback.js       # 再生タイマー（rAF実時間ベース）
│   │   └── useToast.js          # トースト通知フック
│   ├── store/
│   │   └── reducer.js           # アプリ全状態のReducer
│   ├── utils/
│   │   ├── constants.js         # 定数・API URL
│   │   └── helpers.js           # ユーティリティ関数・デモデータ
│   ├── App.jsx
│   ├── index.css
│   └── main.jsx
├── .env.example
├── .gitignore
├── index.html
├── package.json
├── vercel.json
└── vite.config.js
```

---

## ローカルセットアップ

```bash
# 1. リポジトリをクローン
git clone https://github.com/your-username/lecturecraft.git
cd lecturecraft

# 2. パッケージをインストール
npm install

# 3. 環境変数を設定
cp .env.example .env
# .env を開いて VITE_API_URL をバックエンドのURLに変更

# 4. 開発サーバ起動
npm run dev   # → http://localhost:5173
```

バックエンド未接続でも、デモデータ（パターン認識講義）で全機能を確認できます。

---

## GitHub + Vercel へのデプロイ

### 1. GitHubにリポジトリを作成してプッシュ

```bash
cd lecturecraft
git init
git add .
git commit -m "initial commit"

# GitHubでリポジトリを作成した後
git remote add origin https://github.com/your-username/lecturecraft.git
git branch -M main
git push -u origin main
```

### 2. Vercel にデプロイ

1. [vercel.com](https://vercel.com) にログイン（GitHubアカウントで連携）
2. **Add New Project** → GitHubリポジトリを選択
3. 以下の設定を確認：
   - **Framework Preset**: `Vite`
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
4. **Environment Variables** に追加：
   | 変数名 | 値 |
   |---|---|
   | `VITE_API_URL` | `https://your-backend.example.com` |
5. **Deploy** をクリック

### 3. 以降の更新

```bash
git add .
git commit -m "update"
git push
```

GitHubにpushするだけでVercelが自動的に再デプロイします（CI/CD）。

### 4. バックエンドのデプロイ先

Pythonバックエンドのデプロイには以下が使えます：

| サービス | 特徴 |
|---|---|
| [Render](https://render.com) | 無料プランあり、Pythonに強い |
| [Railway](https://railway.app) | セットアップが簡単 |
| [Google Cloud Run](https://cloud.run) | コンテナ対応、スケーラブル |
| 学内サーバ / VPS | 研究用途ならこれが最もシンプル |

---

## バックエンドAPI仕様

### POST `/api/generate`

| フィールド | 値 |
|---|---|
| `pdf_base64` | PDFのBase64文字列 |
| `filename` | ファイル名 |
| `detail` | `"summary"` / `"standard"` / `"detail"` |
| `difficulty` | `"intro"` / `"basic"` / `"advanced"` |
| `mode` | `"audio"` / `"video"` / `"hl"` |

レスポンス例：
```json
{
  "slides":     [{ "id": "sl0", "title": "タイトル", "color": "#1a2340", "image_base64": null }],
  "sentences":  [{ "id": "s1", "slide_idx": 0, "text": "...", "start_sec": 0, "end_sec": 5 }],
  "highlights": [{ "id": "h1", "sid": "s2", "slide_idx": 0, "kind": "marker", "x": 15, "y": 28, "w": 65, "h": 42 }],
  "total_duration": 65,
  "mode": "hl"
}
```

### POST `/api/export`

```json
{ "type": "video_highlight", "sentences": [...], "highlights": [...] }
```
レスポンス: バイナリ（mp4 / mp3）

---

## キーボードショートカット

| キー | 動作 |
|---|---|
| `Space` | 再生 / 停止 |
| `←` / `→` | 前 / 次スライド |
| `Esc` | 描画モードキャンセル |
| `Delete` / `⌫` | 選択中のHL削除 |

---

## 技術スタック

| 項目 | 内容 |
|---|---|
| フレームワーク | React 18 |
| ビルドツール | Vite 5 |
| 状態管理 | `useReducer`（外部ライブラリなし） |
| スタイリング | CSS変数（外部CSSライブラリなし） |
| デプロイ | Vercel |
