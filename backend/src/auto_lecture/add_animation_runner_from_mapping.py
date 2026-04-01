# src/auto_lecture/add_animation_runner_from_mapping.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set
import json
import re
import subprocess
import time

from PIL import Image

from .add_animation_laser_circle import animate_laser_circle_once
from .add_animation_marker_highlight import animate_marker_highlight
from .add_animation_arrow_point import animate_arrow_point
from .paths import ProjectPaths

__all__ = [
    "RunnerConfig",
    "build_sentence_videos_from_mapping",
    "build_all_slides_from_mappings",
    "run_from_mapping",
]


# ============================================================
# RunnerConfig
# ============================================================
class RunnerConfig:
    """
    Step4: mapping -> sentence videos

    ポイント:
    - animate:null は「確実に成功」させるため、laser_circle を流用せず
      ffmpeg 1発で静止画+音声(or 無音) mp4 を生成する。
    - ログを多めに出し、どこで止まった/落ちたかを即特定できるようにする。
    """

    def __init__(
        self,
        lp_dir: Path,
        mapping_dir: Path,
        audio_root: Path,
        slide_img_dir: Path,
        out_dir: Path,
        use_timeline: bool = True,
        min_confidence: float = 0.0,
        max_anims_per_sent: Optional[int] = 1,
        styles_whitelist: Optional[Set[str]] = None,
        # ---- for animate:null robust path ----
        ffmpeg_bin: str = "ffmpeg",
        plain_fps: int = 30,
        plain_fallback_sec: float = 2.0,
        plain_even_scale: bool = True,
        # ---- logging ----
        verbose: bool = True,
    ) -> None:
        self.lp_dir = Path(lp_dir)
        self.mapping_dir = Path(mapping_dir)
        self.audio_root = Path(audio_root)
        self.slide_img_dir = Path(slide_img_dir)
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.use_timeline = bool(use_timeline)
        self.min_confidence = float(min_confidence)
        self.max_anims_per_sent = max_anims_per_sent
        self.styles_whitelist = styles_whitelist

        self.ffmpeg_bin = ffmpeg_bin
        self.plain_fps = int(plain_fps)
        self.plain_fallback_sec = float(plain_fallback_sec)
        self.plain_even_scale = bool(plain_even_scale)

        self.verbose = bool(verbose)


# ============================================================
# Logging
# ============================================================
def _ts() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[Step4 { _ts() }] {msg}", flush=True)


# ============================================================
# Utility
# ============================================================
def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _coords_to_xywh_guess(
    coords: List[int], from_size: Tuple[int, int]
) -> Tuple[float, float, float, float]:
    """
    coords が [x1,y1,x2,y2] か [x,y,w,h] のどちらでも来うる前提で
    “それっぽい方”に解釈して XYWH にする。
    """
    if not isinstance(coords, list) or len(coords) == 0:
        return (0.0, 0.0, 10.0, 10.0)

    if len(coords) != 4:
        xs, ys = coords[0::2], coords[1::2]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        return float(x0), float(y0), float(x1 - x0), float(y1 - y0)

    Wsrc, Hsrc = from_size
    x1, y1, a, b = [float(v) for v in coords]
    looks_like_x2y2 = (a > x1) and (b > y1) and (a <= Wsrc + 1) and (b <= Hsrc + 1)
    if looks_like_x2y2:
        return (x1, y1, (a - x1), (b - y1))
    else:
        return (x1, y1, a, b)


def scaled_bbox_from_coords(
    coords: List[int],
    from_size: Tuple[int, int],
    to_size: Tuple[int, int],
    offset_xy: Tuple[int, int] = (0, 0),
) -> Tuple[int, int, int, int]:
    """
    LP側基準サイズ(from_size)の座標を、
    最終動画側サイズ(to_size)にスケール変換する。
    """
    Wsrc, Hsrc = from_size
    Wdst, Hdst = to_size
    sx = Wdst / float(Wsrc if Wsrc else Wdst)
    sy = Hdst / float(Hsrc if Hsrc else Hdst)
    dx, dy = offset_xy

    x, y, w, h = _coords_to_xywh_guess(coords, from_size)
    x2 = int(round(x * sx + dx))
    y2 = int(round(y * sy + dy))
    w2 = int(round(w * sx))
    h2 = int(round(h * sy))
    return (x2, y2, max(1, w2), max(1, h2))


def load_slide_image_path(cfg: RunnerConfig, slide_str: str) -> Path:
    """
    001.png / page_001.png の両対応。
    """
    cand1 = cfg.slide_img_dir / f"{slide_str}.png"
    cand2 = cfg.slide_img_dir / f"page_{slide_str}.png"
    if cand1.exists():
        return cand1
    if cand2.exists():
        return cand2
    raise FileNotFoundError(f"Slide PNG not found: {cand1} or {cand2}")


def get_reference_image_size(cfg: RunnerConfig, slide_str: str) -> Tuple[int, int]:
    """
    LPの result_###.png がある場合はそれを基準サイズに使う。
    無ければスライド画像サイズ。
    """
    ref_png = cfg.lp_dir / f"result_{slide_str}.png"
    if ref_png.exists():
        with Image.open(ref_png) as im:
            return im.size
    with Image.open(load_slide_image_path(cfg, slide_str)) as im:
        return im.size


def load_result_regions(cfg: RunnerConfig, slide_str: str) -> List[Dict[str, Any]]:
    rp = cfg.lp_dir / f"result_{slide_str}.json"
    if not rp.exists():
        raise FileNotFoundError(f"Region json not found: {rp}")
    return load_json(rp)


def read_audio_for_sentence(
    cfg: RunnerConfig, slide_str: str, sent_idx_zero_based: int
) -> Optional[Path]:
    """
    tts_outputs/pageN/partXX.mp3 を探す。
    partXX は 1始まり想定。
    """
    page_dir = cfg.audio_root / f"page{int(slide_str)}"
    for ext in (".mp3", ".wav", ".m4a", ".ogg"):
        p = page_dir / f"part{sent_idx_zero_based + 1:02}{ext}"
        if p.exists():
            return p
    return None


# ============================================================
# Robust path for animate:null (ffmpeg one-shot)
# ============================================================
def _run_ffmpeg(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )


def _ffmpeg_make_still_with_audio(
    cfg: RunnerConfig,
    slide_png: Path,
    audio_path: Optional[Path],
    out_mp4: Path,
) -> None:
    """
    animate:null を「確実に成功」させるための最短経路。
    - 静止画 + 音声（あれば）を ffmpeg 1発で mp4 化
    - 音声が無ければ無音を合成して fallback_sec 秒で作る
    - H.264/yuv420p のために偶数化 scale を常にかける（任意でOFF可）
    """
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    vf = []
    if cfg.plain_even_scale:
        # どんな画像サイズでも H.264 が嫌がりにくいように偶数へ丸める
        vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    vf_arg = ",".join(vf) if vf else None

    if audio_path and audio_path.exists():
        cmd = [
            cfg.ffmpeg_bin,
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-loop",
            "1",
            "-i",
            str(slide_png),
            "-i",
            str(audio_path),
            "-shortest",
            "-r",
            str(cfg.plain_fps),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-tune",
            "stillimage",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
        if vf_arg:
            cmd += ["-vf", vf_arg]
        cmd += [str(out_mp4)]
        _run_ffmpeg(cmd)
        return

    # 音声が無い/読めない場合でも落ちないように無音を足す
    dur = max(0.2, float(cfg.plain_fallback_sec))
    cmd = [
        cfg.ffmpeg_bin,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-t",
        f"{dur:.3f}",
        "-i",
        str(slide_png),
        "-f",
        "lavfi",
        "-t",
        f"{dur:.3f}",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-r",
        str(cfg.plain_fps),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-tune",
        "stillimage",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
    ]
    if vf_arg:
        cmd += ["-vf", vf_arg]
    cmd += [str(out_mp4)]
    _run_ffmpeg(cmd)


# ============================================================
# Style dispatch
# ============================================================
DISPATCH = {
    "laser_circle": animate_laser_circle_once,
    "marker_highlight": animate_marker_highlight,
    "arrow_point": animate_arrow_point,
}


def _call_anim(
    cfg: RunnerConfig,
    style: str,
    slide_png: Path,
    bbox: Tuple[int, int, int, int],
    audio_path: Optional[Path],
    out_path: Path,
    params: Optional[Dict[str, Any]],
):
    fn = DISPATCH.get(style)
    if fn is None:
        log(f"  [skip] unsupported style: {style}")
        return None

    return fn(
        str(slide_png),
        bbox,
        str(audio_path) if audio_path else None,
        str(out_path),
        params or None,
    )


# ============================================================
# Core
# ============================================================
def build_sentence_videos_from_mapping(cfg: RunnerConfig, slide_str: str) -> List[Path]:
    """
    slide_XXX_mappings.json を読み、文ごとの mp4 を生成する。
    """
    mapping_path = cfg.mapping_dir / f"slide_{slide_str}_mappings.json"
    if not mapping_path.exists():
        log(f"[skip] mapping not found: {mapping_path}")
        return []

    mapping = load_json(mapping_path)
    sentences = mapping.get("sentences", [])

    slide_png = load_slide_image_path(cfg, slide_str)
    regions = load_result_regions(cfg, slide_str)
    ref_size = get_reference_image_size(cfg, slide_str)

    out_files: List[Path] = []

    with Image.open(slide_png) as im:
        to_size = im.size

    if cfg.verbose:
        log(
            f"--- slide {slide_str} --- "
            f"sentences={len(sentences)} slide_png={slide_png.name} to_size={to_size} "
            f"regions={len(regions)} ref_size={ref_size} mapping={mapping_path.name}"
        )

    for sent in sentences:
        sent_idx = int(sent.get("sent_idx", 0))
        if sent_idx <= 0:
            continue

        animate = sent.get("animate")
        audio_path = read_audio_for_sentence(cfg, slide_str, sent_idx_zero_based=sent_idx - 1)

        out_base = cfg.out_dir / f"slide_{slide_str}_sent{sent_idx:02d}"

        t0 = time.time()

        # -----------------------------
        # アニメなし → 静止画 + 音声（ffmpeg 1発で確実に）
        # -----------------------------
        if animate is None:
            out_mp4 = Path(str(out_base) + ".mp4")
            if cfg.verbose:
                log(
                    f"  ▶ sent{sent_idx:02d} plain: "
                    f"audio={'yes' if (audio_path and audio_path.exists()) else 'no'} "
                    f"-> {out_mp4.name}"
                )
            try:
                _ffmpeg_make_still_with_audio(cfg, slide_png, audio_path, out_mp4)
                out_files.append(out_mp4)
                if cfg.verbose:
                    log(f"    ✓ done plain ({time.time() - t0:.2f}s)")
            except Exception as e:
                # ここで落ちると以降のスライドも止まるので、原因が分かるログを必ず出す
                log(f"    ❗ ERROR plain sent{sent_idx:02d}: {e}")
                raise
            continue

        # -----------------------------
        # アニメあり
        # -----------------------------
        if not isinstance(animate, dict):
            if cfg.verbose:
                log(f"  [skip] sent{sent_idx:02d}: animate is not dict (type={type(animate)})")
            continue

        rid = int(animate.get("region_id", -1))
        style = str(animate.get("style", "")).strip()
        params = animate.get("params", None)

        if cfg.styles_whitelist and style not in cfg.styles_whitelist:
            log(f"  [skip] sent{sent_idx:02d}: style not allowed: {style}")
            continue

        if rid < 0 or rid >= len(regions):
            log(f"  [skip] sent{sent_idx:02d}: invalid region id: {rid} (regions={len(regions)})")
            continue

        # coordinates が無い/形式違いでも落ちないように安全に取得
        region_obj = regions[rid]
        coords = region_obj.get("coordinates", None)
        if not isinstance(coords, list) or len(coords) < 4:
            log(f"  [skip] sent{sent_idx:02d}: region {rid} has no valid 'coordinates'")
            continue

        bbox = scaled_bbox_from_coords(coords, ref_size, to_size)

        out_mp4 = Path(str(out_base) + f"_{style}.mp4")

        if cfg.verbose:
            log(
                f"  ▶ sent{sent_idx:02d} anim: style={style} rid={rid} "
                f"bbox={bbox} audio={'yes' if (audio_path and audio_path.exists()) else 'no'} "
                f"-> {out_mp4.name}"
            )

        try:
            _call_anim(cfg, style, slide_png, bbox, audio_path, out_mp4, params)
            out_files.append(out_mp4)
            if cfg.verbose:
                log(f"    ✓ done anim ({time.time() - t0:.2f}s)")
        except Exception as e:
            log(f"    ❗ ERROR anim sent{sent_idx:02d} style={style} rid={rid}: {e}")
            raise

    return out_files


def build_all_slides_from_mappings(cfg: RunnerConfig) -> List[Path]:
    """
    mapping_dir 内の slide_XXX_mappings.json を全て走査して生成。
    """
    mapping_files = sorted(cfg.mapping_dir.glob("slide_*_mappings.json"))
    all_out: List[Path] = []

    log(f"Start. mapping_dir={cfg.mapping_dir} files={len(mapping_files)} out_dir={cfg.out_dir}")
    log(f"LP_dir={cfg.lp_dir} audio_root={cfg.audio_root} slide_img_dir={cfg.slide_img_dir}")
    log(f"ffmpeg_bin={cfg.ffmpeg_bin} plain_fps={cfg.plain_fps} fallback_sec={cfg.plain_fallback_sec}")

    for i, mp in enumerate(mapping_files, 1):
        m = re.search(r"slide_(\d{3})_mappings\.json", mp.name)
        if not m:
            log(f"[skip] unmatched mapping filename: {mp.name}")
            continue
        slide_str = m.group(1)
        log(f"=== ({i}/{len(mapping_files)}) processing slide {slide_str} ===")
        out = build_sentence_videos_from_mapping(cfg, slide_str)
        all_out.extend(out)
        log(f"=== slide {slide_str} done. generated={len(out)} (total={len(all_out)}) ===")

    log(f"Done. total_generated={len(all_out)} out_dir={cfg.out_dir}")
    return all_out


def run_from_mapping(paths: ProjectPaths) -> None:
    """
    Step4 エントリポイント。
    lp_dir は run_all がコピーした snapshot（outputs/<run>/LP_output）を参照する。
    """
    cfg = RunnerConfig(
        lp_dir=paths.lp_snapshot_dir,
        mapping_dir=paths.animation_output_dir,
        audio_root=paths.tts_output_dir,
        slide_img_dir=paths.img_root,
        out_dir=paths.add_animation_output_dir,
        # デフォルトで verbose on
        verbose=True,
    )

    build_all_slides_from_mappings(cfg)
