auto_lecture/
├─ src/
│  └─ auto_lecture/                         # 講義生成パイプライン本体（実験コードからは触らない）
│     ├─ __init__.py                        # パッケージ初期化
│     ├─ config.py                          # 教材ルートやデフォルト設定
│     ├─ paths.py                           # ★最重要：outputs 以下の全パス定義を一元管理
│     ├─ gpt_client.py                      # OpenAI API クライアント（生成・評価共通）
│     ├─ pdf_to_img.py                      # PDF → スライド画像変換
│     ├─ deck_scan.py                       # スライド枚数・ページ構成の取得
│     ├─ lecture_script.py                  # スライド画像 → 講義台本生成
│     ├─ animation_assignment.py             # 台本文ごとのアニメーション割当
│     ├─ add_animation_runner_from_mapping.py# アニメ割当JSONに基づき動画生成
│     ├─ add_animation_laser_circle.py       # レーザー円アニメーション
│     ├─ add_animation_arrow_point.py        # 矢印指示アニメーション
│     ├─ add_animation_marker_highlight.py   # マーカーハイライト
│     ├─ lecture_concat.py                  # 動画・音声の最終連結処理
│     ├─ tts_generation.py                  # TTS生成（章・文単位）
│     ├─ tts_simple.py                      # 簡易TTS（音声のみ用）
│     ├─ audio_only_lecture.py               # 音声のみ講義生成パイプライン
│     ├─ audio_only_style_axes.py            # 音声のみ用レベル・詳細度軸
│     └─ utils/
│        └─ pdf_utils.py                    # PDF処理ユーティリティ
│
├─ scripts/                                 # 既存のCLI実行スクリプト（生成専用）
│  ├─ run_all.py                            # アニメーション付き講義の一括生成
│  ├─ run_audio_only_lecture.py             # 音声のみ講義生成
│  ├─ run_audio_only_direct_gpt4o.py        # GPT-4o直接利用版（検証用）
│  └─ run_allLD_audio_only_lecture.py       # 詳細度×音声のみ統合実行
│
├─ teachingmaterial/                        # 入力教材
│  ├─ pdf/                                 # 元PDF教材
│  │  └─ *.pdf
│  └─ img/                                 # PDFから生成されたスライド画像
│     └─ <pdf_name>/                       # PDFごとに分かれる
│        └─ *.png
│
├─ outputs/                                 # ★生成結果（paths.py 管理、実験コードは読取専用）
│  └─ <run_name>/                          # 1回の生成単位
│     ├─ lecture_outputs/
│     │  ├─ lecture_texts/                 # 生成された講義台本（txt）
│     │  │  └─ *.txt
│     │  ├─ region_id_based_animation_outputs/
│     │  │  └─ *.json                      # 文ごとのアニメーション割当情報
│     │  ├─ tts_outputs/
│     │  │  └─ *.wav / *.mp3               # TTS音声ファイル
│     │  ├─ add_animation_outputs/
│     │  │  └─ *.mp4                       # 文単位のアニメ付き動画
│     │  └─ output_final/
│     │     └─ lecture_final.mp4           # 最終講義動画
│     └─ LP_output/
│        └─ <pdf_name>/                    # LayoutParser 出力
│           ├─ layout.json
│           └─ layout_vis.png
│
├─ experiments/                             # ★実験・評価専用（生成本体とは分離）
│  ├─ config/
│  │  └─ experiment_config.json             # 実験条件（9スライド×8条件・比較ペア等）
│  │
│  ├─ scripts/                              # 実験用CLIスクリプト
│  │  ├─ run_pipeline.py                    # ★生成→抽出→評価を全自動で回すマスター
│  │  ├─ 01_generate.py                    # 実験条件に基づく一括生成
│  │  ├─ 03_extract.py                     # outputs から評価用CSVを抽出
│  │  ├─ 04_metrics_basic.py               # 文字数・文数など機械的指標
│  │  ├─ 05_metrics_gpt_counts.py           # GPT-5による専門語密度などの計測
│  │  ├─ run_judge_pairwise.py               # AIによる「どっちが〇〇」比較
│  │  ├─ 07_pack_animation_review.py        # 人手評価用（アニメ注釈付き台本）
│  │  └─ 02_bundle_run_outputs.py           # 1実験分の生成・評価結果をまとめて固める
│  │
│  └─ runs/                                 # ★1回の生成＋評価＝1 run
│     └─ <experiment_run_id>/               # 例: exp_2025_0106_153210
│        ├─ config/                         # このrunで使った設定のコピー
│        ├─ generation/                     # outputs のスナップショット
│        ├─ extracted/                      # 評価用に正規化したCSV
│        │  ├─ slide_script.csv             # 全スライド×全条件の台本（1ファイル）
│        │  └─ animation_mapping.csv
│        ├─ analysis/                       # 自動評価結果
│        │  ├─ metrics_basic.csv
│        │  ├─ gpt_counts.jsonl
│        │  ├─ judge_votes.jsonl
│        │  └─ judge_summary.csv
│        ├─ review/                         # 人手評価用資料（HTML / md）
│        ├─ logs/                           # 実行ログ（stdout / stderr）
│        ├─ reports/                        # 実験サマリ・失敗報告
│        │  ├─ summary.json
│        │  └─ failures.txt
│        └─ DONE.txt                        # 生成〜評価が完走した印
│
├─ requirements_min.txt                     # 最小依存関係
└─ README.md                                # プロジェクト説明（←ここに貼る）

## Setup

1. Python 3.11 前後の仮想環境を作成する
2. `pip install -r requirements.txt` を実行する
3. `OPENAI_API_KEY` 環境変数を設定する
4. 必要な教材 PDF を `teachingmaterial/pdf/` に置く

最短では、リポジトリルートで次を実行します。

```bash
rm -rf backend/.venv   # 以前の失敗で Python 3.14 の venv が残っている場合だけ
bash scripts/setup_backend.sh
bash scripts/dev_backend.sh
```

`video` / `video_highlight` を `backend/.venv` で直接動かす場合は、追加で次も実行します。

```bash
bash scripts/setup_backend_full.sh
```

ローカルに `../auto_lecture/.venv` が残っていて、そこに `moviepy` / `detectron2` /
`imageio_ffmpeg` が入っている場合、`bash scripts/dev_backend.sh` はその venv を自動利用します。

例:

```bash
export OPENAI_API_KEY=...
```

秘密情報をこのワークスペース内のファイルに置かない運用を推奨します。

ローカルデバッグ時は、次のどちらかでも動作します。

```bash
mkdir -p ~/.config/kenkyu
printf '%s\n' 'YOUR_OPENAI_KEY' > ~/.config/kenkyu/openai_api_key
```

優先順位は `OPENAI_API_KEY` 環境変数が先、その次に
`~/.config/kenkyu/openai_api_key` /
`~/.config/kenkyu/openai_api_key.txt` /
`~/.config/kenkyu/apikey.txt` です。

起動確認:

```bash
curl http://127.0.0.1:8000/api/health
```

`capabilities.video_ready` が `true` なら、動画系の依存まで利用可能です。

補足:
- `backend/.venv` は `Python 3.10` または `3.11` で作ってください
- `Python 3.14` だと `scipy` がビルド失敗しやすいです
