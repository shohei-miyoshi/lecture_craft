from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi.responses import FileResponse
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from .cache import (
    GenerateCachePlan,
    event_snapshot_path,
    research_snapshot_path,
    build_generate_cache_plan,
    decode_pdf_base64,
    get_named_lock,
    write_cached_generate_response,
)
from .models import ExportRequest, GenerateRequest, ResearchSessionRequest
from auto_lecture import config as auto_config
from auto_lecture.audio_only_lecture import run_audio_only_lecture
from auto_lecture.gpt_client import create_client
from auto_lecture.paths import ProjectPaths, build_paths
from auto_lecture.tts_simple import concat_mp3_with_ffmpeg, normalize_for_tts, tts_from_textfile
from auto_lecture.utils.pdf_utils import pdf_to_images


MATERIAL_ROOT = PROJECT_ROOT / "teachingmaterial"
PDF_ROOT = MATERIAL_ROOT / "pdf"
IMG_ROOT = MATERIAL_ROOT / "img"
PREVIEW_TTS_CACHE_ROOT = PROJECT_ROOT / "outputs" / "preview_tts_cache"

LEVEL_MAP = {"intro": "L1", "basic": "L2", "advanced": "L3"}
DETAIL_MAP = {"summary": "D1", "standard": "D2", "detail": "D3"}
FRONT_KIND_TO_BACK_STYLE = {
    "marker": "marker_highlight",
    "arrow": "arrow_point",
    "box": "laser_circle",
}
BACK_STYLE_TO_FRONT_KIND = {
    "marker_highlight": "marker",
    "arrow_point": "arrow",
    "laser_circle": "box",
}
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。．！？!?])\s*|\n+")
SLIDE_TEXT_COMMENT_RE = re.compile(r"^\s*#")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass
class SlideImageInfo:
    index: int
    path: Path
    width: int
    height: int


def generate_media(
    req: GenerateRequest,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> Dict[str, Any]:
    last_progress = [0]
    last_message = ["待機中"]

    def report(progress: int, message: str) -> None:
        last_progress[0] = progress
        last_message[0] = message
        if progress_callback is not None:
            progress_callback(progress, message)

    def check_cancel() -> None:
        if progress_callback is not None:
            progress_callback(last_progress[0], last_message[0])

    report(5, "生成計画を準備しています")
    level = LEVEL_MAP[req.difficulty]
    detail = DETAIL_MAP[req.detail]
    try:
        pdf_bytes = decode_pdf_base64(req.pdf_base64)
    except ValueError as exc:
        raise ApiError(400, "INVALID_PDF", str(exc)) from exc
    plan = build_generate_cache_plan(req, pdf_bytes)

    with get_named_lock(f"generate:{plan.request_key}"):
        material_name = plan.material_name
        output_root_name = plan.output_root_name

        report(12, "PDF をキャッシュに保存しています")
        ensure_pdf_upload(material_name, pdf_bytes)
        report(22, "スライド画像を準備しています")
        ensure_pdf_images(material_name)

        paths = build_paths(
            teaching_material_file_name=material_name,
            material_root=MATERIAL_ROOT,
            output_root_name=output_root_name,
        )

        if req.mode == "audio":
            report(35, "音声用の材料を準備しています")
            script_result = run_audio_only_lecture(
                paths=paths,
                level=level,
                detail=detail,
                do_stitch=True,
                shared_cache_dir=plan.audio_shared_cache_dir,
                material_workers=get_audio_material_worker_count(),
                progress_callback=report,
            )
            script_path = Path(script_result["script_path"])
            report(82, "音声を生成しています")
            ensure_audio_tts(script_path, paths)
            response = build_audio_generate_response(paths, script_result, req.mode, req.detail, req.difficulty)
        else:
            from scripts import run_all

            ensure_lp_outputs(paths, report)
            run_all.run_pipeline(
                teaching_material_file_name=material_name,
                material_root=MATERIAL_ROOT,
                level=level,
                detail=detail,
                output_root_name=output_root_name,
                progress_callback=report,
                cancel_checker=check_cancel,
            )
            report(90, "生成結果を整形しています")
            response = build_visual_generate_response(paths, req.mode, req.detail, req.difficulty)

        try:
            preview_audio_path = ensure_generated_preview_audio(paths)
        except Exception:
            preview_audio_path = None

        response = attach_generation_ref(response, plan, cache_hit=False)
        generation_ref = dict(response.get("generation_ref") or {})
        generation_ref.update(
            {
                "preview_audio_signature": build_preview_audio_signature(response.get("sentences", [])),
                "preview_audio_source_ready": preview_audio_path is not None,
            }
        )
        response["generation_ref"] = generation_ref
        write_cached_generate_response(plan, response)
        write_api_meta(
            paths,
            mode=req.mode,
            material_name=material_name,
            detail=req.detail,
            difficulty=req.difficulty,
            request_key=plan.request_key,
            pdf_hash=plan.pdf_hash,
        )
        report(100, "生成が完了しました")
        return response


def export_media(req: ExportRequest) -> FileResponse:
    export_type = req.type
    try:
        if export_type == "audio":
            out_path = export_audio(req)
            save_research_session_from_export(req, trigger=f"export_{export_type}", status="completed", output_path=out_path)
            log_export_event(req, status="completed", output_path=out_path)
            return FileResponse(out_path, media_type="audio/mpeg", filename="lecture.mp3")

        out_path = export_video(req, include_highlights=(export_type == "video_highlight"))
        save_research_session_from_export(req, trigger=f"export_{export_type}", status="completed", output_path=out_path)
        log_export_event(req, status="completed", output_path=out_path)
        return FileResponse(out_path, media_type="video/mp4", filename="lecture.mp4")
    except Exception as exc:
        save_research_session_from_export(req, trigger=f"export_{export_type}", status="failed", error_message=str(exc))
        log_export_event(req, status="failed", error_message=str(exc))
        raise


def export_audio(req: ExportRequest) -> Path:
    bundle = synthesize_audio_export_bundle(req, export_prefix="api_export_audio")
    return bundle["audio_path"]


def render_preview_audio(req: ExportRequest) -> Dict[str, Any]:
    bundle = synthesize_audio_export_bundle(req, export_prefix="api_preview_audio")
    return {
        "ok": True,
        "output_root_name": bundle["output_root_name"],
        "material_name": bundle["material_name"],
        "audio_filename": bundle["audio_path"].name,
        "sentences": bundle["sentences"],
        "total_duration": round(bundle["total_duration"], 3),
        "preview_audio_signature": build_preview_audio_signature(bundle["sentences"]),
    }


def synthesize_audio_export_bundle(req: ExportRequest, *, export_prefix: str) -> Dict[str, Any]:
    if not req.sentences:
        raise ApiError(400, "INVALID_REQUEST", "sentences is required for audio export")

    export_key = f"{export_prefix}_{timestamp_slug()}_{short_id()}"
    material_name = f"{export_key}.pdf"
    output_root_name = f"api_exports/{export_key}"
    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=MATERIAL_ROOT,
        output_root_name=output_root_name,
    )

    ordered = sorted(
        req.sentences,
        key=sentence_sort_key,
    )
    client = create_client()
    part_paths = resolve_cached_sentence_audio_files(client, ordered)
    timed_sentences, total_duration = build_audio_timeline_from_parts(ordered, part_paths)
    out_path = Path(paths.tts_output_dir) / "lecture_audio.mp3"
    concat_mp3_with_ffmpeg(part_paths, out_path)
    return {
        "audio_path": out_path,
        "sentences": timed_sentences,
        "total_duration": total_duration,
        "material_name": material_name,
        "output_root_name": output_root_name,
    }


def export_video(req: ExportRequest, include_highlights: bool) -> Path:
    from auto_lecture import add_animation_runner_from_mapping, lecture_concat

    if not req.sentences:
        raise ApiError(400, "INVALID_REQUEST", "sentences is required for video export")
    if not req.slides:
        raise ApiError(400, "INVALID_REQUEST", "slides is required for video export")

    export_key = f"api_export_video_{timestamp_slug()}_{short_id()}"
    material_name = f"{export_key}.pdf"
    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=MATERIAL_ROOT,
        output_root_name=f"api_exports/{export_key}",
    )

    slide_infos = write_slide_images_from_payload(req.slides, paths.img_root)
    grouped_sentences = group_sentences_by_slide(req.sentences, len(slide_infos))
    grouped_highlights = index_highlights_by_sentence(req.highlights)

    write_custom_lp_outputs(paths, slide_infos, grouped_sentences, grouped_highlights, include_highlights)
    write_custom_mapping_outputs(paths, grouped_sentences, grouped_highlights, include_highlights)

    client = create_client()
    for slide_idx, slide_sents in enumerate(grouped_sentences, start=1):
        slide_audio_dir = Path(paths.tts_output_dir) / f"page{slide_idx}"
        slide_audio_dir.mkdir(parents=True, exist_ok=True)
        synthesize_sentence_audio_files(client, slide_sents, slide_audio_dir)

    add_animation_runner_from_mapping.run_from_mapping(paths)
    final_video = lecture_concat.run_concat(paths)
    if final_video is None:
        raise ApiError(500, "EXPORT_FAILED", "video export did not produce an output file")
    return Path(final_video)


def build_visual_generate_response(
    paths: ProjectPaths,
    mode: str,
    detail: str,
    difficulty: str,
) -> Dict[str, Any]:
    slide_infos = load_slide_infos(paths.img_root)
    slides = build_frontend_slides(slide_infos, paths, mode, detail, difficulty)
    sentences, highlights, total_duration = parse_visual_outputs(paths, slide_infos)
    return {
        "slides": slides,
        "sentences": sentences,
        "highlights": highlights,
        "total_duration": round(total_duration, 3),
        "mode": mode,
    }


def build_audio_generate_response(
    paths: ProjectPaths,
    script_result: Dict[str, Any],
    mode: str,
    detail: str,
    difficulty: str,
) -> Dict[str, Any]:
    slide_infos = load_slide_infos(paths.img_root)
    slides = build_frontend_slides(slide_infos, paths, mode, detail, difficulty)
    mp3_path = find_first_file(paths.tts_output_dir, ("lecture_audio.mp3", "lecture_detailed.mp3", "lecture_standard.mp3", "lecture_summary.mp3"))
    if mp3_path is None:
        mp3_path = first_path_with_suffix(Path(paths.tts_output_dir), ".mp3")
    total_duration = probe_media_duration(mp3_path) if mp3_path else 0.0

    outline_path = Path(script_result["outline_json_path"])
    script_path = Path(script_result["script_path"])
    chapters = load_outline_chapters(outline_path)
    sentences = build_audio_sentences(script_path, chapters, total_duration)

    return {
        "slides": slides,
        "sentences": sentences,
        "highlights": [],
        "total_duration": round(total_duration or (sentences[-1]["end_sec"] if sentences else 0.0), 3),
        "mode": mode,
    }


def parse_visual_outputs(
    paths: ProjectPaths,
    slide_infos: Sequence[SlideImageInfo],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]:
    sentences: List[Dict[str, Any]] = []
    highlights: List[Dict[str, Any]] = []
    current_t = 0.0

    for slide_info in slide_infos:
        mapping_path = Path(paths.animation_output_dir) / f"slide_{slide_info.index + 1:03d}_mappings.json"
        lp_json_path = Path(paths.lp_snapshot_dir) / f"result_{slide_info.index + 1:03d}.json"
        if not lp_json_path.exists():
            lp_json_path = Path(paths.lp_dir) / f"result_{slide_info.index + 1:03d}.json"
        mapping = load_json_file(mapping_path, default={"sentences": []})
        regions = load_json_file(lp_json_path, default=[])

        for sent_idx, sent in enumerate(mapping.get("sentences", []), start=1):
            duration = probe_media_duration(Path(paths.tts_output_dir) / f"page{slide_info.index + 1}" / f"part{sent_idx:02d}.mp3")
            duration = duration or 2.0
            sent_id = f"s{len(sentences) + 1}"
            start_sec = current_t
            end_sec = current_t + duration
            current_t = end_sec
            sentences.append(
                {
                    "id": sent_id,
                    "slide_idx": slide_info.index,
                    "text": str(sent.get("text", "")).strip(),
                    "start_sec": round(start_sec, 3),
                    "end_sec": round(end_sec, 3),
                }
            )

            animate = sent.get("animate")
            if not isinstance(animate, dict):
                continue

            region_id = animate.get("region_id")
            if not isinstance(region_id, int):
                try:
                    region_id = int(region_id)
                except Exception:
                    continue
            if region_id < 0 or region_id >= len(regions):
                continue

            coords = regions[region_id].get("coordinates")
            if not isinstance(coords, list) or len(coords) < 4:
                continue

            x, y, w, h = xywh_percent_from_coords(coords, slide_info.width, slide_info.height)
            highlights.append(
                {
                    "id": f"h{len(highlights) + 1}",
                    "sid": sent_id,
                    "slide_idx": slide_info.index,
                    "kind": BACK_STYLE_TO_FRONT_KIND.get(str(animate.get("style", "")), "marker"),
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                }
            )

    return sentences, highlights, current_t


def build_audio_sentences(
    script_path: Path,
    chapters: Sequence[Dict[str, Any]],
    total_duration: float,
) -> List[Dict[str, Any]]:
    paragraphs = split_paragraphs(script_path.read_text(encoding="utf-8-sig"))
    sentence_rows: List[Dict[str, Any]] = []
    flat_sentences: List[Tuple[int, str]] = []

    for idx, paragraph in enumerate(paragraphs):
        chapter = chapters[idx] if idx < len(chapters) else {}
        target_slides = chapter.get("target_slides") or [1]
        slide_idx = max(0, int(target_slides[0]) - 1) if target_slides else 0
        for sent in split_sentences_text(paragraph):
            flat_sentences.append((slide_idx, sent))

    if not flat_sentences:
        return []

    weights = [max(1, len(text.replace(" ", ""))) for _, text in flat_sentences]
    total_weight = sum(weights)
    current_t = 0.0

    for i, ((slide_idx, text), weight) in enumerate(zip(flat_sentences, weights), start=1):
        duration = (total_duration * weight / total_weight) if total_duration > 0 else 3.0
        sentence_rows.append(
            {
                "id": f"s{i}",
                "slide_idx": slide_idx,
                "text": text,
                "start_sec": round(current_t, 3),
                "end_sec": round(current_t + duration, 3),
            }
        )
        current_t += duration

    if sentence_rows:
        sentence_rows[-1]["end_sec"] = round(total_duration or sentence_rows[-1]["end_sec"], 3)
    return sentence_rows


def build_frontend_slides(
    slide_infos: Sequence[SlideImageInfo],
    paths: ProjectPaths,
    mode: str,
    detail: str,
    difficulty: str,
) -> List[Dict[str, Any]]:
    slides: List[Dict[str, Any]] = []
    for slide in slide_infos:
        slides.append(
            {
                "id": f"sl{slide.index}",
                "title": guess_slide_title(paths, slide.index),
                "color": slide_color(slide.index),
                "image_base64": encode_file_base64(slide.path),
                "width": slide.width,
                "height": slide.height,
                "aspect_ratio": round(slide.width / max(slide.height, 1), 6),
                "backend_mode": mode,
                "backend_detail": detail,
                "backend_difficulty": difficulty,
            }
        )
    return slides


def write_custom_lp_outputs(
    paths: ProjectPaths,
    slide_infos: Sequence[SlideImageInfo],
    grouped_sentences: Sequence[Sequence[Dict[str, Any]]],
    highlight_by_sentence: Dict[str, Dict[str, Any]],
    include_highlights: bool,
) -> None:
    for slide_info in slide_infos:
        regions: List[Dict[str, Any]] = []
        slide_sentences = grouped_sentences[slide_info.index] if slide_info.index < len(grouped_sentences) else []

        if include_highlights:
            for sentence in slide_sentences:
                hl = highlight_by_sentence.get(str(sentence.get("id")))
                if not hl:
                    continue
                x1, y1, x2, y2 = coords_from_percent_highlight(hl, slide_info.width, slide_info.height)
                regions.append(
                    {
                        "id": len(regions),
                        "type": "Figure",
                        "coordinates": [x1, y1, x2, y2],
                        "score": 1.0,
                    }
                )

        out_path = Path(paths.lp_dir) / f"result_{slide_info.index + 1:03d}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(regions, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_path = Path(paths.lp_snapshot_dir) / f"result_{slide_info.index + 1:03d}.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(regions, ensure_ascii=False, indent=2), encoding="utf-8")


def write_custom_mapping_outputs(
    paths: ProjectPaths,
    grouped_sentences: Sequence[Sequence[Dict[str, Any]]],
    highlight_by_sentence: Dict[str, Dict[str, Any]],
    include_highlights: bool,
) -> None:
    for slide_idx, slide_sentences in enumerate(grouped_sentences, start=1):
        payload_sentences: List[Dict[str, Any]] = []
        region_idx = 0

        for sent_idx, sentence in enumerate(slide_sentences, start=1):
            animate = None
            if include_highlights:
                hl = highlight_by_sentence.get(str(sentence.get("id")))
                if hl:
                    animate = {
                        "region_id": region_idx,
                        "style": FRONT_KIND_TO_BACK_STYLE.get(str(hl.get("kind")), "marker_highlight"),
                        "reason": "frontend export highlight",
                    }
                    region_idx += 1

            payload_sentences.append(
                {
                    "sent_idx": sent_idx,
                    "text": str(sentence.get("text", "")).strip(),
                    "animate": animate,
                }
            )

        out_path = Path(paths.animation_output_dir) / f"slide_{slide_idx:03d}_mappings.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"slide": f"{slide_idx:03d}", "sentences": payload_sentences}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def synthesize_sentence_audio_files(
    client: Any,
    sentences: Sequence[Dict[str, Any]],
    out_dir: Path,
) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    part_paths: List[Path] = []
    for idx, sentence in enumerate(sentences, start=1):
        text = normalize_for_tts(str(sentence.get("text", "")).strip())
        if not text:
            raise ApiError(400, "INVALID_REQUEST", "sentence text must not be empty")
        out_path = out_dir / f"part{idx:02d}.mp3"
        synthesize_sentence_audio_to_path(client, text, out_path)
        part_paths.append(out_path)
    return part_paths


def build_sentence_audio_cache_key(text: str) -> str:
    payload = json.dumps(
        {
            "v": "preview_tts_cache_v1",
            "model": auto_config.API_TTS_MODEL,
            "voice": auto_config.API_TTS_VOICE,
            "speed": auto_config.API_TTS_VOICE_SPEED,
            "text": normalize_for_tts(text),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def synthesize_sentence_audio_to_path(client: Any, text: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with client.audio.speech.with_streaming_response.create(
        model=auto_config.API_TTS_MODEL,
        voice=auto_config.API_TTS_VOICE,
        input=text,
        response_format="mp3",
        speed=auto_config.API_TTS_VOICE_SPEED,
    ) as response:
        response.stream_to_file(out_path)


def resolve_cached_sentence_audio_files(
    client: Any,
    sentences: Sequence[Dict[str, Any]],
) -> List[Path]:
    PREVIEW_TTS_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    part_paths: List[Path] = []
    for sentence in sentences:
        text = normalize_for_tts(str(sentence.get("text", "")).strip())
        if not text:
            raise ApiError(400, "INVALID_REQUEST", "sentence text must not be empty")
        cache_key = build_sentence_audio_cache_key(text)
        cache_path = PREVIEW_TTS_CACHE_ROOT / f"{cache_key}.mp3"
        if not cache_path.exists():
            tmp_path = PREVIEW_TTS_CACHE_ROOT / f"{cache_key}.tmp.mp3"
            with get_named_lock(f"preview-tts:{cache_key}"):
                if not cache_path.exists():
                    synthesize_sentence_audio_to_path(client, text, tmp_path)
                    tmp_path.replace(cache_path)
            try:
                tmp_path.unlink(missing_ok=True)  # type: ignore[arg-type]
            except Exception:
                pass
        part_paths.append(cache_path)
    return part_paths


def build_audio_timeline_from_parts(
    sentences: Sequence[Dict[str, Any]],
    part_paths: Sequence[Path],
) -> Tuple[List[Dict[str, Any]], float]:
    timed_rows: List[Dict[str, Any]] = []
    current_t = 0.0

    for sentence, part_path in zip(sentences, part_paths):
        duration = probe_media_duration(part_path) or 0.0
        duration = max(0.05, float(duration))
        timed_rows.append(
            {
                "id": str(sentence.get("id", "")),
                "slide_idx": int(sentence.get("slide_idx", 0) or 0),
                "text": str(sentence.get("text", "")).strip(),
                "start_sec": round(current_t, 3),
                "end_sec": round(current_t + duration, 3),
            }
        )
        current_t += duration

    return timed_rows, current_t


def ensure_pdf_upload(material_name: str, pdf_bytes: bytes) -> Path:
    PDF_ROOT.mkdir(parents=True, exist_ok=True)
    pdf_path = PDF_ROOT / material_name
    if not pdf_path.exists():
        pdf_path.write_bytes(pdf_bytes)
    return pdf_path


def ensure_pdf_images(material_name: str) -> List[str]:
    pdf_path = PDF_ROOT / material_name
    img_dir = IMG_ROOT / material_name
    if img_dir.exists() and list(img_dir.glob("*.png")):
        return [str(path) for path in sorted(img_dir.glob("*.png"))]
    return pdf_to_images(str(pdf_path), str(img_dir), dpi=150)


def ensure_audio_tts(script_path: Path, paths: ProjectPaths) -> Path:
    out_path = Path(paths.tts_output_dir) / "lecture_audio.mp3"
    if out_path.exists():
        return out_path
    tts_from_textfile(text_file=script_path, paths=paths, mode="audio", fmt="mp3")
    return out_path


def build_preview_audio_signature(sentences: Sequence[Dict[str, Any]]) -> str:
    rows = []
    for sentence in sorted(sentences or [], key=sentence_sort_key):
        rows.append(
            [
                str(sentence.get("id", "")),
                str(sentence.get("text", "")).strip(),
            ]
        )
    return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))


def collect_generated_audio_parts(paths: ProjectPaths) -> List[Path]:
    tts_root = Path(paths.tts_output_dir)
    if not tts_root.exists():
        return []
    return sorted(tts_root.glob("page*/part*.mp3"))


def ensure_generated_preview_audio(paths: ProjectPaths) -> Optional[Path]:
    direct_path = find_first_file(
        Path(paths.tts_output_dir),
        ("lecture_audio.mp3", "lecture_detailed.mp3", "lecture_standard.mp3", "lecture_summary.mp3"),
    )
    if direct_path is not None and direct_path.exists():
        return direct_path

    preview_path = Path(paths.tts_output_dir) / "preview_source_audio.mp3"
    if preview_path.exists():
        return preview_path

    part_paths = collect_generated_audio_parts(paths)
    if not part_paths:
        return None
    concat_mp3_with_ffmpeg(part_paths, preview_path)
    return preview_path


def export_preview_audio_source(output_root_name: str, material_name: str) -> FileResponse:
    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=MATERIAL_ROOT,
        output_root_name=output_root_name,
    )
    outputs_root = (PROJECT_ROOT / "outputs").resolve()
    resolved_output_dir = Path(paths.output_dir).resolve()
    if resolved_output_dir != outputs_root and outputs_root not in resolved_output_dir.parents:
        raise ApiError(400, "INVALID_REQUEST", "output_root_name is invalid")

    audio_path = ensure_generated_preview_audio(paths)
    if audio_path is None or not audio_path.exists():
        raise ApiError(404, "PREVIEW_AUDIO_NOT_FOUND", "preview audio source not found")
    return FileResponse(audio_path, media_type="audio/mpeg", filename="preview_audio.mp3")


def lp_outputs_ready(paths: ProjectPaths) -> bool:
    slide_paths = sorted(Path(paths.img_root).glob("*.png"))
    if not slide_paths:
        return False
    for idx in range(1, len(slide_paths) + 1):
        if not (Path(paths.lp_dir) / f"result_{idx:03d}.json").exists():
            return False
    return True


def ensure_lp_outputs(
    paths: ProjectPaths,
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> None:
    def report(progress: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(progress, message)

    if lp_outputs_ready(paths):
        report(42, "既存のレイアウト解析結果を再利用しています")
        return

    from auto_lecture.lp_processor import process_slides_with_lp

    report(40, "レイアウト解析を実行しています")
    process_slides_with_lp(paths)


def get_audio_material_worker_count() -> int:
    try:
        return max(1, int(getattr(auto_config, "AUDIO_MATERIAL_MAX_WORKERS", 3)))
    except Exception:
        return 1


def write_slide_images_from_payload(slides: Sequence[Dict[str, Any]], out_dir: Path) -> List[SlideImageInfo]:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    infos: List[SlideImageInfo] = []

    for idx, slide in enumerate(slides, start=1):
        image_b64 = slide.get("image_base64")
        if not image_b64:
            raise ApiError(400, "INVALID_REQUEST", "all slides must include image_base64 for video export")
        img_path = out_dir / f"{idx:03d}.png"
        try:
            img_path.write_bytes(base64.b64decode(image_b64))
        except Exception as exc:
            raise ApiError(400, "INVALID_REQUEST", "slide image_base64 could not be decoded") from exc
        with Image.open(img_path) as im:
            infos.append(SlideImageInfo(index=idx - 1, path=img_path, width=im.width, height=im.height))
    return infos


def load_slide_infos(img_root: Path) -> List[SlideImageInfo]:
    infos: List[SlideImageInfo] = []
    for idx, path in enumerate(sorted(img_root.glob("*.png"))):
        with Image.open(path) as im:
            infos.append(SlideImageInfo(index=idx, path=path, width=im.width, height=im.height))
    return infos


def group_sentences_by_slide(sentences: Sequence[Dict[str, Any]], slide_count: int) -> List[List[Dict[str, Any]]]:
    grouped: List[List[Dict[str, Any]]] = [[] for _ in range(slide_count)]
    for sentence in sorted(sentences, key=sentence_sort_key):
        slide_idx = int(sentence.get("slide_idx", 0) or 0)
        slide_idx = min(max(slide_idx, 0), max(slide_count - 1, 0))
        grouped[slide_idx].append(sentence)
    return grouped


def index_highlights_by_sentence(highlights: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(hl.get("sid")): hl for hl in highlights if hl.get("sid")}


def load_outline_chapters(outline_path: Path) -> List[Dict[str, Any]]:
    data = load_json_file(outline_path, default={})
    chapters = data.get("chapters")
    return chapters if isinstance(chapters, list) else []


def guess_slide_title(paths: ProjectPaths, slide_index: int) -> str:
    mapping_path = Path(paths.animation_output_dir) / f"slide_{slide_index + 1:03d}_mappings.json"
    mapping = load_json_file(mapping_path, default={})
    mapping_sentences = mapping.get("sentences")
    if isinstance(mapping_sentences, list) and mapping_sentences:
        text = str(mapping_sentences[0].get("text", "")).strip()
        if text:
            return shorten_title(text)

    slide_txt_path = Path(paths.explanation_save_dir) / f"slide_{slide_index + 1:03d}.txt"
    if slide_txt_path.exists():
        for line in slide_txt_path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or SLIDE_TEXT_COMMENT_RE.match(line):
                continue
            return shorten_title(line.strip())

    return f"スライド {slide_index + 1}"


def shorten_title(text: str, limit: int = 24) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "…"


def split_paragraphs(text: str) -> List[str]:
    blocks = re.split(r"\n\s*\n+", text.replace("\r\n", "\n").replace("\r", "\n"))
    return [block.strip() for block in blocks if block.strip()]


def split_sentences_text(text: str) -> List[str]:
    chunks = [chunk.strip() for chunk in SENTENCE_SPLIT_RE.split(text) if chunk and chunk.strip()]
    return chunks


def sentence_sort_key(sentence: Dict[str, Any]) -> Tuple[int, float, str]:
    slide_idx = int(sentence.get("slide_idx", 0) or 0)
    start_sec = float(sentence.get("start_sec", 0) or 0)
    sent_id = str(sentence.get("id", ""))
    return slide_idx, start_sec, sent_id


def find_first_file(root: Path, names: Iterable[str]) -> Optional[Path]:
    for name in names:
        p = Path(root) / name
        if p.exists():
            return p
    return None


def first_path_with_suffix(root: Path, suffix: str) -> Optional[Path]:
    if not Path(root).exists():
        return None
    for path in sorted(Path(root).rglob(f"*{suffix}")):
        if path.is_file():
            return path
    return None


def load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def probe_media_duration(path: Optional[Path]) -> float:
    if path is None or not Path(path).exists():
        return 0.0
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return 0.0
    try:
        return float(proc.stdout.strip())
    except Exception:
        return 0.0


def encode_file_base64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def slide_color(index: int) -> str:
    colors = ["#1a2340", "#1f2d1f", "#2d1f1f", "#1f1f2d", "#2d2820", "#203047", "#2a2337"]
    return colors[index % len(colors)]


def attach_generation_ref(
    response: Dict[str, Any],
    plan: GenerateCachePlan,
    *,
    cache_hit: bool,
) -> Dict[str, Any]:
    payload = dict(response)
    generation_ref = dict(payload.get("generation_ref") or {})
    generation_ref.update(
        {
            "cache_key": plan.request_key,
            "pdf_hash": plan.pdf_hash,
            "material_name": plan.material_name,
            "output_root_name": plan.output_root_name,
            "cache_hit": cache_hit,
        }
    )
    payload["generation_ref"] = generation_ref
    return payload


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def short_id() -> str:
    return uuid.uuid4().hex[:8]


def xywh_percent_from_coords(coords: Sequence[Any], width: int, height: int) -> Tuple[int, int, int, int]:
    x1 = float(coords[0])
    y1 = float(coords[1])
    x2 = float(coords[2])
    y2 = float(coords[3])
    x = round((x1 / max(width, 1)) * 100)
    y = round((y1 / max(height, 1)) * 100)
    w = round(((x2 - x1) / max(width, 1)) * 100)
    h = round(((y2 - y1) / max(height, 1)) * 100)
    return int(x), int(y), max(1, int(w)), max(1, int(h))


def coords_from_percent_highlight(hl: Dict[str, Any], width: int, height: int) -> Tuple[int, int, int, int]:
    x = float(hl.get("x", 0))
    y = float(hl.get("y", 0))
    w = float(hl.get("w", 1))
    h = float(hl.get("h", 1))
    x1 = round(width * x / 100.0)
    y1 = round(height * y / 100.0)
    x2 = round(width * (x + w) / 100.0)
    y2 = round(height * (y + h) / 100.0)
    return int(x1), int(y1), max(int(x1 + 1), int(x2)), max(int(y1 + 1), int(y2))


def write_api_meta(
    paths: ProjectPaths,
    *,
    mode: str,
    material_name: str,
    detail: str,
    difficulty: str,
    request_key: Optional[str] = None,
    pdf_hash: Optional[str] = None,
) -> None:
    meta = {
        "mode": mode,
        "material_name": material_name,
        "detail": detail,
        "difficulty": difficulty,
        "request_key": request_key,
        "pdf_hash": pdf_hash,
        "output_dir": str(paths.output_dir),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    meta_path = Path(paths.output_dir) / "api_meta.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def log_export_event(
    req: ExportRequest,
    *,
    status: str,
    output_path: Optional[Path] = None,
    error_message: Optional[str] = None,
) -> None:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "export_type": req.type,
        "mode": req.mode,
        "source_cache_key": req.source_cache_key,
        "source_material_name": req.source_material_name,
        "source_output_root_name": req.source_output_root_name,
        "session_id": req.session_id,
        "slide_count": len(req.slides),
        "sentence_count": len(req.sentences),
        "highlight_count": len(req.highlights),
        "operation_log_count": len(req.operation_logs),
        "research_summary": req.research.get("summary") if isinstance(req.research, dict) else {},
        "output_path": str(output_path) if output_path else None,
        "error_message": error_message,
    }
    try:
        path = event_snapshot_path("export")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def save_research_session(req: ResearchSessionRequest) -> Dict[str, Any]:
    session_id = str(req.session_id or f"session_{timestamp_slug()}_{short_id()}")
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "trigger": req.trigger,
        "mode": req.mode,
        "generation_ref": req.generation_ref,
        "settings": req.settings,
        "operation_logs": req.operation_logs,
        "research": req.research,
    }
    path = research_snapshot_path(session_id, req.trigger)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "session_id": session_id,
        "snapshot_path": str(path),
        "summary": req.research.get("summary") if isinstance(req.research, dict) else {},
    }


def save_research_session_from_export(
    req: ExportRequest,
    *,
    trigger: str,
    status: str,
    output_path: Optional[Path] = None,
    error_message: Optional[str] = None,
) -> None:
    if not req.research and not req.operation_logs:
        return
    try:
        save_research_session(
            ResearchSessionRequest(
                session_id=req.session_id,
                trigger=trigger,
                mode=req.mode,
                generation_ref=req.generation_ref or {
                    "cache_key": req.source_cache_key,
                    "material_name": req.source_material_name,
                    "output_root_name": req.source_output_root_name,
                },
                operation_logs=req.operation_logs,
                research={
                    **(req.research or {}),
                    "export": {
                        "type": req.type,
                        "status": status,
                        "output_path": str(output_path) if output_path else None,
                        "error_message": error_message,
                    },
                },
                settings=req.settings.model_dump(),
            )
        )
    except Exception:
        pass
