from __future__ import annotations

import json
import os
import re
import math
from typing import Any, Dict, Iterable, Optional


PREFERENCE_PROMPT_VERSION = "cipher_lpi_lecturecraft_v1"
VALID_PREFERENCE_KINDS = {"preference", "content_correction", "local_instruction", "uncertain"}
VALID_PREFERENCE_SCOPES = {"user", "mode", "difficulty", "project", "one_time"}


def extract_text(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("text")
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalized_edit_distance(before: Any, after: Any) -> float:
    before_text = extract_text(before)
    after_text = extract_text(after)
    if not before_text and not after_text:
        return 0.0
    try:
        import tiktoken

        encoding = tiktoken.get_encoding("o200k_base")
        left = encoding.encode(before_text)
        right = encoding.encode(after_text)
    except Exception:
        left = list(before_text)
        right = list(after_text)
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_token in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[right_index] + 1,
                previous[right_index - 1] + (left_token != right_token),
            ))
        previous = current
    denominator = max(len(left), len(right), 1)
    return round(previous[-1] / denominator, 4)


def build_latent_preference_prompt(
    *,
    before: Any,
    after: Any,
    slide_context: Optional[Dict[str, Any]] = None,
) -> str:
    context = slide_context if isinstance(slide_context, dict) else {}
    return (
        "あなたは、講義台本に対するユーザ編集から潜在的な説明上の好みを推定します。\n"
        "元の台本と修正版を比較し、編集の種類と適用範囲を判定してください。"
        "事実訂正や今回だけの内容変更を恒久的な好みにしないでください。"
        "説明の詳しさ、難易度、構成、語調、例示、図表への言及などを検討してください。"
        "JSON以外は出力しないでください。\n\n"
        f"スライド文脈: {json.dumps(context, ensure_ascii=False)}\n"
        f"元の台本: {extract_text(before)}\n"
        f"ユーザ修正版: {extract_text(after)}\n\n"
        '出力形式: {"kind":"preference|content_correction|local_instruction|uncertain",'
        '"scope":"user|mode|difficulty|project|one_time",'
        '"preference":"再利用可能な好みなら短い一文、それ以外はnull","reason":"短い根拠"}'
    )


def build_preference_context_text(
    *,
    before: Any,
    slide_context: Optional[Dict[str, Any]] = None,
) -> str:
    context = slide_context if isinstance(slide_context, dict) else {}
    fields = [
        f"mode={context.get('mode') or 'unknown'}",
        f"difficulty={context.get('difficulty') or 'unknown'}",
        f"detail={context.get('detail') or 'unknown'}",
        f"usage_context={context.get('usage_context') or 'unknown'}",
        f"slide_idx={context.get('slide_idx')}",
        f"script={extract_text(before)}",
    ]
    return "\n".join(fields)


def create_context_embedding(context_text: str) -> Optional[list[float]]:
    if not str(context_text or "").strip():
        return None
    try:
        from auto_lecture.gpt_client import create_client

        response = create_client().embeddings.create(
            model=os.getenv("LECTURE_CRAFT_MODEL_EMBEDDING", "text-embedding-3-small"),
            input=context_text,
        )
        vector = response.data[0].embedding
        return [float(value) for value in vector]
    except Exception:
        return None


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    a = [float(value) for value in left]
    b = [float(value) for value in right]
    if not a or len(a) != len(b):
        return 0.0
    denominator = math.sqrt(sum(value * value for value in a)) * math.sqrt(sum(value * value for value in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else 0.0


def induce_preference_from_edit(
    *,
    before: Any,
    after: Any,
    slide_context: Optional[Dict[str, Any]] = None,
    applied_preference: Any = None,
    applied_preference_scope: Any = None,
) -> Dict[str, Any]:
    before_text = extract_text(before)
    after_text = extract_text(after)
    distance = normalized_edit_distance(before_text, after_text)
    threshold = max(0.0, float(os.getenv("LECTURE_CRAFT_PREFERENCE_EDIT_THRESHOLD", "0.03")))
    applied_text = extract_text(applied_preference)

    base = {
        "preference_text": None,
        "preference_source": "cipher_lpi_llm_v1",
        "preference_status": "skipped",
        "preference_error": None,
        "preference_reason": None,
        "edit_distance_ratio": distance,
        "prompt_version": PREFERENCE_PROMPT_VERSION,
        "preference_kind": "uncertain",
        "preference_scope": "one_time",
        "context_text": build_preference_context_text(before=before, slide_context=slide_context),
        "context_embedding": None,
    }
    if not before_text or not after_text or before_text == after_text:
        return base
    if distance <= threshold:
        if applied_text:
            applied_scope = str(applied_preference_scope or "user")
            if applied_scope not in VALID_PREFERENCE_SCOPES or applied_scope == "one_time":
                applied_scope = "user"
            return {
                **base,
                "preference_text": applied_text,
                "preference_source": "cipher_reused_v1",
                "preference_status": "reused",
                "preference_kind": "preference",
                "preference_scope": applied_scope,
            }
        return base

    prompt = build_latent_preference_prompt(
        before=before_text,
        after=after_text,
        slide_context=slide_context,
    )
    try:
        from auto_lecture import config as auto_config
        from auto_lecture.gpt_client import create_client
        from auto_lecture.gpt_utils import (
            build_responses_system_message,
            build_responses_user_message,
            call_responses_text,
        )

        client = create_client()
        _response, result = call_responses_text(
            client,
            modelname=os.getenv("LECTURE_CRAFT_MODEL_PREFERENCE", auto_config.API_MODEL_EXPLANATION),
            messages=[
                build_responses_system_message("ユーザ編集から一般化可能な潜在的好みだけを簡潔に推定してください。"),
                build_responses_user_message(prompt),
            ],
        )
        raw = str(result or "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        parsed = json.loads(raw[start:end + 1]) if start >= 0 and end > start else {}
        kind = str(parsed.get("kind") or "uncertain")
        scope = str(parsed.get("scope") or "one_time")
        if kind not in VALID_PREFERENCE_KINDS:
            kind = "uncertain"
        if scope not in VALID_PREFERENCE_SCOPES:
            scope = "one_time"
        preference = re.sub(r"\s+", " ", str(parsed.get("preference") or "")).strip()[:500] or None
        if kind != "preference":
            preference = None
        context_text = base["context_text"]
        return {
            **base,
            "preference_text": preference,
            "preference_status": "inferred" if preference else "not_reusable",
            "preference_kind": kind,
            "preference_scope": scope,
            "preference_reason": re.sub(r"\s+", " ", str(parsed.get("reason") or "")).strip()[:500] or None,
            "context_embedding": create_context_embedding(context_text),
        }
    except Exception as exc:
        return {
            **base,
            "preference_status": "failed",
            "preference_error": str(exc)[:500],
        }


def consolidate_preferences(preferences: Iterable[Dict[str, Any]]) -> Optional[str]:
    rows = [row for row in preferences if isinstance(row, dict) and row.get("preference")]
    if not rows:
        return None
    if len(rows) == 1:
        return str(rows[0]["preference"])
    lines = []
    for row in rows:
        lines.append(f"- {row['preference']}")
    prompt = (
        "以下は、類似する利用文脈から取得した過去のユーザ好みです。"
        "多数に共通する好みを優先し、矛盾や重複を除き、今回の台本生成に使う短い日本語の箇条書きへ統合してください。"
        "現在の教材条件に該当する好みだけを残してください。\n\n"
        + "\n".join(lines)
    )
    try:
        from auto_lecture import config as auto_config
        from auto_lecture.gpt_client import create_client
        from auto_lecture.gpt_utils import (
            build_responses_system_message,
            build_responses_user_message,
            call_responses_text,
        )

        _response, result = call_responses_text(
            create_client(),
            modelname=os.getenv("LECTURE_CRAFT_MODEL_PREFERENCE", auto_config.API_MODEL_EXPLANATION),
            messages=[
                build_responses_system_message("類似文脈から得たユーザ好みを、過度に一般化せず統合してください。"),
                build_responses_user_message(prompt),
            ],
        )
        return re.sub(r"\s+", " ", str(result or "")).strip()[:1500] or None
    except Exception:
        return None
