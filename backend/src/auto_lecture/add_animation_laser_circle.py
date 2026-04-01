# src/auto_lecture/add_animation_laser_circle.py
# ============================================
# レーザー円アニメーション（1周だけ）モジュール
# - draw_mode="accumulate": 描いた軌跡が積み上がって残る（既定）
# - draw_mode="sweep": 短い尾だけが移動（従来の見え方）
# - 新JSONの animate.params をそのまま config に渡せる想定：
#   例: {"duration_sec": 0.9, "laser_color": "#FF5050", "draw_mode": "accumulate"}
# ============================================

from __future__ import annotations

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List
import math
import os
import contextlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from moviepy.video.VideoClip import VideoClip
from moviepy.audio.io.AudioFileClip import AudioFileClip


__all__ = [
    "animate_laser_circle_once",
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


# ---------- 内蔵ユーティリティ ----------
def ease_in_out_sine(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 0.5 * (1 - math.cos(math.pi * x))


def ellipse_points(bbox: Tuple[int, int, int, int], n: int = 900) -> List[Tuple[float, float]]:
    x, y, w, h = bbox
    cx, cy = x + w / 2.0, y + h / 2.0
    rx, ry = max(1.0, w / 2.0), max(1.0, h / 2.0)
    theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    xs = cx + rx * np.cos(theta)
    ys = cy + ry * np.sin(theta)
    return list(zip(xs, ys))


def slice_path_with_trail(
    path: List[Tuple[float, float]], prog: float, trail_len: float
) -> List[Tuple[float, float]]:
    """先頭付近だけを切り出す（従来の“短い尾”）。"""
    prog = max(0.0, min(1.0, prog))
    n = max(2, len(path))
    end_idx = max(2, int(round(prog * (n - 1))))
    start_prog = max(0.0, prog - min(1.0, trail_len))
    start_idx = int(round(start_prog * (n - 1)))
    start_idx = min(start_idx, end_idx - 1)
    return path[start_idx:end_idx]


def slice_path_accumulate(path: List[Tuple[float, float]], prog: float) -> List[Tuple[float, float]]:
    """開始から先頭まで全部を描く（軌跡が残る）。"""
    prog = max(0.0, min(1.0, prog))
    n = max(2, len(path))
    end_idx = max(2, int(round(prog * (n - 1))))
    return path[:end_idx]


def gradient_alphas(m: int, alpha_head=255, alpha_tail=40) -> List[int]:
    if m <= 1:
        return [alpha_head]
    return np.linspace(alpha_tail, alpha_head, m).astype(int).tolist()


def _ensure_even_size(arr: np.ndarray) -> np.ndarray:
    """
    H, W が奇数の場合、下・右に 1 ピクセルずつパディングして
    (偶数, 偶数) にそろえる。（libx264 / yuv420p 対策）
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


# ---------- params 正規化（新旧両対応） ----------
def _parse_color_any(c):
    """(r,g,b) / '#RRGGBB' / '#RGB' / 'r,g,b' を許可。失敗時は既定色。"""
    if c is None:
        return (255, 50, 50)
    if isinstance(c, (list, tuple)) and len(c) == 3:
        try:
            return tuple(int(x) for x in c)
        except Exception:
            return (255, 50, 50)
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
    return (255, 50, 50)


def _normalize_config(cfg_in: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    新JSON: duration_sec / 旧: anim_duration の両対応
    draw_mode: "accumulate"(既定) | "sweep"
      - accumulate: 軌跡が残る
      - sweep: 短い尾だけが動く（従来）
    """
    cfg = {
        "fps": 30,
        "anim_duration": 1.5,  # ← duration_sec があれば上書き
        "laser_color": (255, 50, 50),
        "thickness": 8,
        "glow_radius": 15,
        "trail_len": 0.3,  # sweep 用
        "draw_mode": "accumulate",
        "fallback_audio_sec": 2.0,
        "crf": 20,
        "preset": "veryfast",
        # 見やすさ用: accumulate でも先頭 acc_head_len だけ明るくブースト表示
        "acc_head_boost": True,
        "acc_head_len": 0.06,  # 全周比の先頭区間
    }
    if cfg_in:
        cfg.update(cfg_in)

    # alias: duration_sec -> anim_duration
    if cfg_in and "duration_sec" in cfg_in:
        try:
            cfg["anim_duration"] = float(cfg_in["duration_sec"])
        except Exception:
            pass

    # 旧 persist_mode 互換: "trail" なら sweep 扱い
    if cfg_in and str(cfg_in.get("persist_mode", "")).lower() == "trail" and "draw_mode" not in cfg_in:
        cfg["draw_mode"] = "sweep"

    # 型/範囲の安全化
    try:
        cfg["fps"] = int(cfg.get("fps", 30))
    except Exception:
        cfg["fps"] = 30
    try:
        cfg["thickness"] = int(cfg.get("thickness", 8))
    except Exception:
        cfg["thickness"] = 8
    try:
        cfg["glow_radius"] = int(cfg.get("glow_radius", 15))
    except Exception:
        cfg["glow_radius"] = 15
    try:
        cfg["trail_len"] = float(cfg.get("trail_len", 0.3))
    except Exception:
        cfg["trail_len"] = 0.3
    try:
        cfg["fallback_audio_sec"] = float(cfg.get("fallback_audio_sec", 2.0))
    except Exception:
        cfg["fallback_audio_sec"] = 2.0
    try:
        cfg["anim_duration"] = max(0.05, float(cfg.get("anim_duration", 1.5)))
    except Exception:
        cfg["anim_duration"] = 1.5
    try:
        cfg["acc_head_len"] = max(0.0, min(0.3, float(cfg.get("acc_head_len", 0.06))))
    except Exception:
        cfg["acc_head_len"] = 0.06
    cfg["acc_head_boost"] = bool(cfg.get("acc_head_boost", True))

    cfg["laser_color"] = _parse_color_any(cfg.get("laser_color"))
    if str(cfg.get("draw_mode", "accumulate")).lower() not in ("accumulate", "sweep"):
        cfg["draw_mode"] = "accumulate"
    else:
        cfg["draw_mode"] = str(cfg["draw_mode"]).lower()
    return cfg


# ---------- レーザー1周アニメ（無音） ----------
def _laser_once_clip(
    base_img_np: np.ndarray,
    bbox: Tuple[int, int, int, int],
    anim_duration: float,
    fps: int,
    color=(255, 50, 50),
    thickness: int = 8,
    glow_radius: int = 15,
    trail_len: float = 0.3,
    draw_mode: str = "accumulate",
    acc_head_boost: bool = True,
    acc_head_len: float = 0.06,
) -> VideoClip:
    """
    draw_mode:
      - "accumulate": 軌跡が残る。必要なら先頭 acc_head_len だけ明るくブースト表示。
      - "sweep": 短い尾だけが動く（従来）。
    """
    # ★ base_img_np はすでに偶数サイズに調整済み（animate_laser_circle_once 側で）
    H, W = base_img_np.shape[:2]
    base_img = Image.fromarray(base_img_np, mode="RGB")
    path = ellipse_points(bbox, n=900)

    def draw_segment(seg_points, alphas=None):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        dg = ImageDraw.Draw(glow)

        if alphas is None:
            alphas = [255] * len(seg_points)

        for i in range(len(seg_points) - 1):
            p0, p1 = seg_points[i], seg_points[i + 1]
            a = alphas[i] if i < len(alphas) else 255
            d.line([p0, p1], fill=(color[0], color[1], color[2], a), width=thickness)
            dg.line([p0, p1], fill=(color[0], color[1], color[2], int(a * 0.6)), width=thickness)

        glow_blur = glow.filter(ImageFilter.GaussianBlur(glow_radius))
        out = base_img.convert("RGBA")
        out = Image.alpha_composite(out, glow_blur)
        out = Image.alpha_composite(out, layer)
        return np.array(out.convert("RGB"))

    def make_frame(t: float):
        prog = ease_in_out_sine(min(1.0, max(0.0, t / anim_duration)))

        if draw_mode == "accumulate":
            seg = slice_path_accumulate(path, prog)
            if len(seg) < 2:
                return np.array(base_img)

            # 全体はやや控えめ、先頭 acc_head_len だけ明るくして “動き” を感じさせる
            base_alpha = 180
            alphas = [base_alpha] * len(seg)
            if acc_head_boost and len(seg) > 3:
                k = max(2, int(len(path) * acc_head_len))
                for i in range(max(0, len(seg) - k), len(seg)):
                    alphas[i] = 255
            return draw_segment(seg, alphas)

        else:  # "sweep"
            seg = slice_path_with_trail(path, prog, trail_len)
            if len(seg) < 2:
                return np.array(base_img)
            alphas = gradient_alphas(len(seg), 255, 40)
            return draw_segment(seg, alphas)

    # ★ set_fps は使わず、VideoClip だけ返す
    return VideoClip(make_frame, duration=float(anim_duration))


# ---------- 公開関数 ----------
def animate_laser_circle_once(
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
        config = dict(config)

    # 旧版の verbose / fps などが来ていた場合に吸収
    if "verbose" in kwargs and "verbose" not in config:
        config["verbose"] = kwargs.pop("verbose")
    if "fps" in kwargs and "fps" not in config:
        config["fps"] = kwargs.pop("fps")

    # その他の未知パラメータも一旦 config に入れておく
    config.update(kwargs)

    cfg = _normalize_config(config)

    img_p = Path(slide_image_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(img_p) as im:
        base_np = np.array(im.convert("RGB"))

    # ★ ここで必ず (偶数, 偶数) サイズにそろえる（エンコード安定化）
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
    anim_dur = min(float(cfg["anim_duration"]), total_dur)

    # (1) アニメ区間（無音 mp4）
    motion_clip = _laser_once_clip(
        base_np,
        bbox,
        anim_dur,
        fps,
        cfg["laser_color"],
        int(cfg["thickness"]),
        int(cfg["glow_radius"]),
        float(cfg["trail_len"]),
        draw_mode=cfg["draw_mode"],
        acc_head_boost=bool(cfg["acc_head_boost"]),
        acc_head_len=float(cfg["acc_head_len"]),
    )

    tmp_anim = str(out_p.with_name(out_p.stem + "_anim.mp4"))

    # 最終フレーム PNG（close 前）
    last_frame = motion_clip.get_frame(max(0.0, anim_dur - 1e-3)) if anim_dur > 0 else base_np
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
    remain = max(0.0, total_dur - anim_dur)
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
