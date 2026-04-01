# src/auto_lecture/lecture_script.py
from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import List
import re

from openai import OpenAI

from .paths import ProjectPaths
from .style_axes import resolve_level_detail
from .deck_scan import collect_slide_images
from .gpt_utils import encode_image
from . import config


def build_prompt_for_slide(
    slide_no: int,
    total_slides: int,
    previous_texts: List[str],
    deck_scan_text: str,
    level_desc: str,
    detail_desc: str,
) -> str:
    """
    1スライド分のプロンプトを組み立てる。
    Deck Scan 情報 + 直前スライドの台本も埋め込む。
    """
    # 直前スライドの台本ブロック
    if previous_texts:
        prev_block = "[Previous page]:\n"
        for prev_text in previous_texts:
            prev_block += prev_text.strip() + "\n"
    else:
        prev_block = "[Previous page]:\n(なし)\n"

    # Deck Scan 情報ブロック
    if deck_scan_text:
        deck_block = f"""
[Deck Scan Info]
以下は、この講義スライド全体に対して事前に行った分析結果です。
特に [スライドグループ] / single_slides の情報には、
「どのスライドが同じグループに属しているか」や、
「どのスライドが単独で扱われるか」が書かれています。

現在のスライド番号（current_slide_index）が、
- どのグループに属しているか
- そのグループの途中なのか、最後なのか
- あるいは single_slides に属する単独スライドなのか

をあなた自身で判断し、その役割に応じてナレーションの量と内容を調整してください。

--- 全体スキャン結果ここから ---
{deck_scan_text}
--- 全体スキャン結果ここまで ---
""".strip()
    else:
        deck_block = """
[Deck Scan Info]
全体スキャン結果（deck_scan_overview.txt）が利用できないため、
スライド画像と直前のナレーションだけから判断して台本を作成してください。
""".strip()

    prompt = f"""
[Role / Goal]
あなたは日本語で講義台本を作成する優れたプレゼンターです。
講義資料画像に音声を吹き込みますので，資料に書かれている内容に沿ってナレーションを作成してください。
講義資料に書かれているテキストを必要に応じて利用しつつ，教育的に効果的な講義台本を作成してください。

[Audience]
講義相手は，情報系の学部に所属していて，情報系について学んできた大学生です。
この前提知識を踏まえて説明してください。

[Style Axes]
レベル軸（Level Axis）: {level_desc}
詳細度軸（Detail Axis）: {detail_desc}

[Slide metadata]
- current_slide_index: {slide_no}
- total_slides: {total_slides}

[Content Policy]
- 講義資料画像に書かれている内容に忠実に沿って説明してください。
- 講義資料に記載の文章をそのまま読み上げるだけにせず，必ず，講義資料に書かれていない関連した内容を追加した説明にしてください。
  - ただし，講義資料に書かれていない内容は簡潔に触れる程度にとどめてください。
- タイトルのみのページでは，関連した内容の追加は不要です。
  - 講義タイトルや概要を端的に述べ，短いひとこと挨拶を添える程度にしてください。
- 「〜を求めなさい」「〜を解きなさい」「〜を確かめなさい」などが主となるページは演習問題のページとして扱います。
  - その場合は，問題文の内容を自然な形で読み上げるだけにし，解答や解法の説明は行わないでください。

[Form / Style Constraints]
- 毎回の挨拶は不要です。
- タイトルページは，余計な説明はせずに端的に講義タイトルや内容に加えて，ひとこと挨拶を加えてください。
- 次のスライドについての案内は不要です。
- 各ページの冒頭で「このスライドでは」「このスライドの目的は」のようなメタ的な導入文は書かないでください。
- 説明文は箇条書きにせず，自然な日本語の連続した文章として書いてください。
- 出力中に「レベル軸」「詳細度軸」「L1/L2/L3」「D1/D2/D3」といった制御パラメータを明示的に書かないでください。
  （これらは内部方針としてのみ反映してください。）

[Coherence Policy]
- [Previous page]ですでに十分に説明した内容は繰り返さないでください。
- [Previous page]で説明されている流れを意識して，文脈的な一貫性を保ったナレーションを作成してください。
- 新しいスライドで，同じ概念が再登場する場合は，「初出ではない」ことを前提に，必要な最小限の補足のみにとどめてください。
- ナレーション本文では，説明用の括弧（ ）を原則として使わないでください。

{deck_block}

{prev_block}

[Instruction]
上記の条件と [Deck Scan Info] の内容に従って，
「current_slide_index に対応するこのスライド」のためのナレーションのみを，日本語で出力してください。

- 余計なメタ情報や説明（プロンプトの要約，方針の言い換えなど）は書かず，
  完成された講義台本としての文章のみを出力してください。
""".strip()

    return prompt


def generate_lecture_scripts(
    client: OpenAI,
    paths: ProjectPaths,
    level: str = "L3",
    detail: str = "D2",
    recent_range: int = 1,
) -> List[str]:
    """
    - deck_scan_overview.txt を読み込み（あれば）
    - 各スライド画像 + DeckScan 情報から講義台本を生成
    - slide_###.txt と all_explanations.txt に保存
    戻り値: スライドごとのナレーション一覧（explanations）
    """
    img_root = paths.img_root
    # ★★★ 保存先を output_dir ではなく explanation_save_dir に変更 ★★★
    text_output_dir = Path(paths.explanation_save_dir).resolve()
    all_page_scan_output_dir = Path(paths.all_page_scan_output_dir)

    # 1) スライド画像パス取得
    img_paths: List[str] = collect_slide_images(img_root)
    total_slides = len(img_paths)

    # 2) deck_scan_overview.txt 読み込み
    scan_txt_path = all_page_scan_output_dir / "deck_scan_overview.txt"
    if scan_txt_path.exists():
        with scan_txt_path.open("r", encoding="utf-8-sig") as f:
            deck_scan_text = f.read().strip()
        print(f"[info] deck_scan_overview を読み込みました: {scan_txt_path}")
    else:
        deck_scan_text = ""
        print(f"[warn] deck_scan_overview.txt が見つかりません。スキャン情報なしでナレーションを生成します: {scan_txt_path}")

    # 3) LEVEL/DETAIL 説明文
    level_desc, detail_desc = resolve_level_detail(level, detail)

    # System メッセージ（共通・文字列でOK）
    system_message = {
        "role": "system",
        "content": (
            "あなたは日本語で講義台本を作成する優れたプレゼンターです。"
            "講義資料画像に音声を吹き込みますので，資料に書かれている内容に沿ってナレーションを作成してください。"
            "講義資料に書かれているテキストを必要に応じて利用しつつ，教育的に効果的な講義台本を作成してください。"
        ),
    }

    # 4) 保存先準備（lecture_texts フォルダ）
    text_output_dir.mkdir(parents=True, exist_ok=True)
    all_txt_path = text_output_dir / "all_explanations.txt"

    # まとめファイルは毎回作り直す
    with all_txt_path.open("w", encoding="utf-8-sig", newline="\n") as _f:
        pass

    explanations: List[str] = []

    # 5) 各スライドに対して生成ループ
    for i, img_path in enumerate(img_paths):
        slide_no = i + 1

        # 直前の台本を recent_range 分だけ参照
        if recent_range > 0:
            prev_texts = explanations[-recent_range:]
        else:
            prev_texts = []

        text_content = build_prompt_for_slide(
            slide_no=slide_no,
            total_slides=total_slides,
            previous_texts=prev_texts,
            deck_scan_text=deck_scan_text,
            level_desc=level_desc,
            detail_desc=detail_desc,
        )

        # 画像を base64 → image_url コンテンツに変換
        img_b64 = encode_image(img_path)
        user_content = [
            {"type": "text", "text": text_content},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
            },
        ]

        # GPT 呼び出し（chat.completions を直接使用）
        try:
            resp = client.chat.completions.create(
                model=config.API_MODEL_EXPLANATION,
                messages=[
                    system_message,
                    {"role": "user", "content": user_content},
                ],
                temperature=config.API_MODEL_EXPLANATION_TEMPERATURE,
                max_completion_tokens=4000,
            )
            result: str = resp.choices[0].message.content or ""
        except Exception as e:
            raise RuntimeError(f"モデル応答の取得に失敗しました（slide {slide_no:03d}）: {e}")

        result = result.strip()
        explanations.append(result)

        # スライドごとのテキスト保存（lecture_texts/slide_###.txt）
        slide_txt = text_output_dir / f"slide_{slide_no:03d}.txt"
        with slide_txt.open("w", encoding="utf-8-sig", newline="\n") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"# slide {slide_no:03d} / created at {ts}\n")
            f.write(f"# image: {Path(img_path).resolve()}\n\n")
            # 読みやすいように句点で改行
            formatted_result = re.sub(r"(?<!\n)\s*([。！？])", r"\1\n", result)
            formatted_result = re.sub(r"\n{3,}", "\n\n", formatted_result).strip()
            f.write(formatted_result)
            f.write("\n")

        # まとめファイルへ追記（整形前の素の結果を入れておく）
        with all_txt_path.open("a", encoding="utf-8-sig", newline="\n") as f_all:
            f_all.write(f"\n=== slide_{slide_no:03d} ===\n")
            f_all.write(result)
            f_all.write("\n")

        preview = result[:200] + ("..." if len(result) > 200 else "")
        print(f"[Saved] {slide_txt.name}  ({slide_no}/{total_slides})")
        print(preview)

    print(f"\n✅ 完了: 出力フォルダ = {text_output_dir}")
    print(f" - スライド別: slide_###.txt × {total_slides}")
    print(f" - まとめ    : {all_txt_path.name}")

    return explanations


def run_lecture_script(
    client: OpenAI,
    paths: ProjectPaths,
    level: str = "L3",
    detail: str = "D2",
    recent_range: int = 1,
) -> List[str]:
    """
    run_all.py から呼ぶためのラッパー関数。
    """
    return generate_lecture_scripts(
        client=client,
        paths=paths,
        level=level,
        detail=detail,
        recent_range=recent_range,
    )
