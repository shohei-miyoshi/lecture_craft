# src/auto_lecture/style_axes.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple
import re

# =========================================================
# レベル軸（Level Axis）
# =========================================================

LEVEL_TEXTS: Dict[str, str] = {
    "L1": "入門: 小学生が聞いても雰囲気がわかるような内容とし，専門用語は用いない。身近な具体例やたとえ話だけで，興味を失わないようにやさしく説明する。",
    "L2": "基礎: 基礎概念を平易に説明し，比喩や具体例を多く用いる。専門用語の使用は最小限とし，使用する場合は丁寧に説明する。",
    "L3": "発展: 重要な内容であれば，基本的な専門用語や理論的・抽象的な説明を許容する。スライドの主題から大きく外れない範囲で，関連する応用例や周辺トピックを横方向に広げて紹介する。",
    # 追加したくなったらここに L6 などを生やす
}

# "L2": "ゼロ知識向け: 全く知識がない人を対象とし，理論的な説明は行わない。講義スライドが言おうとしている内容が，イメージとしてつかめる程度に直感的な説明を行う。",
# "L4": "学部専門: 情報系学部生を前提とし，基本的な専門用語はそのまま用いてよいが，要点が分かるように簡潔に補足する。",

# =========================================================
# 詳細度軸（Detail Axis）
# =========================================================

DETAIL_TEXTS: Dict[str, str] = {
    "D1": "要約的: スライドの要点のみを端的に述べる。不要な背景説明や寄り道は行わない。",
    "D2": "標準的: 要点に加えて，理解に必要な補足や短い具体例を適切に追加する。ただし冗長にはしない。",
    "D3": "精緻: 概念間の関係，背景となる考え方，直感的理解を助ける説明を含めて詳しく解説する。ただしスライドの主題から脱線しない。",
    # D4 などを追加する場合はこちらに
}


# =========================================================
# 内部ユーティリティ
# =========================================================

def _natural_key(s: str) -> Tuple[str, int]:
    """
    'L1', 'L2', 'L10' のようなキーを自然順でソートするためのキー。
    """
    m = re.match(r"([A-Za-z]+)(\d+)$", s)
    if m:
        return (m.group(1), int(m.group(2)))
    return (s, 0)


def _list_valid_keys(mapping: Dict[str, str]) -> str:
    """
    'L1 / L2 / L3' のような表示用文字列を作る。
    """
    return " / ".join(sorted(mapping.keys(), key=_natural_key))


def _get_axis_value(name: str, key: str, mapping: Dict[str, str]) -> str:
    """
    軸 name (LEVEL / DETAIL) について、指定キー key の説明文を取得する。
    不正なキーの場合は ValueError を投げる。
    """
    if key not in mapping:
        valid = _list_valid_keys(mapping)
        raise ValueError(f"{name} の値が不正です: {key}（有効: {valid}）")
    return mapping[key]


# =========================================================
# 外部公開 API
# =========================================================

def resolve_level_detail(level: str, detail: str) -> tuple[str, str]:
    """
    LEVEL, DETAIL のキーから説明文を返すユーティリティ。

    Parameters
    ----------
    level : str
        'L1', 'L2', 'L3', ... のいずれか。
    detail : str
        'D1', 'D2', 'D3', ... のいずれか。

    Returns
    -------
    (level_desc, detail_desc) : tuple[str, str]
        各軸の説明文。
    """
    level_desc = _get_axis_value("LEVEL", level, LEVEL_TEXTS)
    detail_desc = _get_axis_value("DETAIL", detail, DETAIL_TEXTS)
    return level_desc, detail_desc
