# src/auto_lecture/tts_simple.py
# -*- coding: utf-8 -*-
"""
指定されたテキストファイルを読み込み、
OpenAI TTS で音声化して保存する汎用モジュール。

特徴:
- 入力は「テキストファイルのパス」
- 出力先は paths.tts_output_dir の配下で、ファイル名は lecture_<mode>.mp3
- モード / 章構造などは一切持たず、テキスト全体を読み上げる

改良点（重要）:
- OpenAI TTS(/audio/speech) は input にトークン上限があるため、
  長文をそのまま渡すと 400 で落ちる。
  → 文単位で分割し、上限未満のチャンクにまとめて複数回TTSし、
    最後に ffmpeg で mp3 を結合して lecture_<mode>.mp3 を生成する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, List, Tuple
import os
import re
import shutil
import subprocess

from openai import OpenAI

from .gpt_client import create_client
from . import config
from .paths import ProjectPaths


# ============================================================
# 1) 台本クリーニング（Step3の思想を踏襲）
#    - BOM除去
#    - # ... / ===...=== / created at / # image: / image: を除去
#    - Windowsパスっぽい行を除去
# ============================================================

_WS_RE = re.compile(r"\s+")
_RE_WIN_PATH = re.compile(r"^[A-Za-z]:\\")
_RE_META_LINE = re.compile(r"^(#|image:|# image:|created at)", re.IGNORECASE)


def _should_drop_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    s = s.lstrip("\ufeff").strip()
    if not s:
        return True

    low = s.lower()

    # 例: === ... ===
    if low.startswith("===") and low.endswith("==="):
        return True

    # 例: "# image:" / "created at" / "# ..."
    if _RE_META_LINE.match(low):
        return True

    # 例: "C:\...." のようなパス行
    if _RE_WIN_PATH.match(s):
        return True

    return False


def clean_script_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    kept: List[str] = []
    for ln in lines:
        if _should_drop_line(ln):
            continue
        kept.append(_WS_RE.sub(" ", ln.strip()))
    return "\n".join(kept).strip()


# ============================================================
# 2) 読み上げ事故りやすい記号の置換
# ============================================================

_REPLACEMENTS: List[Tuple[str, str]] = [
    ("<", "小なり"),
    (">", "大なり"),
    ("≤", "小なりイコール"),
    ("≥", "大なりイコール"),
    ("≈", "ニアリーイコール"),
    ("≠", "ノットイコール"),
]


def normalize_for_tts(text: str) -> str:
    s = text or ""
    for a, b in _REPLACEMENTS:
        s = s.replace(a, b)
    s = _WS_RE.sub(" ", s).strip()
    return s


# ============================================================
# 3) 文分割（ゆるめ）
#    - 句点/終端記号で分割し、必要ならチャンクにまとめ直す
# ============================================================

_SENT_SPLIT_RE = re.compile(r"[。．\.!?！？]+")  # ゆるめ


def split_sentences(text: str) -> List[str]:
    text = clean_script_text(text)
    if not text:
        return []
    parts = _SENT_SPLIT_RE.split(text.strip())
    out: List[str] = []
    for p in parts:
        s = normalize_for_tts(p)
        if not s:
            continue
        out.append(s)
    return out


# ============================================================
# 4) token カウント（tiktoken があれば正確、無ければ推定）
# ============================================================

_RE_JP = re.compile(r"[\u3040-\u30FF\u4E00-\u9FFF]")  # ひら/カタ/漢字ざっくり


def _try_count_tokens_with_tiktoken(model: str, text: str) -> Optional[int]:
    try:
        import tiktoken  # type: ignore
    except Exception:
        return None

    try:
        enc = tiktoken.encoding_for_model(model)
    except Exception:
        # モデル名が未知でも安全側に
        try:
            enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            return None

    try:
        return len(enc.encode(text))
    except Exception:
        return None


def estimate_tokens(model: str, text: str) -> int:
    """
    tiktoken があれば正確にカウント。
    無ければ安全側推定。

    日本語が多い → 1文字≒1token 寄り
    英語寄り   → 3〜4文字≒1token 寄り（安全側に 3 を採用）
    """
    t = text or ""
    n = _try_count_tokens_with_tiktoken(model, t)
    if n is not None:
        return n

    total = len(t)
    if total <= 0:
        return 0

    jp = len(_RE_JP.findall(t))
    jp_ratio = jp / max(total, 1)

    if jp_ratio >= 0.2:
        return int(total * 1.0)  # 安全側（日本語は厳しめに）
    return int(total / 3.0) + 1  # 英語寄り


def chunk_by_token_limit(sentences: List[str], model: str, max_tokens: int) -> List[str]:
    """
    文リストを max_tokens 以下のチャンクにまとめる。
    1文だけで超える場合は文字数で強制分割。
    """
    chunks: List[str] = []
    buf: List[str] = []
    buf_tokens = 0

    for s in sentences:
        s2 = normalize_for_tts(s)
        if not s2:
            continue
        st = estimate_tokens(model, s2)

        # 1文が長すぎる → 強制分割
        if st > max_tokens:
            # token≒文字（日本語寄り想定）で安全側に刻む
            step = max(200, int(max_tokens * 0.8))
            for i in range(0, len(s2), step):
                part = s2[i : i + step].strip()
                if part:
                    chunks.append(part)
            buf, buf_tokens = [], 0
            continue

        if buf and (buf_tokens + st + 1) > max_tokens:
            chunks.append("。".join(buf).strip() + "。")
            buf, buf_tokens = [], 0

        buf.append(s2)
        buf_tokens += st + 1

    if buf:
        chunks.append("。".join(buf).strip() + "。")

    return chunks


# ============================================================
# 5) ffmpeg concat（mp3結合）
# ============================================================

def _which_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def concat_mp3_with_ffmpeg(parts: List[Path], out_path: Path) -> None:
    """
    ffmpeg concat demuxer で mp3 を結合する。
    """
    ffmpeg = _which_ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "[tts_simple] ffmpeg が見つかりません。"
            "分割音声(part_*.mp3)は生成済みなので、ffmpeg をインストールして再実行してください。"
        )

    # concat 用リストファイル（絶対パス。WindowsでもOK）
    list_file = out_path.parent / "_tts_concat_list.txt"
    lines = []
    for p in parts:
        # ffmpeg concat は file 'path' 形式
        # バックスラッシュはそのままでOKだが、念のため Path を文字列化してクォート
        lines.append(f"file '{str(p)}'")
    list_file.write_text("\n".join(lines), encoding="utf-8")

    # -safe 0: 絶対パス許可
    cmd = [
        ffmpeg,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out_path),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "[tts_simple] ffmpeg concat failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )

    # 後片付け（リストファイルだけ消す。partはデバッグのため残しても良いが、ここでは残す）
    try:
        list_file.unlink(missing_ok=True)  # type: ignore
    except Exception:
        pass


# ============================================================
# 6) メインAPI（I/Fは維持）
# ============================================================

def tts_from_textfile(
    text_file: Path,
    paths: ProjectPaths,
    mode: str,
    model: Optional[str] = None,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
    fmt: str = "mp3",
) -> Path:
    """
    任意のテキストファイルを読み込み、TTS で音声化して
    paths.tts_output_dir / lecture_<mode>.<fmt> に保存する。

    重要:
    - 長文は自動分割して複数回TTSし、最後に結合して1ファイルを返す。
    - 分割音声は paths.tts_output_dir / _parts_<mode>/part_XXX.<fmt> に残す（デバッグ用）。

    Returns
    -------
    Path
        保存された音声ファイルのパス。
        例: outputs/<教材>_日時/lecture_outputs/tts_outputs/lecture_detailed.mp3
    """
    text_file = Path(text_file)
    if not text_file.exists():
        raise FileNotFoundError(f"[tts_simple] テキストファイルが見つかりません: {text_file}")

    # 文字コードは utf-8 想定。ただし BOM 混入は除去する
    raw = text_file.read_text(encoding="utf-8", errors="strict")
    raw = clean_script_text(raw)

    if not raw:
        raise ValueError(f"[tts_simple] テキストファイルが空です（クリーニング後）: {text_file}")

    # --- TTS 設定（config.py に依存） ---
    use_model = model or config.API_TTS_MODEL
    use_voice = voice or config.API_TTS_VOICE
    use_speed = speed if speed is not None else config.API_TTS_VOICE_SPEED
    use_fmt = fmt

    # --- 2000上限対策（安全側） ---
    # OpenAI側の上限が将来変わっても、ここは余裕を持たせる
    max_input_tokens = getattr(config, "API_TTS_MAX_INPUT_TOKENS", 1800)

    # --- 出力パス: paths.tts_output_dir / lecture_<mode>.<fmt> ---
    tts_root = Path(paths.tts_output_dir)
    tts_root.mkdir(parents=True, exist_ok=True)
    out_path = tts_root / f"lecture_{mode}.{use_fmt}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 分割パーツ保存先
    parts_dir = tts_root / f"_parts_{mode}"
    parts_dir.mkdir(parents=True, exist_ok=True)

    print("[tts_simple] 音声生成開始")
    print(f"  入力テキスト : {text_file}")
    print(f"  出力先       : {out_path}")
    print(f"  パーツ出力   : {parts_dir}")
    print(f"  モデル       : {use_model}")
    print(f"  声           : {use_voice}")
    print(f"  話速         : {use_speed}")
    print(f"  フォーマット : {use_fmt}")
    print(f"  分割上限token : {max_input_tokens}")

    client: OpenAI = create_client()

    # 文分割 → チャンク化
    sentences = split_sentences(raw)
    if not sentences:
        # 念のため
        sentences = [normalize_for_tts(raw)]
    chunks = chunk_by_token_limit(sentences, use_model, max_input_tokens)

    print(f"[tts_simple] チャンク数: {len(chunks)}")

    part_paths: List[Path] = []

    # チャンクごとに TTS（再実行耐性: 既存partはスキップ）
    for i, chunk in enumerate(chunks):
        part_path = parts_dir / f"part_{i:03d}.{use_fmt}"
        part_paths.append(part_path)

        if part_path.exists() and part_path.stat().st_size > 0:
            print(f"[tts_simple] skip existing: {part_path.name}")
            continue

        # OpenAI TTS をストリーミングで実行し、そのままファイルへ保存
        # NOTE: あなたの既存コードに合わせて response_format を使う
        with client.audio.speech.with_streaming_response.create(
            model=use_model,
            voice=use_voice,
            input=chunk,
            response_format=use_fmt,
            speed=use_speed,
        ) as response:
            response.stream_to_file(part_path)

        print(f"[tts_simple] part done: {part_path.name}")

    # 1チャンクならそれを lecture_<mode>.mp3 としてコピー
    if len(part_paths) == 1:
        shutil.copyfile(part_paths[0], out_path)
        print(f"[tts_simple] 完了（単一チャンク）: {out_path}")
        return out_path

    # 複数チャンクなら ffmpeg で結合
    print("[tts_simple] mp3 結合開始（ffmpeg）")
    concat_mp3_with_ffmpeg(part_paths, out_path)
    print(f"[tts_simple] 完了: {out_path}")

    return out_path
