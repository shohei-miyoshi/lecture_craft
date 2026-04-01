# src/auto_lecture/audio_only_lecture.py
# -*- coding: utf-8 -*-
"""
音声のみの講義台本を生成するモジュール（1モード版）。

- 入力:
    - ProjectPaths（paths.build_paths の戻り値）
    - Level / Detail（L1〜, D1〜）…ステッチ時のスタイル指定にのみ使用

- 出力（paths.explanation_save_dir / "audio_only" 以下）:
    - materials_slide_001.txt, materials_slide_002.txt, ...
    - materials_all.txt
    - outline.json
    - outline.txt
    - lecture_script.txt  （ステッチ前）
    - lecture_script_stitched.txt （ステッチ後 / 実質こちらを使う想定）

OpenAI クライアントは gpt_client.py 経由で取得する。
画像 + GPT-5 では JSON を強制せず、テキスト出力を基本とする。

フロー:
  1) スライドごとの「材料抽出」
  2) 全材料 + 全スライド画像から「アウトライン生成」
  3) 章ごとのナレーション生成（1種類のみ）
       - 各章の target_slides に対応するスライド群の材料 + 画像のみを使用
  4) ステッチ（このタイミングで Level/Detail をスタイル指定として渡す）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import base64
import json
import re

from openai import OpenAI

from .paths import ProjectPaths
from .gpt_utils import ask_gpt  # 他モジュール用に残す（ここでは使わない）
from .deck_scan import collect_slide_images
from .config import API_MODEL_EXPLANATION
from .audio_only_style_axes import resolve_audio_only_style


# ============================================================
#  ユーティリティ
# ============================================================


def sentence_split_ja(text: str) -> str:
    """
    日本語の文末（。！？）で改行し、連続空行を1行に圧縮する。
    音声ナレーションを字幕的に扱いたいときに便利。
    """
    parts = re.split(r"(?<=[。！？])", text)
    lines = [p.strip() for p in parts if p.strip()]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def extract_json_object(text: str) -> Dict[str, Any]:
    """
    テキスト中に含まれる最初の JSON オブジェクトを抽出して dict に変換する。
    失敗した場合は空 dict を返す。
    """
    try:
        start = text.index("{")
        end = text.rfind("}") + 1
        core = text[start:end]
        obj = json.loads(core)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def ensure_audio_only_dir(paths: ProjectPaths) -> Path:
    """
    outputs/<教材PDF名>_*_LxDy/lecture_outputs/lecture_texts/audio_only/
    を作成して Path を返す。
    """
    base_dir = Path(paths.explanation_save_dir) / "audio_only"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


# ============================================================
#  GPT-5 用ヘルパー（Responses API 専用）
# ============================================================


def _build_user_message_with_image(
    text_prompt: str,
    img_path: Path,
) -> Dict[str, Any]:
    """
    Responses API 用の user メッセージ（単一画像付き）を構築する。

    content は list[content-part] で:
      - {"type": "input_text", "text": "..."}
      - {"type": "input_image", "image_url": "data:image/xxx;base64,...."}
    """
    img_path = Path(img_path)
    suffix = img_path.suffix.lower()
    fmt = suffix.lstrip(".") if suffix else "png"
    if fmt == "jpg":
        fmt = "jpeg"

    with img_path.open("rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    data_url = f"data:image/{fmt};base64,{b64}"

    return {
        "role": "user",
        "content": [
            {"type": "input_text", "text": text_prompt.strip()},
            {
                "type": "input_image",
                "image_url": data_url,
            },
        ],
    }


def _build_user_message_with_images(
    text_prompt: str,
    img_paths: List[Path],
) -> Dict[str, Any]:
    """
    Responses API 用の user メッセージ（複数画像付き）を構築する。

    content は list[content-part] で:
      - 先頭に {"type": "input_text", "text": "..." }
      - 続けて各スライド画像の {"type": "input_image", ...}
    """
    content: List[Dict[str, Any]] = [
        {"type": "input_text", "text": text_prompt.strip()},
    ]

    for p in img_paths:
        p = Path(p)
        suffix = p.suffix.lower()
        fmt = suffix.lstrip(".") if suffix else "png"
        if fmt == "jpg":
            fmt = "jpeg"

        with p.open("rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        data_url = f"data:image/{fmt};base64,{b64}"
        content.append(
            {
                "type": "input_image",
                "image_url": data_url,
            }
        )

    return {
        "role": "user",
        "content": content,
    }


def _normalize_system_content(system_text: str) -> Dict[str, Any]:
    """
    Responses API 用の system メッセージを content-part 形式で構築。
    """
    return {
        "role": "system",
        "content": [
            {"type": "input_text", "text": system_text.strip()},
        ],
    }


def _call_gpt5_responses(
    client: OpenAI,
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    audio_only_lecture 専用:
    GPT-5 を Responses API で呼び出し、他モジュールと干渉しないようにする。

    戻り値の形式は ask_gpt と合わせて:
        [{"response": resp, "result": ""}]
    """
    modelname = API_MODEL_EXPLANATION or "gpt-5"

    resp = client.responses.create(
        model=modelname,
        input=messages,
        # 出力トークンは API 側のデフォルト上限に任せる
    )

    return [{
        "response": resp,
        "result": "",
    }]


def _extract_text_from_response(
    resp_list: Any,
    step_name: str,
    context: str = "",
) -> str:
    """
    ask_gpt/_call_gpt5_responses の返却値からテキスト部分を安全に取り出す。

    想定している2パターン:
      1. Responses API 形式:
         - resp.output_text に全テキストがまとまっている（推奨）
         - resp.output[i].content[j].text に個別のテキストが入ることもある
      2. ChatCompletions 形式（念のため）:
         - response.choices[0].message.content

    どちらでも取れなければ RuntimeError を投げる。
    """
    if not resp_list:
        raise RuntimeError(f"{step_name}: モデル応答が空でした (resp_list が空)")

    first = resp_list[0]
    resp = first.get("response")
    if resp is None:
        raise RuntimeError(f"{step_name}: 'response' キーが見つかりません")

    # --- 1) Responses API の output_text を試す ---
    try:
        output_text = getattr(resp, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text
    except Exception:
        pass

    # --- 2) Responses API の output[*].content[*].text を試す ---
    try:
        output = getattr(resp, "output", None)
        if output:
            texts: List[str] = []
            for item in output:
                contents = getattr(item, "content", None)
                if not contents:
                    continue
                for c in contents:
                    t = getattr(c, "text", None)
                    if isinstance(t, str) and t.strip():
                        texts.append(t)
            if texts:
                return "\n".join(texts)
    except Exception:
        pass

    # --- 3) ChatCompletions 形式（保険） ---
    try:
        choices = getattr(resp, "choices", None)
        if choices:
            msg = choices[0].message
            content = getattr(msg, "content", None)

            # content が str の場合
            if isinstance(content, str):
                return content

            # content が list[content-part] の場合
            if isinstance(content, list):
                texts2: List[str] = []
                for part in content:
                    p_type = None
                    p_text = None
                    if isinstance(part, dict):
                        p_type = part.get("type")
                        if p_type == "text":
                            p_text = part.get("text")
                    else:
                        p_type = getattr(part, "type", None)
                        if p_type == "text":
                            p_text = getattr(part, "text", None)
                    if p_type == "text" and p_text:
                        texts2.append(p_text)
                if texts2:
                    return "\n".join(texts2)
    except Exception:
        pass

    raise RuntimeError(
        f"{step_name}: モデル応答からテキストを取り出せませんでした。\n"
        f"context={context}"
    )


def _save_debug_response(debug_path: Path, resp_list: Any) -> None:
    """
    生レスポンスをデバッグ用に保存（失敗してもエラーにはしない）。
    """
    try:
        from pprint import pformat

        debug_path.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(pformat(resp_list, width=120), encoding="utf-8")
    except Exception:
        pass


# ============================================================
#  プロンプト定義
# ============================================================

# ------ 1) 各スライドから材料抽出（テキスト） ------

SYSTEM_MATERIAL = """
あなたは日本語で大学講義スライドから「講義ナレーションの材料」を抜き出すアシスタントです。

重要：
- 材料として使ってよいのは、スライド画像の中に **実際に書かれている内容だけ** です。
- スライドに書かれていない情報を、自分の知識にもとづいて新しく付け足してはいけません。

禁止事項：
- スライドに存在しない情報を追加すること。
- 教科書や一般的な知識をもとに、スライドが触れていない話題を広げること。
- 「このスライドには書かれていないが一般には〜」といった補足を書くこと。

もし、ある観点（例：数式・応用分野など）がスライドに書かれていない場合は、
その項目には「（スライドに明示的な記載なし）」とだけ書いてください。

出力は日本語テキストのみとし、JSON やコードブロック、マークダウン記法は使わないでください。
"""


SLIDE_MATERIAL_PROMPT = """
[タスク]
これから 1 枚のスライド画像を見て、
そのスライド **上に実際に書かれている内容だけ** をもとに、
音声のみの講義ナレーションに使える「材料」を整理してください。

[出力フォーマット]
次の見出しの順に、日本語で箇条書きでまとめてください。
各項目の箇条書きは、スライド上に書かれている語句・式・図・例を
「意味を変えずに、耳で聞いて分かるように言い換えたもの」に限ってください。

[定義]
- スライドに明示的に書かれている用語や概念の定義・説明のみを書く。
- スライドに書かれていない一般的な定義や背景を新たに追加してはいけない。
- 書く内容がなければ「- （スライドに明示的な記載なし）」とする。

[数式・関係式]
- スライドに書かれている数式・関係式だけを、耳で読み上げやすい形で書く。
- スライドに存在しない数式・決定則・評価指標などを新しく導入しない。
- なければ「- （スライドに明示的な記載なし）」とする。

[例・具体的なイメージ]
- スライド上に具体例やイラストがある場合のみ、それに対応する説明を書く。
- 新しい例を自分で考えて追加してはいけない。
- なければ「- （スライドに明示的な記載なし）」とする。

[応用・関連分野]
- スライド上に応用分野・関連領域が列挙されている場合、それだけを書き直す。
- スライドにない応用分野を一般知識から追加してはいけない。
- なければ「- （スライドに明示的な記載なし）」とする。

[キーポイント]
- スライド上の見出しや強調箇所から、このスライドの「主題」と読み取れる内容を、
  スライドの表現に忠実に 1〜2 文でまとめる。
- 新しい主張や教科書的なまとめを勝手に作らない。

[制約]
- 図やレイアウトの位置に依存する表現（「この図の右上」など）は使わない。
- 箇条書きの行頭には必ず「- 」を付ける。
- スライドに書かれていない内容を、推測で補ったり拡張してはいけない。
"""


# ------ 2) アウトライン生成（材料 + 全スライド画像 → JSON + 説明） ------

SYSTEM_OUTLINE = """
あなたは日本語で音声講義の章立てを設計する教育工学の専門家です。

【あなたに渡される情報】
- 各スライドから抽出した「材料テキスト」
  （スライドに書かれている語句や図・例を要約したもの）
- 全スライドの画像
  （1枚目がスライド1，2枚目がスライド2，…という順番）

【重要な制約】
- 章立てに使ってよい内容は、
  「スライドに実際に書かれている内容」や
  「図から直接読み取れる範囲の情報」に限ります。
- スライドに存在しない発展的な話題や新しいトピックを、
  勝手に追加してはいけません。

【出力方針】
- JSON 形式で講義全体のアウトライン（章構成）を最初に出力する。
- JSON はコードブロックを使わず、そのままテキストとして出力する。
- 各章には、その章で主に扱うスライド番号（target_slides）を必ず含める。
- JSON のあとに，各章のねらいを日本語で短く説明してもよい。
"""

OUTLINE_PROMPT = """
[材料テキスト（スライドに基づく要約）]
以下は、各スライドから抽出した材料を連結したものです。
※ここに含まれる内容も、もともとはスライドに書かれている情報に由来します。
--------------------
{materials_text}
--------------------

[スライド画像について]
- あなたには、スライド1〜{num_slides} の画像も同時に渡されています。
- 画像の並びは「1枚目 = スライド1, 2枚目 = スライド2, …」です。
- 章立てを考えるときは、「どのスライドをどの章で扱うか」を意識してください。

[タスク]
- スライドに書かれている内容だけに基づいて、
  音声のみの講義として自然な「章立て」を設計してください。
- 各章ごとに、「どのスライドを主に説明するのか」を target_slides に指定してください。

[要件]
- 講義全体を通して主題が自然につながるように章を構成する。
- 主題と直接関係しない発展的な話題や，
  スライドに現れていない新しいトピックはここでは入れない。
- 同じスライドを複数の章にまたがって使う場合は、
  そのスライド番号を複数の章に含めてもよいが、不必要な重複は避ける。

[JSON出力仕様]
次のような JSON オブジェクトを最初に出力してください。

{{
  "title": "講義全体のタイトル（短く分かりやすく。スライド全体の主題から素直に付ける）",
  "chapters": [
    {{
      "id": 1,
      "title": "第1章のタイトル（スライドの見出しに沿った簡潔な表現）",
      "summary": "その章で何を説明するか（2〜3文）",
      "target_slides": [1]
    }}
    ...
  ]
}}

[注意]
- JSON を最初に 1 回だけ出力してください。
- JSON の中ではコメント (// ...) は入れないでください。
- JSON のあとに，各章のねらいを日本語で簡単に説明して構いません。
"""


# ------ 3) 章ごとのナレーション生成（1種類のみ） ------

SYSTEM_NARRATION = """
あなたは日本語で「音声のみで理解できる講義ナレーション」を作成する講師です。

【あなたに渡される情報】
- この章に対応するスライド画像（target_slides の番号に対応）
- そのスライドから抽出した材料テキスト
  （スライドに書かれている語句や図・例の要約）
- 講義全体のアウトライン（章タイトル・要約・target_slides）

【重要な制約】
- 説明の中心は、必ず
  「この章の target_slides に対応するスライドに実際に書かれている内容・図・例」
  に置いてください。
- スライドに存在しない話題を長々と展開したり、新しいトピックを勝手に導入してはいけません。
- ただし、スライドの主題を少し補うための短い背景説明や、具体例などは許容されます（あくまでスライドの主題から離れない範囲で）。
- 章題は必要ないです。音声で読み上げるものだけを生成してください。

【目的】
- 音声だけで聞き手が、そのスライドの主題とメッセージをきちんと理解できるようにする。

【出力方針】
- 出力はナレーション本文のみ。
  メタ情報・指示文・JSON・コードブロックは書かない。

以上の方針に従って、この章に対応するスライドの主題を、
耳で理解しやすい形で説明してください。
"""

NARRATION_PROMPT_TEMPLATE = """
[この章に対応する材料テキスト]
以下は、この章の target_slides に対応するスライドから抽出した材料の要約です。
（スライドに実際に書かれている語句や図・例に基づいています。）
--------------------
{materials_text}
--------------------

[講義全体のアウトライン（参考）]
以下は講義全体の章構成（JSON）です。現在の章はその一部です。
--------------------
{outline_json}
--------------------

[この章の情報]
- 対象の章 ID: {chapter_id}
- 章タイトル: {chapter_title}
- 章の要約: {chapter_summary}
- 対象スライド番号（target_slides）: {target_slides_str}

[スライド画像について]
- あなたには、この章の target_slides に対応するスライド画像も同時に渡されています。
- 画像の並びは「1枚目 = target_slides の先頭のスライド、2枚目 = 2番目のスライド、…」です。
- 説明の中心は、必ずこれらのスライドに実際に書かれている内容・図・例としてください。

[出力スタイル]
- モード: 講義ナレーション
- 日本語で、音声読み上げを前提とした自然な講義口調で書く。
- 長すぎる一文は避け、聞き取りやすい長さで文を区切る。
- JSONやコードブロックは絶対に書かない。
"""


# ------ 4) ステッチ・整形（任意 / Level・Detail をここで反映） ------

SYSTEM_STITCH = """
あなたは日本語の講義ナレーションを自然な流れに整える編集者です。

[目的]
- 既に書かれている講義ナレーションを読みやすく、聞きやすく整えます。
- 章と章のつながりを滑らかにし、重複している説明は必要に応じてまとめます。

[出力条件]
- プレーンテキストのみ（JSON やコードブロックは使わない）。
- 章題は必要ないです。音声で読み上げるものだけを生成してください。
- 文は音声読み上げを意識して、長すぎないように調整する。
- 専門用語は削らず、説明を簡潔にする。
- 図や位置への参照は追加しない。
- 出力は台本本文のみ。
"""

STITCH_PROMPT_TEMPLATE = """
[入力ナレーション全文]
--------------------
{script_text}
--------------------

[スタイル指定（Level / Detail 軸）]
- この音声講義は、スタイルコード {style_label} （レベル: {style_level}, 詳細度: {style_detail}）を想定しています。
- レベルの説明: {style_level_text}
- 詳細度の説明: {style_detail_text}

これらのスタイル指定に沿うように、
- 説明の深さや分量
- 用語の扱い方
- 文の長さやテンポ
を適切に調整してください。

[タスク]
上の講義ナレーションを、音声のみの講義として聞きやすいように整えてください。

- 章と章のつながりを自然にする。
- 同じ説明が何度も繰り返されている場合は、適度にまとめる。
- 文の長さが極端に長い場合は、2文に分けるなどして調整する。
- 図や位置への参照は追加しない。
- 出力は台本本文のみ。

出力は日本語のプレーンテキストのみとし、JSON やコードブロックは使わないでください。
"""


# ============================================================
#  ステップ 1: 材料抽出
# ============================================================

@dataclass
class MaterialsResult:
    audio_only_dir: Path
    img_paths: List[str]
    materials_slide_paths: List[Path]
    materials_all_path: Path


def step_extract_materials(
    client: OpenAI,
    paths: ProjectPaths,
) -> MaterialsResult:
    """
    各スライド画像から講義ナレーションの「材料テキスト」を抽出する。
    """
    audio_only_dir = ensure_audio_only_dir(paths)

    img_root = Path(paths.img_root)
    img_paths: List[str] = collect_slide_images(img_root)

    materials_slide_paths: List[Path] = []
    all_buf: List[str] = []

    total_slides = len(img_paths)
    print(f"[audio_only] 材料抽出: {total_slides} 枚のスライドを処理します")

    debug_dir = audio_only_dir / "_debug_raw_materials"
    debug_dir.mkdir(parents=True, exist_ok=True)

    for idx, img_path_str in enumerate(img_paths, start=1):
        img_path = Path(img_path_str)
        slide_str = f"{idx:03d}"
        print(f"[audio_only] 材料抽出: Slide {idx}/{total_slides}: {img_path}")

        text_prompt = SLIDE_MATERIAL_PROMPT.format(
            slide_index=idx,
            total_slides=total_slides,
        )

        system_message = _normalize_system_content(SYSTEM_MATERIAL)
        user_message = _build_user_message_with_image(text_prompt, img_path)

        messages = [system_message, user_message]

        resp_list = _call_gpt5_responses(client, messages)

        debug_raw_path = debug_dir / f"slide_{slide_str}_raw.txt"
        _save_debug_response(debug_raw_path, resp_list)

        try:
            material_text = _extract_text_from_response(
                resp_list,
                step_name="材料抽出",
                context=f"slide={idx}",
            )
        except Exception as e:
            print(f"[audio_only] ⚠ 材料抽出エラー（slide {idx}）: {e}")
            material_text = (
                f"【注意】スライド {idx} から材料抽出中にエラーが発生しました。\n"
                "詳細は _debug_raw_materials のログを確認してください。"
            )

        if not material_text or not material_text.strip():
            print(f"[audio_only] ⚠ モデル応答が空でした: slide {idx}")
            material_text = (
                f"【注意】スライド {idx} から抽出できる講義材料が "
                "モデル応答として空でした。\n"
                "このスライドには、講義ナレーションに直接使えるテキスト情報が "
                "ほとんど含まれていない可能性があります。"
            )

        material_text = material_text.strip()

        slide_path = audio_only_dir / f"materials_slide_{slide_str}.txt"
        slide_path.write_text(material_text, encoding="utf-8")
        materials_slide_paths.append(slide_path)

        all_buf.append(f"# [slide_{slide_str}]\n{material_text}\n\n")

        print(f"[audio_only] Slide {idx}: 抽出テキスト長 = {len(material_text)} 文字")

    materials_all_path = audio_only_dir / "materials_all.txt"
    materials_all_path.write_text("".join(all_buf), encoding="utf-8")

    print(f"[audio_only] 材料テキストを保存しました: {materials_all_path}")

    return MaterialsResult(
        audio_only_dir=audio_only_dir,
        img_paths=img_paths,
        materials_slide_paths=materials_slide_paths,
        materials_all_path=materials_all_path,
    )


# ============================================================
#  ステップ 2: アウトライン生成
# ============================================================

@dataclass
class OutlineResult:
    outline_json: Dict[str, Any]
    outline_json_path: Path
    outline_txt_path: Path
    lecture_title: str


def step_generate_outline(
    client: OpenAI,
    materials_all_path: Path,
    audio_only_dir: Path,
    img_paths: List[str],
) -> OutlineResult:
    """
    materials_all.txt と全スライド画像をもとに、
    講義全体のアウトライン（JSON + テキスト）を生成。
    """
    materials_text = materials_all_path.read_text(encoding="utf-8")

    user_content = OUTLINE_PROMPT.format(
        materials_text=materials_text,
        num_slides=len(img_paths),
    )

    messages = [
        _normalize_system_content(SYSTEM_OUTLINE),
        _build_user_message_with_images(
            user_content,
            [Path(p) for p in img_paths],
        ),
    ]

    print("[audio_only] アウトライン生成中...")

    resp_list = _call_gpt5_responses(client, messages)

    debug_path = audio_only_dir / "_debug_outline_raw.txt"
    _save_debug_response(debug_path, resp_list)

    try:
        outline_raw = _extract_text_from_response(
            resp_list,
            step_name="アウトライン生成",
        )
    except Exception as e:
        raise RuntimeError(f"アウトライン生成のモデル応答の形式が想定と異なります: {e}")

    outline_raw = outline_raw.strip()

    outline_txt_path = audio_only_dir / "outline.txt"
    outline_txt_path.write_text(outline_raw, encoding="utf-8")

    outline_json = extract_json_object(outline_raw)
    if not outline_json:
        outline_json = {
            "title": "音声講義",
            "chapters": [
                {
                    "id": 1,
                    "title": "全体",
                    "summary": "講義全体を通して主要な内容を説明する。",
                    "target_slides": [],
                }
            ],
        }

    outline_json_path = audio_only_dir / "outline.json"
    outline_json_path.write_text(
        json.dumps(outline_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lecture_title = outline_json.get("title") or "音声講義"

    print(f"[audio_only] アウトライン JSON を保存しました: {outline_json_path}")
    print(f"[audio_only] 講義タイトル: {lecture_title}")

    return OutlineResult(
        outline_json=outline_json,
        outline_json_path=outline_json_path,
        outline_txt_path=outline_txt_path,
        lecture_title=lecture_title,
    )


# ============================================================
#  ステップ 3: 章ごとのナレーション生成（1モード）
# ============================================================


def _get_chapters_from_outline(outline_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    chapters = outline_json.get("chapters")
    if isinstance(chapters, list) and chapters:
        return chapters

    return [
        {
            "id": 1,
            "title": outline_json.get("title", "全体"),
            "summary": outline_json.get(
                "summary", "講義全体の内容をまとめて説明する。"
            ),
            "target_slides": [],
        }
    ]


def step_generate_narration(
    client: OpenAI,
    materials_slide_paths: List[Path],
    outline_json: Dict[str, Any],
    audio_only_dir: Path,
    img_paths: List[str],
) -> Path:
    """
    章ごとのナレーションを生成し、連結して 1 ファイルに保存する。

    - 各章は、outline_json.chapters[*].target_slides に対応する
      スライドの材料テキスト + 画像のみを使う。

    戻り値: lecture_script.txt の Path
    """
    # slide_idx (1始まり) -> materials テキスト
    materials_by_slide: Dict[int, str] = {}
    for idx, p in enumerate(materials_slide_paths, start=1):
        try:
            materials_by_slide[idx] = p.read_text(encoding="utf-8")
        except Exception:
            materials_by_slide[idx] = ""

    outline_json_str = json.dumps(outline_json, ensure_ascii=False, indent=2)
    chapters = _get_chapters_from_outline(outline_json)

    system_content = SYSTEM_NARRATION
    mode_label = "講義ナレーション"

    lecture_parts: List[str] = []

    print(f"[audio_only] ナレーション生成: chapters={len(chapters)}")

    total_slides = len(img_paths)

    for ch in chapters:
        cid = int(ch.get("id", len(lecture_parts) + 1))
        ctitle = str(ch.get("title", f"第{cid}章"))
        csummary = str(ch.get("summary", ""))
        target_slides = ch.get("target_slides", [])
        if not isinstance(target_slides, list):
            target_slides = []

        # -------- 章用の材料テキストを作成 --------
        chapter_materials_parts: List[str] = []
        for sid in target_slides:
            try:
                sid_int = int(sid)
            except Exception:
                continue
            t = materials_by_slide.get(sid_int, "").strip()
            if t:
                chapter_materials_parts.append(f"# [slide_{sid_int:03d}]\n{t}")

        if chapter_materials_parts:
            chapter_materials_text = "\n\n".join(chapter_materials_parts)
        else:
            chapter_materials_text = (
                "（この章に対応するスライド材料が指定されていません。"
                "必要最小限の説明にとどめてください。）"
            )

        # -------- 章用のスライド画像リスト --------
        chapter_img_paths: List[Path] = []
        for sid in target_slides:
            try:
                sid_int = int(sid)
            except Exception:
                continue
            if 1 <= sid_int <= total_slides:
                chapter_img_paths.append(Path(img_paths[sid_int - 1]))

        user_content = NARRATION_PROMPT_TEMPLATE.format(
            materials_text=chapter_materials_text,
            outline_json=outline_json_str,
            chapter_id=cid,
            chapter_title=ctitle,
            chapter_summary=csummary,
            target_slides_str=str(target_slides),
        )

        messages = [
            _normalize_system_content(system_content),
            _build_user_message_with_images(user_content, chapter_img_paths),
        ]

        resp_list = _call_gpt5_responses(client, messages)

        debug_path = audio_only_dir / f"_debug_narration_raw_ch_{cid}.txt"
        _save_debug_response(debug_path, resp_list)

        try:
            chapter_text = _extract_text_from_response(
                resp_list,
                step_name="ナレーション生成",
                context=f"chapter_id={cid}",
            )
        except Exception as e:
            raise RuntimeError(
                "ナレーション生成のモデル応答の形式が想定と異なります"
                f"（chapter_id={cid}）: {e}"
            )

        chapter_text = chapter_text.strip()
        chapter_text = sentence_split_ja(chapter_text)

        lecture_parts.append(f"## {ctitle}\n{chapter_text}\n")

    full_script = "\n\n".join(lecture_parts).strip()

    out_path = audio_only_dir / "lecture_script.txt"
    out_path.write_text(full_script, encoding="utf-8")

    print(f"[audio_only] ナレーションを保存しました: {out_path}")
    return out_path


# ============================================================
#  ステップ 4: ステッチ・整形（任意 / Level・Detail 反映）
# ============================================================


def step_stitch_script(
    client: OpenAI,
    script_path: Path,
    level: str,
    detail: str,
) -> Path:
    """
    生成済みの lecture_script.txt を読み込み、
    Level / Detail のスタイル指定に従って全体の流れを滑らかにした
    バージョンを lecture_script_stitched.txt として保存する。
    """
    script_text = script_path.read_text(encoding="utf-8")

    style = resolve_audio_only_style(level, detail)

    prompt_text = STITCH_PROMPT_TEMPLATE.format(
        script_text=script_text,
        style_label=style.style_label,
        style_level=style.level,
        style_detail=style.detail,
        style_level_text=style.level_text,
        style_detail_text=style.detail_text,
    )

    messages = [
        _normalize_system_content(SYSTEM_STITCH),
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": prompt_text,
                },
            ],
        },
    ]

    print(f"[audio_only] ステッチ中... ({script_path.name}) [style={style.style_label}]")

    resp_list = _call_gpt5_responses(client, messages)

    debug_path = script_path.parent / f"_debug_stitch_raw_{script_path.name}.txt"
    _save_debug_response(debug_path, resp_list)

    try:
        stitched = _extract_text_from_response(
            resp_list,
            step_name="ステッチ処理",
            context=str(script_path),
        )
    except Exception as e:
        raise RuntimeError(
            f"ステッチ処理のモデル応答の形式が想定と異なります（{script_path}）: {e}"
        )

    stitched = sentence_split_ja(stitched.strip())

    out_path = script_path.parent / "lecture_script_stitched.txt"
    out_path.write_text(stitched, encoding="utf-8")

    print(f"[audio_only] ステッチ済みスクリプトを保存しました: {out_path}")
    return out_path


# ============================================================
#  オーケストレーション関数
# ============================================================

@dataclass
class AudioOnlyLectureResult:
    audio_only_dir: Path
    materials_all_path: Path
    materials_slide_paths: List[Path]
    outline_json_path: Path
    outline_txt_path: Path
    lecture_title: str
    script_path: Path  # ステッチ後の台本を返す


def generate_audio_only_lecture(
    client: OpenAI,
    paths: ProjectPaths,
    level: str = "L3",
    detail: str = "D2",
    do_stitch: bool = True,
) -> Dict[str, Any]:
    """
    音声のみ講義フローを実行するメイン関数。

    - level/detail はステッチ時のスタイル指定にのみ使用する。
    """
    # 1) 材料抽出
    mres = step_extract_materials(client, paths)
    audio_only_dir = mres.audio_only_dir
    materials_all_path = mres.materials_all_path

    # 2) アウトライン生成（全スライド画像も渡す）
    ores = step_generate_outline(
        client,
        materials_all_path,
        audio_only_dir,
        img_paths=mres.img_paths,
    )
    outline_json = ores.outline_json

    # 3) ナレーション生成（1本）
    script_raw_path = step_generate_narration(
        client=client,
        materials_slide_paths=mres.materials_slide_paths,
        outline_json=outline_json,
        audio_only_dir=audio_only_dir,
        img_paths=mres.img_paths,
    )

    # 4) ステッチ（任意）
    if do_stitch:
        script_final_path = step_stitch_script(
            client=client,
            script_path=script_raw_path,
            level=level,
            detail=detail,
        )
    else:
        script_final_path = script_raw_path

    result = AudioOnlyLectureResult(
        audio_only_dir=audio_only_dir,
        materials_all_path=materials_all_path,
        materials_slide_paths=mres.materials_slide_paths,
        outline_json_path=ores.outline_json_path,
        outline_txt_path=ores.outline_txt_path,
        lecture_title=ores.lecture_title,
        script_path=script_final_path,
    )

    return {
        "audio_only_dir": result.audio_only_dir,
        "materials_all_path": result.materials_all_path,
        "materials_slide_paths": result.materials_slide_paths,
        "outline_json_path": result.outline_json_path,
        "outline_txt_path": result.outline_txt_path,
        "lecture_title": result.lecture_title,
        "script_path": result.script_path,
    }


def run_audio_only_lecture(
    paths: ProjectPaths,
    level: str = "L3",
    detail: str = "D2",
    do_stitch: bool = True,
) -> Dict[str, Any]:
    """
    gpt_client.create_client() を使ってクライアントを生成し、
    そのまま generate_audio_only_lecture を呼ぶラッパー。
    """
    from .gpt_client import create_client

    client = create_client()
    return generate_audio_only_lecture(
        client=client,
        paths=paths,
        level=level,
        detail=detail,
        do_stitch=do_stitch,
    )
