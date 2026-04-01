# API Contract

このドキュメントは `frontend/` が期待する HTTP API 契約を固定するためのものです。

## Base URL

- 開発時: `http://localhost:8000`
- フロント設定: `frontend/.env` の `VITE_API_URL`

## 1. POST `/api/generate`

### Request

```json
{
  "pdf_base64": "JVBERi0xLjc...",
  "filename": "lecture.pdf",
  "detail": "summary",
  "difficulty": "intro",
  "mode": "audio"
}
```

### Request fields

- `pdf_base64`: PDF 本体の Base64 文字列
- `filename`: 元 PDF 名
- `detail`: `summary | standard | detail`
- `difficulty`: `intro | basic | advanced`
- `mode`: `audio | video | hl`

### Response

```json
{
  "slides": [
    {
      "id": "sl0",
      "title": "タイトル",
      "color": "#1a2340",
      "image_base64": null
    }
  ],
  "sentences": [
    {
      "id": "s1",
      "slide_idx": 0,
      "text": "説明文",
      "start_sec": 0,
      "end_sec": 5
    }
  ],
  "highlights": [
    {
      "id": "h1",
      "sid": "s1",
      "slide_idx": 0,
      "kind": "marker",
      "x": 15,
      "y": 28,
      "w": 65,
      "h": 42
    }
  ],
  "total_duration": 65,
  "mode": "hl"
}
```

### Response rules

- `slides` は配列必須
- `sentences` は配列必須
- `highlights` は未生成でも空配列を返す
- `total_duration` は秒数
- `mode` は実際に生成したモードを返す
- `slide_idx` は `slides` 配列の 0-based index
- `audio` モードでは全 `sentences[].slide_idx` を `0` にそろえてよい
- `kind` は `marker | arrow | box`
- 座標 `x y w h` はスライド上の百分率で扱う

## 2. POST `/api/export`

フロントは編集後の状態をバックエンドへ渡し、最終音声または動画を生成します。

### Request

```json
{
  "type": "video_highlight",
  "mode": "hl",
  "slides": [],
  "sentences": [],
  "highlights": [],
  "settings": {
    "detail": "standard",
    "difficulty": "basic"
  }
}
```

### Request fields

- `type`: `video_highlight | video | audio`
- `mode`: `audio | video | hl`
- `slides`: 生成時に使ったスライド情報
- `sentences`: フロントで編集済みの台本
- `highlights`: フロントで編集済みのハイライト
- `settings.detail`: `summary | standard | detail`
- `settings.difficulty`: `intro | basic | advanced`

### Response

- `type=audio` のとき `audio/mpeg`
- `type=video` または `type=video_highlight` のとき `video/mp4`

## 3. Error format

失敗時は HTTP 4xx/5xx を返し、JSON は次の形式にそろえます。

```json
{
  "error": {
    "code": "GENERATION_FAILED",
    "message": "lecture generation failed"
  }
}
```

## 4. Backend implementation notes

- バックエンド内部は CLI パイプラインのままでよく、HTTP 層が入出力を変換する
- まずは DB なしでよい
- 生成物は `backend/outputs/` に置き、必要になってから DB を入れる
- ブラウザは MCP ではなく HTTP API を使う
