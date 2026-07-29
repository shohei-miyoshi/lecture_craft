# src/auto_lecture/lecture_concat.py
# -*- coding: utf-8 -*-
"""
文→スライド→講義 連結（安定・軽量・ズレなし・無音対策 / Windowsのcp932例外対策込み）

✅ 修正内容（今回のバグ原因への対処）
- ffmpeg concat(filter) が落ちる根本原因：
    「入力クリップの解像度が一致していない（例: 1500x1124 と 1500x1126 が混在）」
  → concat フィルタは解像度/SARが一致しないと Invalid argument で失敗する。

- 対策：
    1) 各スライド内の sentence_files を ffprobe で調べ、
       そのスライド内での「最大W/H（偶数）」に全入力を強制スケールして統一してから concat。
    2) 講義全体結合（slide_final + gap）でも同様に最大W/Hに統一してから concat。
    3) SAR は setsar=1 で統一（プレーン側に変なSARが出ても潰す）

これにより、あなたのログで出ていた
  size 1500x1124 != 1500x1126
の混在でも確実に結合できます。
"""

from __future__ import annotations

from pathlib import Path
import re
import json
import gc
import os
import subprocess
import contextlib
import shutil
from typing import Optional, List, Tuple, Dict, Any

from .paths import ProjectPaths

# ---------------------------------------------------------
# グローバルに使うパス変数（外部からセットする）
# ---------------------------------------------------------
OUT_ANIM: Path
MAPS: Path
SLIDE_IMG_DIR: Path
AUDIO_ROOT: Path
FINAL_OUT: Path

# ---------------------------------------------------------
# 環境設定
# ---------------------------------------------------------
os.environ.setdefault("PYTHONUTF8", "1")

# ffmpeg の場所（任意・Windows安定化）
try:
    import imageio_ffmpeg

    os.environ.setdefault("IMAGEIO_FFMPEG_EXE", imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    pass

FFMPEG = os.environ.get("IMAGEIO_FFMPEG_EXE", "ffmpeg")
FFPROBE = "ffprobe"

# ★ 偶数サイズにそろえるためのスケールフィルタ（汎用）
FFMPEG_SCALE_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"

# ---------- 基本パラメータ ----------
FPS: int = 30
FALLBACK_SENT_DURATION: float = 2.0
SLIDE_GAP_SECONDS: float = 1.0
SAVE_GENERATED_PLAIN: bool = False
VIDEO_CRF: int = 20
VIDEO_PRESET: str = "veryfast"
AUDIO_BITRATE: str = "192k"  # 最終出力のビットレート（中間は素材準拠）

# ---------------------------------------------------------
# パスを外部から設定するヘルパー
# ---------------------------------------------------------
def set_paths(
    add_animation_output_dir: str | Path,
    animation_output_dir: str | Path,
    img_root: str | Path,
    tts_output_dir: str | Path,
    lecture_outputs_final: str | Path,
) -> None:
    """
    ProjectPaths などから渡されたパスを内部用グローバルにセット。
    """
    global OUT_ANIM, MAPS, SLIDE_IMG_DIR, AUDIO_ROOT, FINAL_OUT

    OUT_ANIM = Path(add_animation_output_dir)
    MAPS = Path(animation_output_dir)
    SLIDE_IMG_DIR = Path(img_root)
    AUDIO_ROOT = Path(tts_output_dir)
    FINAL_OUT = Path(lecture_outputs_final)
    FINAL_OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------
# 文字列デコードの安全関数
# ---------------------------------------------------------
def _decode_bytes(b: bytes) -> str:
    if b is None:
        return ""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return b.decode("cp932")
        except UnicodeDecodeError:
            return b.decode("utf-8", errors="replace")


# ---------- 小物 ----------
def _run(args: list) -> subprocess.CompletedProcess:
    """
    ffmpeg/ffprobe 実行。成功時は静穏化（stdout捨て、stderrだけ確保）。
    失敗時は stderr を人間可読の str にデコードして例外に載せる。
    """
    args = [str(a) for a in args]
    proc = subprocess.run(
        args,
        shell=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=False,  # ★ バイナリで受ける（cp932例外回避）
    )
    if proc.returncode != 0:
        stderr = _decode_bytes(proc.stderr)
        raise subprocess.CalledProcessError(proc.returncode, proc.args, output=b"", stderr=stderr)
    return proc


def _write_concat_list(list_path: Path, files: List[Path]) -> Path:
    list_path = Path(list_path)
    list_path.parent.mkdir(parents=True, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")
    return list_path.resolve()


def _has_audio_stream(path: Path) -> bool:
    """そのMP4に音声ストリームがあるかを ffprobe で判定（安全なバイナリ読み）"""
    try:
        r = subprocess.run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            shell=False,
            capture_output=True,
            text=False,  # ★ バイナリ
        )
        if r.returncode != 0:
            # 失敗時は「ある」と仮定して無駄な再エンコード回避
            return True
        return r.stdout is not None and r.stdout.strip() != b""
    except Exception:
        return True


def _ensure_audio_stream(in_path: Path) -> Path:
    """
    入力MP4に音声が無ければ、anullsrc を合成してステレオAACを付与した一時ファイルを返す。
    既に音声がある場合はそのまま in_path を返す。
    """
    in_path = Path(in_path).resolve()
    if _has_audio_stream(in_path):
        return in_path

    tmp = in_path.with_name(in_path.stem + "_aud.mp4")
    # anullsrc は“無限”でも -shortest があるので映像長に合わせて終了する
    args = [
        FFMPEG,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-i",
        str(in_path),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        _run(args)
        return tmp
    except subprocess.CalledProcessError as e:
        print("  ⚠ ensure-audio failed; use original:", in_path.name)
        print(e.stderr)
        return in_path


# ---------------------------------------------------------
# ✅ ffprobe で動画の W/H を取る（concat前の統一用）
# ---------------------------------------------------------
def _probe_video_wh(path: Path) -> Optional[Tuple[int, int]]:
    """
    ffprobeで最初の video stream の width/height を取得。
    取得できなければ None。
    """
    p = Path(path).resolve()
    if not p.exists():
        return None
    try:
        r = subprocess.run(
            [
                FFPROBE,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(p),
            ],
            shell=False,
            capture_output=True,
            text=False,  # バイナリ
        )
        if r.returncode != 0 or not r.stdout:
            return None
        data = json.loads(_decode_bytes(r.stdout))
        streams = data.get("streams", [])
        if not streams:
            return None
        w = int(streams[0].get("width", 0) or 0)
        h = int(streams[0].get("height", 0) or 0)
        if w <= 0 or h <= 0:
            return None
        return (w, h)
    except Exception:
        return None


def _even(n: int) -> int:
    """偶数へ切り上げ（yuv420p等の安全用）"""
    if n <= 0:
        return 0
    return n if (n % 2 == 0) else (n + 1)


def _pick_target_wh(files: List[Path]) -> Optional[Tuple[int, int]]:
    """
    クリップ群から最大W/Hを取り、偶数化したターゲットサイズを返す。
    """
    max_w = 0
    max_h = 0
    for f in files:
        wh = _probe_video_wh(f)
        if not wh:
            continue
        w, h = wh
        if w > max_w:
            max_w = w
        if h > max_h:
            max_h = h
    if max_w <= 0 or max_h <= 0:
        return None
    return (_even(max_w), _even(max_h))


# ---------- I/O ユーティリティ ----------
def _load_mapping(slide_str: str) -> dict:
    p = MAPS / f"slide_{slide_str}_mappings.json"
    if not p.exists():
        raise FileNotFoundError(f"Mapping not found: {p}")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_num_sentences(slide_str: str) -> int:
    data = _load_mapping(slide_str)

    n = int(data.get("num_sentences", 0) or 0)
    if n <= 0 and isinstance(data.get("sentences"), list):
        n = len(data["sentences"])
    return n


def _slide_png_path(slide_str: str) -> Path:
    p = SLIDE_IMG_DIR / f"{slide_str}.png"
    if not p.exists():
        raise FileNotFoundError(f"Slide image not found: {p}")
    return p.resolve()


def _audio_path_for_sentence(slide_str: str, sidx_zero: int) -> Optional[Path]:
    """
    TTS 出力は part01, part02, ... の 1 始まりなので、
    sidx_zero(0始まり) から +1 して対応させる。
    """
    page_dir = AUDIO_ROOT / f"page{int(slide_str)}"
    for ext in (".mp3", ".wav", ".m4a", ".ogg"):
        p = page_dir / f"part{sidx_zero + 1:02}{ext}"
        if p.exists():
            return p.resolve()
    return None


def _find_best_animated_clip(slide_str: str, sidx_zero: int) -> Optional[Path]:
    """
    既に生成済みのアニメ付きクリップ（mp4）を検索。
    同一文で複数がある場合は“更新日時が最新”を採用（名前順より安全）。

    ★ add_animation_runner_from_mapping.py 側は
      slide_{slide_str}_sent{index:02}_*.mp4 という 1 始まりの index を使うので、
      ここでも sidx_zero に +1 して 1 始まりに合わせる。
    """
    sent_idx_one = sidx_zero + 1
    pattern = f"slide_{slide_str}_sent{sent_idx_one:02}_*.mp4"
    cands = list(OUT_ANIM.glob(pattern))
    if not cands:
        return None
    cands.sort(key=lambda p: p.stat().st_mtime)
    return cands[-1].resolve()


# ---------- アニメなし文：静止画＋音声（極力シンプル / 偶数スケール付き） ----------
def _plain_sentence_video(
    image_path: Path,
    output_path: Path,
    audio_path: Optional[Path] = None,
    fps: int = FPS,
    crf: int = VIDEO_CRF,
    preset: str = VIDEO_PRESET,
    fallback_duration: float = FALLBACK_SENT_DURATION,
) -> Path:
    """
    音声あり:  -loop 1 で画像ループ + 音声、-shortest（-t 不使用）で終了を音声に合わせる
    音声なし:  anullsrc + -t <fallback> で無音クリップ
    途中で resample/フィルタは使わない（素材に従う）
    ★ 画像は scale=trunc(iw/2)*2:trunc(ih/2)*2 で偶数サイズに揃える
    """
    img = Path(image_path).resolve()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    aud = Path(audio_path).resolve() if audio_path else None

    if not img.exists():
        raise FileNotFoundError(f"Image not found: {img}")
    if aud and not aud.exists():
        raise FileNotFoundError(f"Audio not found: {aud}")

    if aud:
        _run(
            [
                FFMPEG,
                "-y",
                "-nostdin",
                "-hide_banner",
                "-loop",
                "1",
                "-i",
                str(img),  # #0: 画像
                "-i",
                str(aud),  # #1: 音声
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-shortest",
                "-vf",
                f"{FFMPEG_SCALE_EVEN},setsar=1",  # ★ 偶数 + SAR統一
                "-r",
                str(int(fps)),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-tune",
                "stillimage",
                "-crf",
                str(int(crf)),
                "-preset",
                str(preset),
                "-c:a",
                "aac",
                "-b:a",
                AUDIO_BITRATE,
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
    else:
        dur = max(0.2, float(fallback_duration))
        _run(
            [
                FFMPEG,
                "-y",
                "-nostdin",
                "-hide_banner",
                "-loop",
                "1",
                "-t",
                f"{dur:.3f}",
                "-i",
                str(img),  # #0: 画像
                "-f",
                "lavfi",
                "-t",
                f"{dur:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",  # #1: 無音
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-vf",
                f"{FFMPEG_SCALE_EVEN},setsar=1",  # ★ 偶数 + SAR統一
                "-r",
                str(int(fps)),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-tune",
                "stillimage",
                "-crf",
                str(int(crf)),
                "-preset",
                str(preset),
                "-c:a",
                "aac",
                "-b:a",
                AUDIO_BITRATE,
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
    return out


# ---------- スライド完成（文→連結） ----------
def build_final_video_for_slide(slide_str: str) -> Optional[Path]:
    slide_str = f"{int(slide_str):03d}"
    n_sent = _get_num_sentences(slide_str)
    if n_sent <= 0:
        print(f"⚠ slide {slide_str}: sentences=0")
        return None

    print(f"===== Processing slide {slide_str} =====")
    slide_png = _slide_png_path(slide_str)

    out_path = (FINAL_OUT / f"slide_{slide_str}_final.mp4").resolve()
    tmp_dir = (FINAL_OUT / f"__tmp_slide_{slide_str}").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    sentence_files: List[Path] = []

    # 文ごとの素材（アニメ or プレーン）をそろえる
    for sidx in range(n_sent):
        sidx_one = sidx + 1
        aud = _audio_path_for_sentence(slide_str, sidx)
        print(f"▶ slide {slide_str} / sentence {sidx_one:02} / audio={'yes' if aud else 'no'}")

        # ★ 1 始まりに揃えたアニメ付きクリップ探索
        anim = _find_best_animated_clip(slide_str, sidx)
        if anim and anim.exists():
            # 既存のアニメ付きクリップを採用（ただし“必ず音声付き”に補強）
            with_audio = _ensure_audio_stream(anim)
            sentence_files.append(with_audio)
            continue

        # アニメなし → 静止画 + 音声 を最小構成で生成（この時点で必ず音声が付く）
        try:
            out_mp4 = (
                (OUT_ANIM if SAVE_GENERATED_PLAIN else tmp_dir)
                / f"slide_{slide_str}_sent{sidx_one:02}_plain.mp4"
            )
            out_mp4 = out_mp4.resolve()
            _plain_sentence_video(
                image_path=slide_png,
                output_path=out_mp4,
                audio_path=aud,
                fps=FPS,
                crf=VIDEO_CRF,
                preset=VIDEO_PRESET,
                fallback_duration=FALLBACK_SENT_DURATION,
            )
            sentence_files.append(out_mp4)
        except subprocess.CalledProcessError as e:
            print(f"  ❗ plain generation failed at sent {sidx_one:02}")
            print("  ---- ffmpeg stderr ----\n", e.stderr)
            continue

    if not sentence_files:
        print(f"✅ 完了: 0 ファイル生成（slide {slide_str}）")
        return None

    # ✅ スライド内でのターゲット解像度（最大W/H）を決めて統一する
    target = _pick_target_wh(sentence_files)
    if target is None:
        # 最悪、従来通り（ただし失敗しやすい）
        target_w, target_h = 0, 0
    else:
        target_w, target_h = target
    if target_w and target_h:
        print(f"[concat] slide {slide_str} target size = {target_w}x{target_h}")

    # --- concat フィルタで結合 ---
    args: List[str] = [FFMPEG, "-y", "-nostdin", "-hide_banner"]
    for p in sentence_files:
        args += ["-i", str(p)]

    n = len(sentence_files)
    vf_parts: List[str] = []
    af_parts: List[str] = []

    # ✅ ここが今回の本丸：全入力を同じサイズ＆SARに正規化して concat
    for i in range(n):
        if target_w and target_h:
            vf_parts.append(
                f"[{i}:v]scale={target_w}:{target_h},setsar=1,fps={FPS},format=yuv420p[v{i}]"
            )
        else:
            # フォールバック（従来）
            vf_parts.append(f"[{i}:v]fps={FPS},format=yuv420p[v{i}]")

        # 音声は aresample で timestamp を揃える（必要なら aformat も足せる）
        af_parts.append(f"[{i}:a]aresample=async=1:first_pts=0[a{i}]")

    concat_in = "".join([f"[v{i}][a{i}]" for i in range(n)])
    filter_complex = ";".join(
        vf_parts + af_parts + [f"{concat_in}concat=n={n}:v=1:a=1[v][a]"]
    )

    args += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-crf",
        str(VIDEO_CRF),
        "-preset",
        VIDEO_PRESET,
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        str(out_path),
    ]

    try:
        gc.collect()
        _run(args)
    except subprocess.CalledProcessError as e:
        print("❗ slide concat(filter) failed")
        print("---- ffmpeg stderr ----\n", e.stderr)
        return None

    # 一時のプレーン + 途中で作成した “音声付け直し” を削除
    if not SAVE_GENERATED_PLAIN:
        for p in sentence_files:
            if (tmp_dir in Path(p).parents) or str(p.name).endswith("_aud.mp4"):
                with contextlib.suppress(Exception):
                    Path(p).unlink()
        with contextlib.suppress(Exception):
            tmp_dir.rmdir()

    print(f"✅ slide {slide_str} final saved: {out_path}")
    return out_path


# ---------- スライド間ギャップ（無音 / 偶数スケール付き） ----------
def _build_gap_clip_for_slide(slide_str: str, duration: float) -> Path:
    gap_dir = (FINAL_OUT / "__gap").resolve()
    gap_dir.mkdir(parents=True, exist_ok=True)
    out_p = (gap_dir / f"gap_{slide_str}_{int(duration * 1000)}ms.mp4").resolve()
    if out_p.exists():
        return out_p
    slide_png = _slide_png_path(slide_str)
    _run(
        [
            FFMPEG,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loop",
            "1",
            "-t",
            f"{float(duration):.3f}",
            "-i",
            str(slide_png),
            "-f",
            "lavfi",
            "-t",
            f"{float(duration):.3f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            f"{FFMPEG_SCALE_EVEN},setsar=1",
            "-r",
            str(int(FPS)),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-tune",
            "stillimage",
            "-crf",
            str(int(VIDEO_CRF + 2)),
            "-preset",
            VIDEO_PRESET,
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-movflags",
            "+faststart",
            str(out_p),
        ]
    )
    return out_p


# ---------- 講義全体連結（concat フィルタ） ----------
def build_full_lecture_video(insert_gap_sec: float = SLIDE_GAP_SECONDS) -> Optional[Path]:
    # スライド順
    slide_ids: List[str] = []
    pat = re.compile(r"slide_(\d{3})_mappings\.json$")
    for mp in sorted(MAPS.glob("slide_*_mappings.json")):
        m = pat.search(mp.name)
        if m:
            slide_ids.append(m.group(1))
    if not slide_ids:
        print("⚠ No slide mappings found.")
        return None

    # 各スライド final を用意
    slide_final_paths: List[Path] = []
    for sid in slide_ids:
        p = (FINAL_OUT / f"slide_{sid}_final.mp4").resolve()
        if not p.exists():
            print(f"▶ building slide final {sid} ...")
            made = build_final_video_for_slide(sid)
            if not made:
                print(f"  ⚠ skip slide {sid}")
                continue
            p = made
        p_with_aud = _ensure_audio_stream(p)
        if p_with_aud != p:
            try:
                backup = p.with_suffix(".bak.mp4")
                with contextlib.suppress(Exception):
                    if backup.exists():
                        backup.unlink()
                shutil.move(str(p), str(backup))
                shutil.move(str(p_with_aud), str(p))
                with contextlib.suppress(Exception):
                    backup.unlink()
            except Exception:
                p = p_with_aud
        slide_final_paths.append(p.resolve())

    if not slide_final_paths:
        print("⚠ No slide finals to concatenate.")
        return None

    # 必要に応じてギャップを挟んだリストを作る
    concat_items: List[Path] = []
    for i, p in enumerate(slide_final_paths):
        concat_items.append(p)
        if (i < len(slide_final_paths) - 1) and (insert_gap_sec > 0):
            gap_mp4 = _build_gap_clip_for_slide(slide_ids[i], float(insert_gap_sec))
            concat_items.append(gap_mp4)

    # ✅ 講義全体でもターゲット解像度（最大W/H）に統一してから concat
    target = _pick_target_wh(concat_items)
    if target is None:
        target_w, target_h = 0, 0
    else:
        target_w, target_h = target
    if target_w and target_h:
        print(f"[concat] lecture target size = {target_w}x{target_h}")

    # concat フィルタ
    args: List[str] = [FFMPEG, "-y", "-nostdin", "-hide_banner"]
    for p in concat_items:
        args += ["-i", str(p)]

    n = len(concat_items)
    vf_parts: List[str] = []
    af_parts: List[str] = []
    for i in range(n):
        if target_w and target_h:
            vf_parts.append(
                f"[{i}:v]scale={target_w}:{target_h},setsar=1,fps={FPS},format=yuv420p[v{i}]"
            )
        else:
            vf_parts.append(f"[{i}:v]fps={FPS},format=yuv420p[v{i}]")

        af_parts.append(f"[{i}:a]aresample=async=1:first_pts=0[a{i}]")

    concat_in = "".join([f"[v{i}][a{i}]" for i in range(n)])
    filter_complex = ";".join(
        vf_parts + af_parts + [f"{concat_in}concat=n={n}:v=1:a=1[v][a]"]
    )

    out_path = (FINAL_OUT / "lecture_final.mp4").resolve()
    args += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-crf",
        str(VIDEO_CRF),
        "-preset",
        VIDEO_PRESET,
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-movflags",
        "+faststart",
        str(out_path),
    ]

    try:
        gc.collect()
        _run(args)
    except subprocess.CalledProcessError as e:
        print("❗ lecture concat(filter) failed")
        print("---- ffmpeg stderr ----\n", e.stderr)
        return None

    print(f"🎬 Lecture done: {out_path}")
    return out_path


# ---------------------------------------------------------
# 1発で「パス設定＋講義全体生成」するラッパー
# ---------------------------------------------------------
def build_full_lecture_video_with_paths(
    add_animation_output_dir: str | Path,
    animation_output_dir: str | Path,
    img_root: str | Path,
    tts_output_dir: str | Path,
    lecture_outputs_final: str | Path,
    insert_gap_sec: float = SLIDE_GAP_SECONDS,
) -> Optional[Path]:
    set_paths(
        add_animation_output_dir,
        animation_output_dir,
        img_root,
        tts_output_dir,
        lecture_outputs_final,
    )
    return build_full_lecture_video(insert_gap_sec=insert_gap_sec)


# ---------------------------------------------------------
# run_all.py から呼ぶラッパー
# ---------------------------------------------------------
def run_concat(paths: ProjectPaths, insert_gap_sec: float = SLIDE_GAP_SECONDS) -> Optional[Path]:
    """
    フルパイプライン Step5 用のラッパー。
    """
    return build_full_lecture_video_with_paths(
        add_animation_output_dir=paths.add_animation_output_dir,
        animation_output_dir=paths.animation_output_dir,
        img_root=paths.img_root,
        tts_output_dir=paths.tts_output_dir,
        lecture_outputs_final=paths.lecture_outputs_final,
        insert_gap_sec=insert_gap_sec,
    )


if __name__ == "__main__":
    print(
        "このスクリプトは通常 run_concat(paths) または\n"
        "build_full_lecture_video_with_paths(...) から呼び出して使います。"
    )
