# src/auto_lecture/animation_assignment.py
from __future__ import annotations

import os
import re
import io
import json
import base64
import pathlib
from glob import glob
from typing import Dict, Any, List, Optional

from pathlib import Path
from openai import OpenAI

from .paths import ProjectPaths
from .config import API_MODEL_ANIMATION
from .gpt_utils import build_responses_system_message, call_responses_text


# ====== Style Catalog ======
STYLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "arrow_point": {
        "llm_hint": "小さい領域や一点を指し示す矢印アニメーション。",
        "aliases": ["arrow", "pointer", "arrowpoint"],
    },
    "marker_highlight": {
        "llm_hint": "重要な文章をマーキングして視線誘導する。",
        "aliases": ["highlight", "marker", "hl"],
    },
    "laser_circle": {
        "llm_hint": "円で囲って注意を集める（レーザーポインタ風）。",
        "aliases": ["circle", "laser", "ring"],
    },
}

_ALIAS_TO_STYLE: Dict[str, str] = {}


def _rebuild_alias_map() -> None:
    global _ALIAS_TO_STYLE
    _ALIAS_TO_STYLE = {}
    for name, meta in STYLE_CATALOG.items():
        _ALIAS_TO_STYLE[name.lower()] = name
        for a in meta.get("aliases", []) or []:
            _ALIAS_TO_STYLE[str(a).lower()] = name


_rebuild_alias_map()


def normalize_style_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = str(name).strip()
    return _ALIAS_TO_STYLE.get(s.lower(), s)


_SENT_SPLIT_RE = re.compile(r"(?<=[。．！!？?])\s*|\n+")


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(text or "") if s and s.strip()]


def sentences_numbered_1based(sentences: List[str]) -> str:
    # ✅ runner が sent_idx=1.. を要求するので 1始まりで番号付け
    return "\n".join([f"{i+1}: {s}" for i, s in enumerate(sentences)])


def build_style_hints_text() -> str:
    lines = []
    for k, v in STYLE_CATALOG.items():
        lines.append(f"- {k}: {v.get('llm_hint', '').strip()}")
    return "\n".join(lines)


def image_to_dataurl(path: str | Path, max_side: int = 900, quality: int = 75) -> str:
    path = str(path)
    try:
        from PIL import Image

        with Image.open(path) as im:
            im = im.convert("RGB")
            w, h = im.size
            scale = max(w, h) / float(max_side) if max(w, h) > max_side else 1.0
            if scale > 1.0:
                im = im.resize((int(w / scale), int(h / scale)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=quality, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        return f"data:image/{ext};base64,{b64}"


def extract_json(text: str) -> Dict[str, Any]:
    """
    モデル出力からJSONだけを抜き出して dict にする（フェンス等を吸収）
    """
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last != -1 and last > first:
        text = text[first : last + 1]
    return json.loads(text)


_PAT_REGION = re.compile(
    r"region_(\d{3})_(\d+)_([A-Za-z]+)\.(?:png|jpg|jpeg)$",
    re.IGNORECASE,
)


def list_region_images_for_slide(input_dir: str | Path, slide_str: str) -> List[Dict[str, str]]:
    imgs: List[Dict[str, str]] = []
    input_dir = str(input_dir)
    for p in sorted(glob(os.path.join(input_dir, f"region_{slide_str}_*.*"))):
        m = _PAT_REGION.search(pathlib.Path(p).name)
        if not m:
            continue
        s_str, rid, rtype = m.groups()
        if s_str != slide_str:
            continue
        imgs.append({"region_id": rid, "type": rtype, "path": p})
    return imgs


def resolve_lp_input_dir(paths: ProjectPaths) -> Path:
    # 1) run_all が作った snapshot があればこちらを優先
    if paths.lp_snapshot_dir.exists():
        return paths.lp_snapshot_dir
    # 2) paths が定義する公式 LP_output
    return paths.lp_dir


def _compress_regions_for_prompt(regions_json: Any) -> List[Dict[str, Any]]:
    """
    regions_json をプロンプトに載せるために必要フィールドだけに圧縮。
    - region_id: str（インデックスと整合するID/番号を想定）
    - type: str
    - coordinates: [x,y,w,h] or [x1,y1,x2,y2] そのまま（runner側が推測で解釈するのでOK）
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(regions_json, list):
        return out

    for r in regions_json:
        if not isinstance(r, dict):
            continue

        rid = r.get("region_id", r.get("id", r.get("idx", r.get("index"))))
        rtype = r.get("type", r.get("label", r.get("category")))
        coords = r.get("coordinates", r.get("bbox", r.get("box")))

        if rid is None:
            continue

        if not (isinstance(coords, list) and len(coords) >= 4):
            coords = [0, 0, 1, 1]

        out.append(
            {
                "region_id": str(rid),
                "type": str(rtype) if rtype is not None else "",
                "coordinates": coords,
            }
        )
    return out


# -----------------------------
# プロンプト（旧スキーマを維持しつつ情報量を増やす）
# -----------------------------
def build_system_message() -> str:
    style_hints = build_style_hints_text()
    return (
        "あなたは講義スライド編集の熟練アシスタントです。"
        "与えられた「全文・文分割リスト」「スライド内の全領域（id/type/座標）」「領域画像」から、"
        "各“文”ごとにアニメーションの要否を判定し、必要なら「どの領域に・どのスタイルを・なぜ」を決めてください。"
        "必ず守ること："
        "- 「1つの文につきアニメは最大1つ」（animate は各文で null か1つ）。"
        "- 不要なら animate=null。"
        f"- スタイルは次の候補のみ: {style_hints}（これ以外を出力してはいけない）。"
        "- 出力は純粋JSONのみ。余計な文章は禁止。"
        "- JSON構造は指定スキーマに厳密一致（timelineが主、再生順が一目で分かる）。"
        "- スライドの表紙に対してアニメーションは必要ない。"
    )


def build_user_message(
    slide_str: str,
    slide_image_path: Path,
    regions_json: List[Dict[str, Any]],
    region_imgs: List[Dict[str, str]],
    script_full: str,
    sentences: List[str],
) -> Dict[str, Any]:
    """
    旧スキーマ（sentences）を維持したまま、判断材料を増やすプロンプト。

    ✅ 重要修正（対処Aの本命）：
    - region画像の dataURL(base64) を user_text に埋め込むのをやめる
      （巨大トークン化の主因）
    - 画像は content の image_url として“添付”する
    """
    slide_img_url = image_to_dataurl(slide_image_path)

    # 文字（JSON）としては「region_id/type」だけを載せる（base64は禁止）
    region_list_for_text: List[Dict[str, Any]] = []
    for r in region_imgs:
        region_list_for_text.append(
            {
                "region_id": str(r["region_id"]),
                "type": str(r["type"]),
            }
        )

    compressed_regions = _compress_regions_for_prompt(regions_json)
    numbered = sentences_numbered_1based(sentences)
    style_hints = build_style_hints_text()

    user_text = f"""以下の入力に基づき、スライド内の全領域の対応付けとアニメーション計画を一括で行ってください。

[slide]
- slide: {slide_str}

[講義台本: 全文]
---FULL---
{script_full}
---END---

[講義台本: 文分割（sent_idx は 1始まり）]
{numbered}

[スタイル候補と説明]
{style_hints}

[スライド内の全領域（必要フィールドのみ）]
{json.dumps(compressed_regions, ensure_ascii=False)}

[領域画像（赤枠入り）]
- 領域画像は、このメッセージの後半に image として添付しています（text中にbase64は含めません）。
{json.dumps(region_list_for_text, ensure_ascii=False)}

[判断基準]
- どの領域にも適切でない場合、その文の animate は null。
- 同じ文で複数候補がある場合でも、教育効果が最も高い1つに絞る。
- 表紙/タイトルだけのスライドは、基本的に animate=null でよい。ただし，タイトルに重要な領域がある場合はその限りではない。

[備考]
- 添付している画像は **対応した領域が赤い枠線で描かれたスライド画像**と、**各領域の切り出し画像**です。
- アニメーションは教育的効果がある場合のみ。一つのスライドに対して適切な量のアニメーションを心がける。


[出力スキーマ（厳守）]
{{
  "slide": "{slide_str}",
  "sentences": [
    {{
      "sent_idx": 1,
      "text": "...",
      "animate": null | {{
        "region_id": 0,
        "style": "<上の候補のいずれかのみ>",
        "reason": "短い根拠",
        "params": {{ "duration_sec": 0.9 }}
      }}
    }}
  ]
}}
"""

    # content パーツ：スライド画像 + region画像群を「画像」として添付
    content: List[Dict[str, Any]] = [
        {"type": "input_text", "text": user_text},
        {"type": "input_image", "image_url": slide_img_url},
    ]

    # region画像を画像パーツで追加（必要なら簡単なラベルテキストも添付）
    for r in region_imgs:
        try:
            region_url = image_to_dataurl(r["path"])
        except Exception:
            # 画像化に失敗しても落とさない（ただしこのregionは添付されない）
            continue

        content.append({"type": "input_text", "text": f"[region_image] region_id={r['region_id']} type={r['type']}"})
        content.append({"type": "input_image", "image_url": region_url})

    return {"role": "user", "content": content}


def save_mapping_outputs(paths: ProjectPaths, slide_str: str, mapping: Dict[str, Any]) -> None:
    """
    旧仕様を維持：
    - slide_XXX_mappings.json に LLM出力を保存
    - slide_XXX_region_YY.json は animate（そのまま）を保存（従来どおり）
    """
    out_dir = paths.animation_output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # ★ 文数を埋めておく（従来互換）
    sentences = mapping.get("sentences") or []
    mapping["num_sentences"] = len(sentences)

    # スライド全体のマッピング JSON
    slide_map_path = out_dir / f"slide_{slide_str}_mappings.json"
    with open(slide_map_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    # region単位JSONも分割保存（従来どおり）
    for s in mapping.get("sentences", []):
        anim = s.get("animate")
        if anim and isinstance(anim, dict):
            # region_id は runner が int 化するので、ここでも int 化できる形を想定
            try:
                rid = int(anim.get("region_id", -1))
            except Exception:
                continue
            if rid >= 0:
                region_path = out_dir / f"slide_{slide_str}_region_{rid:02d}.json"
                with open(region_path, "w", encoding="utf-8") as rf:
                    json.dump(anim, rf, ensure_ascii=False, indent=2)


def run_animation_assignment(client: OpenAI, paths: ProjectPaths, explanations: List[str]) -> None:
    """
    Step2:
      explanations（スライドごとの講義全文）と LP_output から
      slide_XXX_mappings.json を生成する。
    """
    system_msg = build_responses_system_message(build_system_message())

    lp_input_dir = resolve_lp_input_dir(paths)
    slide_imgs = sorted([p for p in paths.img_root.glob("*.png")])

    if not slide_imgs:
        raise RuntimeError(f"No slide images found under {paths.img_root}")

    for sidx0, slide_path in enumerate(slide_imgs):
        slide_str = f"{sidx0 + 1:03d}"

        script_full = explanations[sidx0] if sidx0 < len(explanations) else ""
        sentences = split_sentences(script_full)

        result_json_path = lp_input_dir / f"result_{slide_str}.json"
        if not result_json_path.exists():
            print(f"⚠ result not found. skip slide {slide_str}: {result_json_path}")
            continue

        with open(result_json_path, "r", encoding="utf-8") as f:
            regions_json = json.load(f)

        region_imgs = list_region_images_for_slide(lp_input_dir, slide_str)

        user_msg = build_user_message(
            slide_str=slide_str,
            slide_image_path=slide_path,
            regions_json=regions_json,
            region_imgs=region_imgs,
            script_full=script_full,
            sentences=sentences,
        )

        messages = [system_msg, user_msg]

        _resp, out_text = call_responses_text(
            client,
            modelname=API_MODEL_ANIMATION,
            messages=messages,
        )
        out_text = out_text or "{}"

        try:
            mapping = extract_json(out_text)
        except Exception as e:
            print(f"❌ JSON parse error on slide {slide_str}: {e}")
            print(out_text)
            continue

        # -------- 正規化（旧仕様維持）--------
        # slide は必ず文字列 "001" 形式に
        mapping["slide"] = str(mapping.get("slide", slide_str)).zfill(3)

        # sentences の形を最低限補強
        sents = mapping.get("sentences")
        if not isinstance(sents, list):
            sents = []
        fixed: List[Dict[str, Any]] = []

        for i, s in enumerate(sents):
            if not isinstance(s, dict):
                continue
            sent_idx = s.get("sent_idx", i + 1)
            try:
                sent_idx = int(sent_idx)
            except Exception:
                sent_idx = i + 1

            text = s.get("text")
            if not isinstance(text, str) or not text.strip():
                # もし text が無い場合は、こちらの文分割結果から補う（落ちないように）
                if 0 <= (sent_idx - 1) < len(sentences):
                    text = sentences[sent_idx - 1]
                else:
                    text = ""

            animate = s.get("animate", None)
            if animate is not None and isinstance(animate, dict):
                animate["style"] = normalize_style_name(animate.get("style"))
                # region_id を int 化できる文字列/数値に寄せる（"00"などもOK）
                if "region_id" in animate:
                    try:
                        animate["region_id"] = int(str(animate["region_id"]))
                    except Exception:
                        # int化できない場合は無効化（runner互換のため）
                        animate = None

                # style が未知なら無効化（runner互換）
                st = animate.get("style")
                if st not in STYLE_CATALOG:
                    animate = None

            fixed.append(
                {
                    "sent_idx": sent_idx,
                    "text": text,
                    "animate": animate,
                }
            )

        # もし LLM が sentences を返さなかった場合でも、最低限の形を作る（全部 animate=null）
        if not fixed:
            fixed = [{"sent_idx": i + 1, "text": s, "animate": None} for i, s in enumerate(sentences)]

        mapping["sentences"] = fixed

        save_mapping_outputs(paths, slide_str, mapping)

        print(f"✅ saved mapping: slide_{slide_str}")
