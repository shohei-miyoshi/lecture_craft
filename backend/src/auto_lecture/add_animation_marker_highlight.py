# src/auto_lecture/add_animation_marker_highlight.py
# ============================================
# マーカー塗りアニメーションモジュール
# - mode="block": 1ブロックごと塗る
# - mode="lines": 複数行の下線・ラインとして塗る
# - 終了後は最終フレームで静止し、音声末まで表示
# - animate.params をそのまま config に渡せる想定：
#   例: {"duration_sec": 0.9, "color": "#FFF799", "mode": "lines", "line_count": 2}
# ============================================

from __future__ import annotations

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List
import math
import contextlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from moviepy.video.VideoClip import VideoClip
from moviepy.audio.io.AudioFileClip import AudioFileClip


__all__ = ["animate_marker_highlight"]


# ---------- 安全な ffmpeg 実行 ----------
def run_ffmpeg(args: List[Any]) -> subprocess.CompletedProcess[str]:
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
    args: List[Any] = [
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


def _write_concat_list(list_path: Path, files: List[str]) -> None:
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


# ---------- ユーティリティ ----------
def ease_in_out_sine(x: float) -> float:
    x_clamped = max(0.0, min(1.0, x))
    return 0.5 * (1 - math.cos(math.pi * x_clamped))


def _compute_line_bands(
    x: int,
    y: int,
    w: int,
    h: int,
    line_count: int,
    marker_height_ratio: Optional[float],
    line_spacing_px: Optional[int],
    align: str,
    offset_ratio: float,
) -> List[Tuple[int, int]]:
    n = max(1, min(5, int(line_count)))
    h = max(2, int(h))

    if marker_height_ratio is None:
        band_h = max(2, int(round(h / (2.5 * n))))
    else:
        band_h = max(2, int(round(h * float(marker_height_ratio))))

    gap = max(1, int(round(band_h * 0.5))) if line_spacing_px is None else max(1, int(line_spacing_px))

    total_h = n * band_h + (n - 1) * gap
    if total_h > h:
        scale = h / float(total_h)
        band_h = max(2, int(round(band_h * scale)))
        gap = max(1, int(round(gap * scale)))
        total_h = n * band_h + (n - 1) * gap
        if total_h > h:
            overflow = total_h - h
            shrink_each = int(np.ceil(overflow / float(n)))
            band_h = max(2, band_h - shrink_each)
            total_h = n * band_h + (n - 1) * gap
            if total_h > h and gap > 1:
                gap = max(1, gap - (total_h - h))
                total_h = n * band_h + (n - 1) * gap

    if align == "top":
        start_y = y
    elif align == "bottom":
        start_y = y + h - total_h
    else:
        start_y = y + (h - total_h) // 2
    start_y = int(round(start_y + h * float(offset_ratio)))

    bands: List[Tuple[int, int]] = []
    cur = start_y
    for _ in range(n):
        y0 = max(y, cur)
        y1 = min(y + h, y0 + band_h)
        if y1 - y0 < 2:
            y1 = min(y + h, y0 + 2)
        bands.append((y0, y1))
        cur = y1 + gap

    fixed: List[Tuple[int, int]] = []
    for (yy0, yy1) in bands:
        yy0_clamped = max(y, min(y + h, yy0))
        yy1_clamped = max(y, min(y + h, yy1))
        if yy1_clamped - yy0_clamped < 2:
            yy1_clamped = min(y + h, yy0_clamped + 2)
        fixed.append((yy0_clamped, yy1_clamped))
    return fixed


# ---------- params 正規化（新旧両対応） ----------
def _parse_color_any(c: Any) -> Tuple[int, int, int]:
    """(r,g,b) / '#RRGGBB' / '#RGB' / 'r,g,b' を許可。失敗時は既定色。"""
    if c is None:
        return (255, 247, 153)
    if isinstance(c, (list, tuple)) and len(c) == 3:
        try:
            return tuple(int(x) for x in c)  # type: ignore[return-value]
        except Exception:
            return (255, 247, 153)
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
    return (255, 247, 153)


def _normalize_mode(m: Optional[str]) -> str:
    """mode の表記ゆれ補正。"""
    s = (m or "block").strip().lower()
    if s in ("block", "box", "fill"):
        return "block"
    if s in ("line", "lines", "underline", "underlines"):
        return "lines"
    return "block"


def _normalize_marker_config(cfg_in: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    新JSON: duration_sec / 旧: paint_duration の両対応
    色: color / marker_color / highlight_color / fill
    alpha: 0-255 or opacity(0-1) 両対応
    mode: "block" / "lines"（表記ゆれ吸収）
    """
    cfg: Dict[str, Any] = {
        "fps": 30,
        "mode": "block",
        "color": (255, 247, 153),
        "alpha": 165,
        "corner_radius": 8,
        "feather_radius": 1,
        "blend_mode": "normal",  # normal|screen|multiply
        "block_hmargin_px": 8,
        "block_vmargin_px": 6,
        "line_count": 1,
        "marker_height_ratio": None,
        "line_spacing_px": None,
        "align": "center",  # top|center|bottom
        "offset_ratio": 0.0,  # -1.0..+1.0 推奨は小さめ
        "paint_duration": 1.2,  # ← duration_sec があれば上書き
        "fallback_audio_sec": 2.0,
        "crf": 20,
        "preset": "veryfast",
    }
    if cfg_in:
        cfg.update(cfg_in)

    # duration_sec -> paint_duration
    if cfg_in and "duration_sec" in cfg_in:
        try:
            cfg["paint_duration"] = float(cfg_in["duration_sec"])
        except Exception:
            pass

    # color の別名（優先順: color > marker_color > highlight_color > fill）
    color_key: Optional[str] = None
    for k in ("color", "marker_color", "highlight_color", "fill"):
        if cfg_in and k in cfg_in:
            color_key = k
            break
    if cfg_in and color_key:
        cfg["color"] = _parse_color_any(cfg_in[color_key])
    else:
        cfg["color"] = _parse_color_any(cfg.get("color"))

    # alpha / opacity
    if cfg_in and "opacity" in cfg_in:
        try:
            op = float(cfg_in["opacity"])
            cfg["alpha"] = max(0, min(255, int(round(op * 255))))
        except Exception:
            pass
    try:
        cfg["alpha"] = max(0, min(255, int(cfg.get("alpha", 165))))
    except Exception:
        cfg["alpha"] = 165

    # mode / blend_mode
    cfg["mode"] = _normalize_mode(cfg.get("mode"))
    bm = str(cfg.get("blend_mode", "normal")).strip().lower()
    if bm not in ("normal", "screen", "multiply"):
        bm = "normal"
    cfg["blend_mode"] = bm

    # 型の安全化
    def _to_int(name: str, default: int) -> int:
        try:
            return int(cfg.get(name, default))
        except Exception:
            return default

    def _to_float(name: str, default: float) -> float:
        try:
            return float(cfg.get(name, default))
        except Exception:
            return default

    cfg["fps"] = _to_int("fps", 30)
    cfg["corner_radius"] = _to_int("corner_radius", 8)
    cfg["feather_radius"] = _to_int("feather_radius", 1)
    cfg["block_hmargin_px"] = _to_int("block_hmargin_px", 8)
    cfg["block_vmargin_px"] = _to_int("block_vmargin_px", 6)
    cfg["line_count"] = max(1, min(5, _to_int("line_count", 1)))

    # None 許容系
    mhr = cfg.get("marker_height_ratio", None)
    cfg["marker_height_ratio"] = None if mhr in (None, "", "None") else float(mhr)
    lsp = cfg.get("line_spacing_px", None)
    cfg["line_spacing_px"] = None if lsp in (None, "", "None") else int(lsp)

    al = str(cfg.get("align", "center")).strip().lower()
    if al not in ("top", "center", "bottom"):
        al = "center"
    cfg["align"] = al

    cfg["offset_ratio"] = _to_float("offset_ratio", 0.0)
    cfg["paint_duration"] = max(0.05, _to_float("paint_duration", 1.2))
    cfg["fallback_audio_sec"] = _to_float("fallback_audio_sec", 2.0)
    cfg["crf"] = _to_int("crf", 20)
    cfg["preset"] = str(cfg.get("preset", "veryfast"))
    return cfg


# ---------- マーカー（無音アニメ） ----------
def _marker_clip(
    base_np: np.ndarray,
    bbox: Tuple[int, int, int, int],
    paint_duration: float,
    fps: int,
    cfg: Dict[str, Any],
) -> VideoClip:
    H, W = base_np.shape[:2]
    base_img = Image.fromarray(base_np, mode="RGB")
    x, y, w, h = bbox

    mode = cfg["mode"]
    color = tuple(cfg.get("color", (255, 247, 153)))
    alpha = int(cfg.get("alpha", 165))
    corner_radius = int(cfg.get("corner_radius", 8))
    feather_radius = int(cfg.get("feather_radius", 1))
    blend_mode = cfg["blend_mode"]

    # mode に応じて band（塗る縦幅）を決める
    if mode == "lines":
        bands = _compute_line_bands(
            x,
            y,
            w,
            h,
            line_count=int(cfg.get("line_count", 1)),
            marker_height_ratio=cfg.get("marker_height_ratio", None),
            line_spacing_px=cfg.get("line_spacing_px", None),
            align=str(cfg.get("align", "center")).lower(),
            offset_ratio=float(cfg.get("offset_ratio", 0.0)),
        )
        x_draw, w_draw = x, w
    else:
        hpad = int(cfg.get("block_hmargin_px", 8))
        vpad = int(cfg.get("block_vmargin_px", 6))
        bx0 = max(0, x + hpad)
        by0 = max(0, y + vpad)
        bx1 = min(W, x + w - hpad)
        by1 = min(H, y + h - vpad)
        if by1 - by0 < 2:
            by1 = min(H, by0 + 2)
        bands = [(by0, by1)]
        x_draw, w_draw = bx0, max(1, bx1 - bx0)

    def _composite(bg_rgba: Image.Image, layer: Image.Image) -> np.ndarray:
        if blend_mode == "screen":
            rgb_bg = bg_rgba.convert("RGB")
            rgb_layer = Image.new("RGB", (W, H), (0, 0, 0))
            rgb_layer.paste(layer.convert("RGB"), mask=layer.split()[-1])
            screened = ImageChops.screen(rgb_bg, rgb_layer)
            out = Image.composite(screened, rgb_bg, layer.split()[-1])
            return np.array(out.convert("RGB"))
        if blend_mode == "multiply":
            rgb_bg = bg_rgba.convert("RGB")
            rgb_layer = Image.new("RGB", (W, H), (255, 255, 255))
            rgb_layer.paste(layer.convert("RGB"), mask=layer.split()[-1])
            multiplied = ImageChops.multiply(rgb_bg, rgb_layer)
            out = Image.composite(multiplied, rgb_bg, layer.split()[-1])
            return np.array(out.convert("RGB"))
        return np.array(Image.alpha_composite(bg_rgba, layer).convert("RGB"))

    def make_frame(t: float) -> np.ndarray:
        prog = ease_in_out_sine(max(0.0, min(1.0, t / paint_duration)))
        xmax = x_draw + int(round(w_draw * prog))

        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        if xmax > x_draw:
            for (y0, y1) in bands:
                rect = [x_draw, y0, xmax, y1]
                if corner_radius > 0:
                    draw.rounded_rectangle(
                        rect,
                        radius=corner_radius,
                        fill=(color[0], color[1], color[2], alpha),
                    )
                else:
                    draw.rectangle(rect, fill=(color[0], color[1], color[2], alpha))

        if feather_radius > 0:
            layer = layer.filter(ImageFilter.GaussianBlur(feather_radius))

        return _composite(base_img.convert("RGBA"), layer)

    # fps は外側で VideoFile 出力時に使用。ここでは duration のみ指定。
    return VideoClip(make_frame, duration=float(paint_duration))


# ---------- 公開関数 ----------
def animate_marker_highlight(
    slide_image_path: str,
    bbox: Tuple[int, int, int, int],
    audio_path: Optional[str],
    output_path: str,
    config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Path:
    
    # config と kwargs をマージ（旧API対策）
    merged_cfg: Dict[str, Any] = dict(config) if config is not None else {}

    # 旧版から飛んでくる verbose / fps などを吸収
    if "verbose" in kwargs and "verbose" not in merged_cfg:
        merged_cfg["verbose"] = kwargs.pop("verbose")
    if "fps" in kwargs and "fps" not in merged_cfg:
        merged_cfg["fps"] = kwargs.pop("fps")

    # その他の未知パラメータも一旦 config に入れておく
    merged_cfg.update(kwargs)

    cfg = _normalize_marker_config(merged_cfg)

    img_p = Path(slide_image_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # スライド画像を読み込んで即座に偶数サイズにそろえる
    with Image.open(img_p) as im:
        base_np = np.array(im.convert("RGB"))
    base_np = _ensure_even_size(base_np)

    # 音声長
    audio_clip: Optional[AudioFileClip] = None
    if audio_path and Path(audio_path).exists():
        try:
            audio_clip = AudioFileClip(str(Path(audio_path).resolve()))
        except Exception:
            audio_clip = None
    total_dur = float(audio_clip.duration) if audio_clip else float(cfg["fallback_audio_sec"])

    fps = int(cfg["fps"])
    paint_dur = min(float(cfg["paint_duration"]), total_dur)

    # (1) 無音アニメ生成
    motion_clip = _marker_clip(base_np, bbox, paint_dur, fps, cfg)
    tmp_anim = str(out_p.with_name(out_p.stem + "_anim.mp4"))

    # 最終フレーム保存（close 前） ─ 念のためここでも偶数保証
    last_frame = motion_clip.get_frame(max(0.0, paint_dur - 1e-3)) if paint_dur > 0 else base_np
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
    remain = max(0.0, total_dur - paint_dur)
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

        args: List[Any] = [
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
        args2: List[Any] = ["ffmpeg", "-y", "-i", str(Path(tmp_anim).resolve())]
        if audio_clip:
            args2 += [
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
            args2 += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
        args2 += [str(out_p.resolve())]
        run_ffmpeg(args2)

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
