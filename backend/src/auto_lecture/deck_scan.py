# src/auto_lecture/deck_scan.py
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import List

from openai import OpenAI

from .paths import ProjectPaths
from .gpt_utils import (
    build_responses_system_message,
    build_responses_user_message,
    call_responses_text,
)
from .style_axes import resolve_level_detail
from . import config


def collect_slide_images(img_root: Path) -> List[str]:
    exts = {".png", ".jpg", ".jpeg", ".webp"}
    if not img_root.exists():
        raise FileNotFoundError(f"IMG_ROOT が見つかりません: {img_root}")
    paths = sorted(
        [str(p) for p in img_root.iterdir() if p.suffix.lower() in exts]
    )
    if not paths:
        raise RuntimeError(
            f"スライド画像が見つかりません（{img_root} 内の {sorted(exts)}）"
        )
    return paths


def run_deck_scan(
    client: OpenAI,
    paths: ProjectPaths,
    level: str = "L3",
    detail: str = "D2",
) -> Path:
    """
    Cell3 + Cell4 相当:
    - スライド画像をすべて読み込み
    - GPT-5 に講義全体の構造・難所・グループを分析させる
    - deck_scan_overview.txt に保存
    戻り値: deck_scan_overview.txt のパス
    """
    img_root = paths.img_root
    all_page_scan_output_dir = Path(paths.all_page_scan_output_dir)

    # --- 1) スライド画像の取得 ---
    scan_img_paths: List[str] = collect_slide_images(img_root)
    print(f"検出されたスライド枚数（全て送信）: {len(scan_img_paths)}")

    # --- 2) LEVEL/DETAIL の説明文取得 ---
    level_desc, detail_desc = resolve_level_detail(level, detail)
    print(f"LEVEL={level} ({level_desc}) / DETAIL={detail} ({detail_desc})")

    # --- 3) Systemメッセージ & プロンプト ---
    scan_system_message = build_responses_system_message(
        f"""あなたは日本語で大学講義資料を分析する教育工学の専門家です。
講義スライド全体を俯瞰し，スライドグループ・講義の構造・流れ・重要用語・難所を整理します。
想定する説明スタイルは次の通りです：

レベル軸（Level Axis）: {level_desc}
詳細度軸（Detail Axis）: {detail_desc}
"""
    )

    scan_text = f"""
[Style Axes]
レベル軸（Level Axis）: {level_desc}
詳細度軸（Detail Axis）: {detail_desc}

[Task]
これから渡す画像は、1つの講義のスライド全ページです。
全体を眺めて、講義の構造・流れ・重要用語・難所を分析し、
さらに「同じ概念・単語を複数スライドにわたって段階的に説明している」スライドグループも抽出してください。

[Output items]

1. [全体概要]
- 講義全体のテーマ
- 想定される前提知識
- 講義の大まかな流れ（序盤・中盤・終盤）

2. [スライドグループ]
- 複数枚のスライドを「ひとかたまりとして説明した方が，聞き手にとって自然で分かりやすい」と判断できる場合，
  その連続したスライド列を 1 つのグループとして列挙してください。
- グループは必ず「スライド番号が連続した列」とします。
  - 例: [2,3] や [4,5] や [12,13,14] はOK、[2,4,5] のような飛び飛びはNG。
- 次のような場合は，「同じ概念を段階的に説明している 1 つの流れ」とみなして，同じグループにまとめてください。
  - レイアウトや文章はほぼ同じで，図や数値・次元・具体例だけが少しずつ変わっている。
- 迷ったときの方針：
  - 「少し長めでも，一続きで説明した方が自然か？」「それとも途中で区切って別の話として説明するか？」
    を教員の立場で考え，より説明しやすい方を選んでください。
  - 「大きなひとまとめにする」よりも、「少し細かめのグループに分ける」ことを優先してください。
[スライドグループの書き方]
- 各グループについて、次の形式で書いてください：
  - 「group 1: topic=ベクトルと座標系と『1データ=1点』, slides=[12,13,14,15,16,17]」
- どのグループにも属さないスライド番号（1始まり）は、
  最後に「single_slides=[1,2,6,7,...]」のように昇順で列挙してください。
  
3. [スライド構造]
- 各スライドを次の形式で1行ずつ書く：
  - 「slide 001: 種別=concept, キーワード=○○, 軽い内容説明（いずれかのグループに属している場合は，そのグループ内での役割）」
- 種別候補：
  - "title", "overview", "concept", "example", "derivation", "exercise", "summary", "other"

4. [キー用語・記号・略語]
- 講義全体を通して重要な用語・記号・略語を列挙
- 各項目：用語 / 読み（あれば） / 学部生向けの短い説明（1〜2文）

5. [難所・誤解しやすいポイント]
- つまずきやすそうな部分を箇条書き
- 各項目：スライド番号、なぜ難しいか、説明時の注意点

[Notes]
- 出力はテキスト形式で構いませんが、必ず次の見出しをこの順番で含めてください：
  [全体概要]
  [スライドグループ]
  [スライド構造]
  [キー用語・記号・略語]
  [難所・誤解しやすいポイント]
- ナレーション本文そのものはここでは書かないでください。
  あくまで構造・用語・難所・グループの分析情報のみを出力してください。
""".strip()

    scan_messages = [
        scan_system_message,
        build_responses_user_message(scan_text, scan_img_paths),
    ]

    # --- 4) GPT 呼び出し ---
    _scan_response, scan_result = call_responses_text(
        client,
        modelname=config.API_MODEL_DECK_SCAN,
        messages=scan_messages,
    )

    # --- 5) 保存 ---
    all_page_scan_output_dir.mkdir(parents=True, exist_ok=True)
    scan_txt_path = all_page_scan_output_dir / "deck_scan_overview.txt"

    with scan_txt_path.open("w", encoding="utf-8-sig", newline="\n") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"# deck_scan_overview / created at {ts}\n")
        f.write(f"# total_slides: {len(scan_img_paths)}\n")
        f.write(f"# LEVEL={level} ({level_desc}) / DETAIL={detail} ({detail_desc})\n\n")
        for i, p in enumerate(scan_img_paths, 1):
            f.write(f"# slide_{i:03d}: {Path(p).resolve()}\n")
        f.write("\n")
        f.write(scan_result)
        f.write("\n")

    # --- 6) プレビュー ---
    print(f"[Saved] {scan_txt_path}")
    preview = scan_result[:500] + ("..." if len(scan_result) > 500 else "")
    print(preview)

    return scan_txt_path
