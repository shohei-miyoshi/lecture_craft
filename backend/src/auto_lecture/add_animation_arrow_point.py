# src/auto_lecture/add_animation_arrow_point.py
# ============================================
# 矢印フォーカスアニメーションモジュール
# - 矢印をフェードイン表示し、その後は最終フレームを静止で音声末まで保持
# - 静止区間は ffmpeg -loop 1 で超軽量生成
# - concat用 list.txt と入力パスを絶対パス指定して Windows の相対解決問題を回避
# - animate.params をそのまま config に渡せる想定：
#   例: {"duration_sec": 0.8, "color": "#00C8FF", "side": "auto_opposite"}
# ============================================

from __future__ import annotations

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List
import os
import math
import contextlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from moviepy.video.VideoClip import VideoClip
import moviepy.video.io.ffmpeg_writer as ffmpeg_writer
from moviepy.audio.io.AudioFileClip import AudioFileClip


__all__ = [
    "animate_arrow_point",
]


# ---------- 安全な ffmpeg 実行 ----------
def run_ffmpeg(args: list):
    args = [str(a) for a in args]
    proc = subprocess.run(args, shell=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (code={proc.returncode})\n"
            f"cmd: {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


def _ffmpeg_still(
    image_path: str,
    duration: float,
    output_path: str,
    fps: int = 30,
    crf: int = 20,
    preset: str = "veryfast",
) -> Path:
    args = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        f"{max(0.001, duration):.3f}",
        "-i",
        str(Path(image_path).resolve()),
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-tune",
        "stillimage",
        "-crf",
        str(crf),
        "-preset",
        str(preset),
        "-movflags",
        "+faststart",
        str(Path(output_path).resolve()),
    ]
    run_ffmpeg(args)
    return Path(output_path)


def _write_concat_list(list_path: Path, files: list):
    """ffmpeg concat demuxer 用の list.txt を絶対パスで書き出す。"""
    list_path = Path(list_path)
    list_path.parent.mkdir(parents=True, exist_ok=True)
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")


# ---------- 画像サイズを必ず偶数にそろえる ----------
def _ensure_even_size(arr: np.ndarray) -> np.ndarray:
    """
    H, W が奇数の場合、下・右に1ピクセルずつパディングして
    (偶数, 偶数) にそろえる（pad は edge）。
    """
    h, w = arr.shape[:2]
    new_h = h + (h % 2)
    new_w = w + (w % 2)
    if new_h == h and new_w == w:
        return arr
    pad_h = new_h - h
    pad_w = new_w - w
    if arr.ndim == 3:
        pad_width = ((0, pad_h), (0, pad_w), (0, 0))
    else:
        pad_width = ((0, pad_h), (0, pad_w))
    return np.pad(arr, pad_width, mode="edge")


# ---------- 内蔵ユーティリティ ----------
def ease_in_out_sine(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 0.5 * (1 - math.cos(math.pi * x))


def _unit(vx: float, vy: float):
    n = math.hypot(vx, vy)
    if n <= 1e-6:
        return (0.0, 0.0)
    return (vx / n, vy / n)


def _opposite_side_for_pointing(
    bbox: Tuple[int, int, int, int],
    canvas_wh: Tuple[int, int],
) -> str:
    x, y, w, h = bbox
    W, H = canvas_wh
    cx = x + w / 2.0
    return "right" if cx < W / 2 else "left"


def _edge_mid_tip(bbox: Tuple[int, int, int, int], side: str):
    x, y, w, h = bbox
    if side == "left":
        return (x, y + h / 2.0)
    if side == "right":
        return (x + w, y + h / 2.0)
    if side == "top":
        return (x + w / 2.0, y)
    else:
        return (x + w / 2.0, y + h)


# ---------- params 正規化（新旧両対応） ----------
def _parse_color_any(c):
    """(r,g,b) / '#RRGGBB' / '#RGB' / 'r,g,b' を許可。失敗時は既定色。"""
    if c is None:
        return (0, 200, 255)
    if isinstance(c, (list, tuple)) and len(c) == 3:
        try:
            return tuple(int(x) for x in c)
        except Exception:
            return (0, 200, 255)
    if isinstance(c, str):
        s = c.strip()
        if s.startswith("#"):
            if len(s) == 7:
                return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
            if len(s) == 4:  # #RGB
                return tuple(int(s[i] * 2, 16) for i in (1, 2, 3))
        if "," in s:
            parts = s.split(",")
            if len(parts) == 3:
                try:
                    return tuple(int(p) for p in parts)
                except Exception:
                    pass
    return (0, 200, 255)


def _norm_side(v: Optional[str]) -> str:
    s = (v or "auto_opposite").strip().lower()
    if s in ("auto", "opposite", "auto-opposite", "auto_opposite"):
        return "auto_opposite"
    if s in ("left", "right", "top", "bottom"):
        return s
    return "auto_opposite"


def _norm_tip_pos(v: Optional[str]) -> str:
    s = (v or "edge_mid").strip().lower()
    if s in ("edge", "edge_mid", "edge-middle", "mid"):
        return "edge_mid"
    if s in ("center", "centre", "middle"):
        return "center"
    return "edge_mid"


def _to_int(v, default):
    try:
        return int(v)
    except Exception:
        return default


def _to_float(v, default):
    try:
        return float(v)
    except Exception:
        return default


def _normalize_arrow_config(cfg_in: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    新JSON: duration_sec / 旧: fadein の両対応
    色: color / arrow_color / fill などを許可
    他パラメータも型・範囲を安全化
    """
    cfg = {
        "fps": 30,
        "color": (0, 200, 255),
        "thickness": 60,
        "arrow_len_px": 30.0,
        "head_len_scale": 0.7,
        "head_width_scale": 1.0,
        "glow_radius": 0,
        "fadein": 1.0,  # ← duration_sec があれば上書き
        "fallback_audio_sec": 2.0,
        "crf": 20,
        "preset": "veryfast",
        "side": "auto_opposite",
        "tip_pos": "edge_mid",
        "tip_inset_px": 3.0,
    }
    if cfg_in:
        cfg.update(cfg_in)

    # duration_sec -> fadein
    if cfg_in and "duration_sec" in cfg_in:
        cfg["fadein"] = _to_float(cfg_in.get("duration_sec"), cfg.get("fadein", 1.0))

    # color 別名（優先順: color > arrow_color > fill）
    color_key = None
    for k in ("color", "arrow_color", "fill"):
        if cfg_in and k in cfg_in:
            color_key = k
            break
    if cfg_in and color_key:
        cfg["color"] = _parse_color_any(cfg_in[color_key])
    else:
        cfg["color"] = _parse_color_any(cfg.get("color"))

    # 数値・範囲の安全化
    cfg["fps"] = max(1, _to_int(cfg.get("fps"), 30))
    cfg["thickness"] = max(2, _to_int(cfg.get("thickness"), 60))
    cfg["arrow_len_px"] = max(4.0, _to_float(cfg.get("arrow_len_px"), 30.0))
    cfg["head_len_scale"] = max(0.1, _to_float(cfg.get("head_len_scale"), 0.7))
    cfg["head_width_scale"] = max(0.1, _to_float(cfg.get("head_width_scale"), 1.0))
    cfg["glow_radius"] = max(0, _to_int(cfg.get("glow_radius"), 0))
    cfg["fadein"] = max(0.05, _to_float(cfg.get("fadein"), 1.0))
    cfg["fallback_audio_sec"] = max(0.05, _to_float(cfg.get("fallback_audio_sec"), 2.0))
    cfg["crf"] = _to_int(cfg.get("crf"), 20)
    cfg["preset"] = str(cfg.get("preset", "veryfast"))

    # enumの表記ゆれ
    cfg["side"] = _norm_side(cfg.get("side"))
    cfg["tip_pos"] = _norm_tip_pos(cfg.get("tip_pos"))
    cfg["tip_inset_px"] = max(0.0, _to_float(cfg.get("tip_inset_px"), 3.0))

    return cfg


# ---------- 矢印（無音アニメ） ----------
def _arrow_clip(
    base_np: np.ndarray,
    bbox: Tuple[int, int, int, int],
    fadein: float,
    fps: int,
    cfg: Dict[str, Any],
) -> VideoClip:
    H, W = base_np.shape[:2]
    base_img = Image.fromarray(base_np, mode="RGB")

    color = tuple(cfg.get("color", (0, 200, 255)))
    thickness = int(cfg.get("thickness", 60))
    arrow_len = float(cfg.get("arrow_len_px", 30.0))
    head_len_scale = float(cfg.get("head_len_scale", 0.7))
    head_width_scale = float(cfg.get("head_width_scale", 1.0))
    head_len = max(8.0, thickness * head_len_scale)
    head_width = max(6.0, thickness * head_width_scale)
    glow_radius = int(cfg.get("glow_radius", 0))
    side = str(cfg.get("side", "auto_opposite")).lower()
    tip_pos = str(cfg.get("tip_pos", "edge_mid")).lower()
    tip_inset = float(cfg.get("tip_inset_px", 3.0))

    x, y, w, h = bbox
    if side == "auto_opposite":
        side = _opposite_side_for_pointing(bbox, (W, H))

    if tip_pos == "edge_mid":
        tip = _edge_mid_tip(
            bbox,
            "left"
            if side == "left"
            else "right"
            if side == "right"
            else "top"
            if side == "top"
            else "bottom",
        )
    else:
        tip = (x + w / 2.0, y + h / 2.0)

    # tip をわずかに領域内に押し込む
    if side == "left":
        tip = (tip[0] + tip_inset, tip[1])
    if side == "right":
        tip = (tip[0] - tip_inset, tip[1])
    if side == "top":
        tip = (tip[0], tip[1] + tip_inset)
    if side == "bottom":
        tip = (tip[0], tip[1] - tip_inset)

    if side == "left":
        dirv = (1.0, 0.0)
    elif side == "right":
        dirv = (-1.0, 0.0)
    elif side == "top":
        dirv = (0.0, 1.0)
    else:
        dirv = (0.0, -1.0)

    dx, dy = _unit(*dirv)
    nx, ny = -dy, dx  # 法線

    # 矢じり基底とシャフト
    B = (tip[0] - dx * head_len, tip[1] - dy * head_len)
    start = (B[0] - dx * arrow_len, B[1] - dy * arrow_len)
    start = (min(max(0, start[0]), W - 1), min(max(0, start[1]), H - 1))
    epsilon = 1.0
    B_eps = (B[0] + dx * epsilon, B[1] + dy * epsilon)

    half = thickness / 2.0
    shaft_poly = [
        (start[0] + nx * half, start[1] + ny * half),
        (B_eps[0] + nx * half, B_eps[1] + ny * half),
        (B_eps[0] - nx * half, B_eps[1] - ny * half),
        (start[0] - nx * half, start[1] - ny * half),
    ]
    head_poly = [
        (tip[0], tip[1]),
        (B[0] + nx * head_width, B[1] + ny * head_width),
        (B[0] - nx * head_width, B[1] - ny * head_width),
    ]

    def make_frame(t: float):
        prog = min(1.0, max(0.0, t / max(1e-6, fadein)))
        a = int(255 * ease_in_out_sine(prog))

        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        drawg = ImageDraw.Draw(glow)

        draw.polygon(shaft_poly, fill=(color[0], color[1], color[2], a))
        draw.polygon(head_poly, fill=(color[0], color[1], color[2], a))

        if glow_radius > 0:
            drawg.polygon(shaft_poly, fill=(color[0], color[1], color[2], a // 2))
            drawg.polygon(head_poly, fill=(color[0], color[1], color[2], a // 2))
            glow_blur = glow.filter(ImageFilter.GaussianBlur(glow_radius))
            layer = Image.alpha_composite(glow_blur, layer)

        out = Image.alpha_composite(base_img.convert("RGBA"), layer)
        return np.array(out.convert("RGB"))

    return VideoClip(make_frame, duration=float(fadein))


# ---------- 公開関数 ----------
def animate_arrow_point(
    slide_image_path: str,
    bbox: Tuple[int, int, int, int],
    audio_path: Optional[str],
    output_path: str,
    config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Path:
    
    # config と kwargs をマージ（旧API対策）
    if config is None:
        config = {}
    else:
        config = dict(config)  # 破壊しないようコピー

    # 旧版の verbose / fps などが来ていた場合に吸収
    if "verbose" in kwargs and "verbose" not in config:
        config["verbose"] = kwargs.pop("verbose")
    if "fps" in kwargs and "fps" not in config:
        config["fps"] = kwargs.pop("fps")

    # その他の未知パラメータも一旦 config に入れておく
    config.update(kwargs)

    cfg = _normalize_arrow_config(config)

    img_p = Path(slide_image_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # スライド画像を読み込んで即座に偶数サイズにそろえる
    with Image.open(img_p) as im:
        base_np = np.array(im.convert("RGB"))
    base_np = _ensure_even_size(base_np)

    # 音声長
    audio_clip = None
    if audio_path and Path(audio_path).exists():
        try:
            audio_clip = AudioFileClip(str(Path(audio_path).resolve()))
        except Exception:
            audio_clip = None

    total_dur = float(audio_clip.duration) if audio_clip else float(cfg["fallback_audio_sec"])
    fps = int(cfg["fps"])
    fadein = min(float(cfg["fadein"]), total_dur)

    # (1) 無音アニメ生成
    motion_clip = _arrow_clip(base_np, bbox, fadein, fps, cfg)
    tmp_anim = str(out_p.with_name(out_p.stem + "_anim.mp4"))

    # 最終フレーム保存（close 前） ─ 念のためここでも偶数保証
    last_frame = motion_clip.get_frame(max(0.0, fadein - 1e-3)) if fadein > 0 else base_np
    last_frame = _ensure_even_size(last_frame)
    still_png = str(out_p.with_name(out_p.stem + "_still.png"))
    Image.fromarray(last_frame).save(still_png)

    motion_clip.write_videofile(
        str(Path(tmp_anim).resolve()),
        fps=fps,
        codec="libx264",
        audio=False, 
        logger=None,
    )

    # (2) 静止区間（-loop 1）
    remain = max(0.0, total_dur - fadein)
    tmp_still: Optional[str] = None
    if remain > 0:
        tmp_still = str(out_p.with_name(out_p.stem + "_still.mp4"))
        _ffmpeg_still(
            still_png,
            remain,
            tmp_still,
            fps=fps,
            crf=int(cfg["crf"]),
            preset=str(cfg["preset"]),
        )

    # (3) 連結 + 音声合成（ffmpeg、list.txt は絶対パス）
    if tmp_still:
        list_file = out_p.with_suffix(".txt")
        _write_concat_list(list_file, [tmp_anim, tmp_still])

        args = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(Path(list_file).resolve()),
        ]
        if audio_clip:
            args += ["-i", str(Path(audio_path).resolve()), "-shortest"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        if audio_clip:
            args += ["-c:a", "aac"]
        args += [str(out_p.resolve())]
        run_ffmpeg(args)
    else:
        # アニメのみ +（任意で）音声
        args = ["ffmpeg", "-y", "-i", str(Path(tmp_anim).resolve())]
        if audio_clip:
            args += [
                "-i",
                str(Path(audio_path).resolve()),
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-pix_fmt",
                "yuv420p",
            ]
        else:
            args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        args += [str(out_p.resolve())]
        run_ffmpeg(args)

    # 後片付け
    with contextlib.suppress(Exception):
        motion_clip.close()
    if audio_clip:
        with contextlib.suppress(Exception):
            audio_clip.close()
    for f in [tmp_anim, tmp_still, still_png, out_p.with_suffix(".txt")]:
        if f and Path(f).exists():
            with contextlib.suppress(Exception):
                Path(f).unlink()

    return out_p
