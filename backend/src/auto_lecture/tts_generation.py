# src/auto_lecture/tts_generation.py
# ============================================
# TTS 音声生成モジュール
# - 入力 : スライドごとのナレーション文字列リスト（explanations[0..]）
# - 出力 : <tts_output_dir>/page{slide}/partXX.<fmt> 形式の音声ファイル
# - 旧セル7の処理を関数化＆run_all.py から呼べるようにラッパー追加
#
# ★追加:
#   TTS前に「読み上げに弱い記号」を音声向け表現に置換する前処理を実施
# ============================================

from __future__ import annotations

from pathlib import Path
from typing import List, Iterable
import re

from openai import OpenAI

# 設定値（config にあればそちらを優先し、無ければデフォルトを使う）
try:
    from .config import (  # type: ignore
        API_MODEL_TTS,
        TTS_VOICE,
        TTS_SPEED,
        TTS_FORMAT,
    )
except Exception:
    # config に定義されていない場合のデフォルト
    API_MODEL_TTS = "gpt-4o-mini-tts"
    TTS_VOICE = "alloy"
    TTS_SPEED = 1.0
    TTS_FORMAT = "mp3"

# OpenAI クライアントは gpt_client.py 経由のみ
try:
    from .gpt_client import get_client as get_openai_client  # type: ignore
except ImportError:
    try:
        from .gpt_client import create_client as get_openai_client  # type: ignore
    except ImportError:
        try:
            from .gpt_client import init_client as get_openai_client  # type: ignore
        except ImportError as e:
            raise ImportError(
                "gpt_client.py から OpenAI クライアントを返す関数 "
                "(get_client / create_client / init_client のいずれか) を "
                "export してください。"
            ) from e


# ============================================================
#  TTS 前処理（読み上げに弱い記号の置換）
# ============================================================

# 1) 単純置換（順序が大事なので list[tuple] で保持）
_SYMBOL_REPLACEMENTS: List[tuple[str, str]] = [
    # 比較・不等号
    ("＜", "小なり"),
    ("＞", "大なり"),

    ("≤", "小なりイコール"),
    ("≥", "大なりイコール"),
    ("≦", "小なりイコール"),
    ("≧", "大なりイコール"),
    ("≠", "ノットイコール"),
    ("≈", "ニアリーイコール"),
    ("≒", "ニアリーイコール"),
    ("=", "イコール"),

    # 矢印・対応
    ("→", "へ"),
    ("←", "から"),
    ("↔", "相互に"),
    ("⇒", "したがって"),
    ("⇔", "同値"),
    ("↓", "下向き"),
    ("↑", "上向き"),

    # 数学記号
    ("±", "プラスマイナス"),
    ("∓", "マイナスプラス"),
    ("×", "かける"),
    ("÷", "わる"),
    ("!", "の階乗"),
    ("∞", "無限大"),
    ("√", "ルート"),

    # 集合・論理
    # ("∈", "属する"),
    # ("⊂", "部分集合"),
    # ("⊆", "部分集合または等しい"),
    # ("∪", "和集合"),
    # ("∩", "共通部分"),
    # ("∀", "すべての"),
    # ("∃", "存在する"),
    # ("¬", "否定"),
    # ("∧", "かつ"),
    # ("∨", "または"),

    # 記号っぽい区切り（読み上げで詰まりやすい）
    # ("…", "、"),
    # ("・", "、"),
]

# 2) ギリシャ文字（よく出るものだけ）
_GREEK: List[tuple[str, str]] = [
    ("α", "アルファ"),
    ("β", "ベータ"),
    ("γ", "ガンマ"),
    ("δ", "デルタ"),
    ("ε", "イプシロン"),
    ("θ", "シータ"),
    ("λ", "ラムダ"),
    ("μ", "ミュー"),
    ("π", "パイ"),
    ("σ", "シグマ"),
    ("τ", "タウ"),
    ("φ", "ファイ"),
    ("ω", "オメガ"),
    ("Δ", "デルタ"),
    ("Σ", "シグマ"),
    ("Ω", "オメガ"),
]

# 3) 正規表現で処理したいもの
_RE_LATEX_INLINE = re.compile(r"\$(.+?)\$")
_RE_LATEX_CMD = re.compile(r"\\[a-zA-Z]+")  # \alpha 等
_RE_MULTI_SPACES = re.compile(r"[ \t]{2,}")
_RE_CODE_FENCE = re.compile(r"```.*?```", flags=re.DOTALL)
_RE_MD_BULLET = re.compile(r"^\s*[-*]\s+", flags=re.MULTILINE)

# よく出る「比較演算子」や「スラッシュ」等
# ※ "=" をすでに置換しているので、"==" を先に処理したい場合はここで対応
_RE_SPECIAL_TOKENS: List[tuple[re.Pattern, str]] = [
    (re.compile(r"=="), "イコールイコール"),
    (re.compile(r"!="), "ノットイコール"),
    (re.compile(r">="), "以上"),
    (re.compile(r"<="), "以下"),
    (re.compile(r"\bOR\b", flags=re.IGNORECASE), "または"),
    (re.compile(r"\bAND\b", flags=re.IGNORECASE), "かつ"),
    (re.compile(r"/"), "スラッシュ"),
]


def normalize_for_tts(text: str) -> str:
    """
    TTS 前に、読み上げが難しい記号・表記を音声向けに正規化する。

    方針:
    - 変換不能そうな記号は「消す」より「置換」優先
    - Markdown/コードフェンスは極力除去（読ませても意味が薄い）
    - 空白や改行の過剰は整形
    """
    if not text:
        return ""

    t = str(text)

    # コードブロックは読み上げに向かないので削除（必要なら後で方針変更可）
    t = _RE_CODE_FENCE.sub("", t)

    # Markdown 箇条書きの "- " や "* " を消す（読み上げで「ハイフン」と言いがち）
    t = _RE_MD_BULLET.sub("", t)

    # LaTeX インライン $...$ は中身だけ残す
    t = _RE_LATEX_INLINE.sub(r"\1", t)

    # LaTeX コマンド \alpha などはバックスラッシュ付きが残ると詰まるので消す
    # ただし \alpha は残したい場合もあるので、まずは単純に削除
    t = _RE_LATEX_CMD.sub("", t)

    # よくある特殊トークン（==, != など）を先に処理
    for pat, rep in _RE_SPECIAL_TOKENS:
        t = pat.sub(rep, t)

    # ギリシャ文字
    for src, rep in _GREEK:
        t = t.replace(src, rep)

    # 記号置換
    for src, rep in _SYMBOL_REPLACEMENTS:
        t = t.replace(src, rep)

    # 括弧類（読み上げに不要なら削る：中身は残す）
    # 例: (A) や [x] は中身だけ残す
    t = t.replace("（", " ")
    t = t.replace("）", " ")
    t = t.replace("(", " ")
    t = t.replace(")", " ")
    t = t.replace("【", " ")
    t = t.replace("】", " ")
    t = t.replace("[", " ")
    t = t.replace("]", " ")
    t = t.replace("{", " ")
    t = t.replace("}", " ")

    # 記号の連続や余計な空白を整形
    t = t.replace("\u00a0", " ")  # nbsp
    t = _RE_MULTI_SPACES.sub(" ", t)

    # 句読点が連続して不自然な場合を軽く整形
    t = re.sub(r"[、]{2,}", "、", t)
    t = re.sub(r"[。]{2,}", "。", t)

    # 行頭行末の空白
    t = "\n".join(line.strip() for line in t.splitlines())
    t = t.strip()

    return t


# ---------------- 文分割 ----------------

def _split_narration_to_sentences(narration_text: str) -> List[str]:
    """
    「。」で文を区切って、末尾に「。」を付け直す。
    空要素は除外する。

    ★注意:
    - TTS正規化は「文に分けた後」に各文へ適用する（理由: 句点分割精度を落とさないため）
    """
    sentences = [s.strip() for s in narration_text.split("。") if s.strip()]
    return [s + "。" for s in sentences]


# ---------------- 1スライド分 TTS ----------------

def narration_to_tts_one_slide(
    client: OpenAI,
    narration_text: str,
    slide_index: int,
    base_dir: str | Path,
    model: str,
    voice: str,
    speed: float = 1.0,
    fmt: str = "mp3",
) -> List[Path]:
    """
    1スライド分のナレーションを「。」ごとに区切って TTS 音声を生成する。
    """
    base_dir = Path(base_dir)
    out_dir = base_dir / f"page{slide_index}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sentences = _split_narration_to_sentences(narration_text)
    out_paths: List[Path] = []

    for idx, sentence in enumerate(sentences, start=1):
        # ★ここで TTS 正規化（記号置換）
        sentence_tts = normalize_for_tts(sentence)

        # 正規化の結果が空になったらスキップ（空音声を作らない）
        if not sentence_tts.strip():
            print(f"⚠ スライド{slide_index} 文{idx}: 正規化後が空のためスキップ")
            continue

        file_path = out_dir / f"part{idx:02}.{fmt}"
        print(f"▶ スライド{slide_index} 文{idx}: {sentence_tts}")

        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=sentence_tts,
            response_format=fmt,
            speed=speed,
        ) as response:
            response.stream_to_file(file_path)

        print(f"   保存完了: {file_path}")
        out_paths.append(file_path)

    return out_paths


# ---------------- 複数スライド分 TTS ----------------

def generate_tts_for_explanations(
    client: OpenAI,
    explanations: Iterable[str],
    base_dir: str | Path,
    model: str,
    voice: str,
    speed: float = 1.0,
    fmt: str = "mp3",
) -> List[Path]:
    """
    複数スライド分の explanations 全体に対して TTS 音声を生成する。
    """
    all_paths: List[Path] = []

    for i, narration_text in enumerate(explanations, start=1):
        slide_paths = narration_to_tts_one_slide(
            client=client,
            narration_text=narration_text,
            slide_index=i,
            base_dir=base_dir,
            model=model,
            voice=voice,
            speed=speed,
            fmt=fmt,
        )
        all_paths.extend(slide_paths)

    print(f"\n✅ TTS 完了: 合計 {len(all_paths)} ファイル生成")
    return all_paths


# ---------------- run_all.py から呼ぶラッパー ----------------

def run_tts_generation(
    paths,
    explanations: Iterable[str],
    model: str | None = None,
    voice: str | None = None,
    speed: float | None = None,
    fmt: str | None = None,
) -> List[Path]:
    """
    run_all.py の Step3 から呼び出すためのラッパー関数。
    """
    if explanations is None:
        print("[tts_generation] explanations が None なので何もしません。")
        return []

    client = get_openai_client()

    use_model = model or API_MODEL_TTS
    use_voice = voice or TTS_VOICE
    use_speed = speed if speed is not None else TTS_SPEED
    use_fmt = fmt or TTS_FORMAT

    base_dir = Path(paths.tts_output_dir)

    print(
        f"[tts_generation] TTS開始: model={use_model}, voice={use_voice}, "
        f"speed={use_speed}, fmt={use_fmt}, out={base_dir}"
    )

    return generate_tts_for_explanations(
        client=client,
        explanations=explanations,
        base_dir=base_dir,
        model=use_model,
        voice=use_voice,
        speed=use_speed,
        fmt=use_fmt,
    )
