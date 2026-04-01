# src/auto_lecture/audio_only_style_axes.py
from __future__ import annotations

from dataclasses import dataclass

# ============================================================
#  音声のみ講義用のスタイル軸定義（Level / Detail）
#  - style_axes.py は動画用に専念させるため、こちらは audio_only 用に分離
# ============================================================

LEVEL_TEXTS: dict[str, str] = {
    "L1": "入門: 小学生が聞いても雰囲気がわかるような内容とし，専門用語は基本的に用いない。身近な具体例やたとえ話だけで，興味を失わないようにやさしく説明する。",
    # "L2": "ゼロ知識向け: 全く知識がない人を対象とし，理論的な説明は行わない。講義スライドが言おうとしている内容が，イメージとしてつかめる程度に直感的な説明を行う。",
    "L2": "基礎: 基礎概念を平易に説明し，比喩や具体例を多く用いる。専門用語の使用は最小限とし，使用する場合は丁寧に説明する。",
    # "L4": "学部専門: 情報系学部生を前提とし，基本的な専門用語はそのまま用いてよいが，要点が分かるように簡潔に補足する。",
    "L3": "発展: 重要な内容であれば，基本的な専門用語や理論的・抽象的な説明を許容する。スライドの主題から大きく外れない範囲で，関連する応用例や周辺トピックを横方向に広げて紹介する。",
    # "L1": "入門: 基礎概念を平易に説明し，比喩や具体例を多く用いる。専門用語の使用は最小限とし，使用する場合は丁寧に説明する。",
    # "L2": "学部専門: 情報系学部生を前提とし，基本的な専門用語はそのまま用いてよいが，要点が分かるように簡潔に補足する。",
    # "L3": "上級: 上級者・大学院生レベルを想定し，理論的・抽象的な説明を行うが，重要な式や概念には一言の直感的な説明を添える。",
    # "L4": "研究者: 研究者・専門家向け。専門用語・前提知識を前提に，数式・理論的背景・位置づけを中心に説明する。",
}

DETAIL_TEXTS: dict[str, str] = {
    "D1": "要約的: スライドの要点のみを端的に述べる。不要な背景説明や寄り道は行わない。",
    "D2": "標準的: 要点に加えて，理解に必要な補足や短い具体例を適切に追加する。ただし冗長にはしない。",
    "D3": "詳細: 概念間の関係，背景となる考え方，直感的理解を助ける説明を含めて詳しく解説する。ただしスライドの主題から脱線しない。",
    # "D1": "要約重視: 重要なポイントに絞り，全体像や直感的な理解を優先して説明する。細かい条件や例は必要最低限。",
    # "D2": "標準: 全体像と主要な細部のバランスを取り，講義として自然な分量で説明する。",
    # "D3": "詳細: 細かい条件・例・注意点も含めて丁寧に説明し，多少長くなっても理解の抜けを減らすことを優先する。",
}

# ============================================================
# 互換性のための別名（重要）
# - run_audio_only_lecture.py が import している名前に合わせる
# - 将来コードが混在しても ImportError で落ちないようにする
# ============================================================
LEVEL_TEXTS_AUDIO_ONLY = LEVEL_TEXTS
DETAIL_TEXTS_AUDIO_ONLY = DETAIL_TEXTS


@dataclass
class AudioOnlyStyle:
    level: str
    detail: str
    style_label: str
    level_text: str
    detail_text: str


def resolve_audio_only_style(level: str, detail: str) -> AudioOnlyStyle:
    """
    音声のみ講義のスタイル軸を解決する。

    - 不正な level/detail が来た場合は L3/D2 にフォールバックする。
    """
    norm_level = (level or "L3").upper()
    norm_detail = (detail or "D2").upper()

    if norm_level not in LEVEL_TEXTS:
        norm_level = "L3"
    if norm_detail not in DETAIL_TEXTS:
        norm_detail = "D2"

    style_label = f"{norm_level}{norm_detail}"
    level_text = LEVEL_TEXTS[norm_level]
    detail_text = DETAIL_TEXTS[norm_detail]

    return AudioOnlyStyle(
        level=norm_level,
        detail=norm_detail,
        style_label=style_label,
        level_text=level_text,
        detail_text=detail_text,
    )
