from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from .cache import (
    GenerateCachePlan,
    build_generate_cache_plan,
    get_named_lock,
    load_cached_generate_response,
    write_cached_generate_response,
)
from .db import db_conn, json_text
from .models import ExportRequest, GenerateRequest, PreviewAudioRequest, ResearchSessionRequest, ReviewAssignmentRequest
from .storage import get_artifact_store
from auto_lecture import config as auto_config
from auto_lecture.audio_only_lecture import run_audio_only_lecture
from auto_lecture.gpt_client import create_client
from auto_lecture.gpt_utils import (
    build_responses_system_message,
    build_responses_user_message,
    call_responses_text,
)
from .preference_memory import consolidate_preferences
from auto_lecture.paths import ProjectPaths, build_paths
from auto_lecture.tts_simple import clean_script_text, concat_mp3_with_ffmpeg, normalize_for_tts
from auto_lecture.utils.pdf_utils import pdf_to_images


PREVIEW_CLIP_MANIFEST = "manifest.json"

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
PREVIEW_AUDIO_VERSION = "preview_audio_v1"
VALID_KG_MODES = {"off", "slide", "global", "global_slide"}
LOGGER = logging.getLogger(__name__)
_PREVIEW_CACHE_PRUNE_LOCK = threading.Lock()
_PREVIEW_CACHE_LAST_PRUNE = 0.0
_PREVIEW_CACHE_PRUNE_INTERVAL_SECONDS = 60 * 60


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


def _preview_clip_root() -> Path:
    return get_artifact_store().cache_root / "preview_audio" / "clips"


def generate_media(
    req: GenerateRequest,
    *,
    pdf_bytes: bytes,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    partial_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
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
    plan = build_generate_cache_plan(req, pdf_bytes)

    with get_named_lock(f"generate:{plan.request_key}"):
        cached_response = load_cached_generate_response(plan)
        if cached_response is not None:
            report(100, "キャッシュ済みの生成結果を読み込みました")
            return attach_generation_ref(cached_response, plan, cache_hit=True)

        material_name = plan.material_name
        output_root_name = plan.output_root_name

        report(12, "PDF を作業領域に準備しています")
        ensure_pdf_upload(material_name, pdf_bytes, material_root=plan.material_root)
        report(22, "スライド画像を準備しています")
        ensure_pdf_images(material_name, material_root=plan.material_root)

        paths = build_paths(
            teaching_material_file_name=material_name,
            material_root=plan.material_root,
            output_root_name=output_root_name,
        )
        conditions = normalize_generation_conditions(req.generation_conditions)
        if conditions.get("kg_mode") != "off":
            report(28, "台本生成前のナレッジグラフを構築しています")
            ensure_pre_generation_knowledge_graph(paths, kg_mode=conditions["kg_mode"])
        write_research_generation_context(paths, req)

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
            report(82, "音声用の台本を整形しています")
            response = build_audio_generate_response(paths, script_result, req.mode, req.detail, req.difficulty)
        else:
            from scripts import run_all

            ensure_lp_outputs(paths, report)
            layout_review_requested = bool(req.layout_review_enabled)
            script_review_requested = bool(req.script_review_enabled or req.interactive_review_enabled)
            if layout_review_requested and partial_callback is not None:
                layout_response = build_layout_review_generate_response(
                    paths,
                    req.mode,
                    req.detail,
                    req.difficulty,
                )
                partial_callback("layout_ready", layout_response)
            if layout_review_requested:
                run_all.run_pipeline(
                    teaching_material_file_name=material_name,
                    material_root=plan.material_root,
                    level=level,
                    detail=detail,
                    output_root_name=output_root_name,
                    progress_callback=report,
                    cancel_checker=check_cancel,
                    stop_before="animation",
                )
                report(90, "台本生成結果を整形しています")
                response = build_visual_script_review_response(paths, req.mode, req.detail, req.difficulty)
            elif script_review_requested:
                run_all.run_pipeline(
                    teaching_material_file_name=material_name,
                    material_root=plan.material_root,
                    level=level,
                    detail=detail,
                    output_root_name=output_root_name,
                    progress_callback=report,
                    cancel_checker=check_cancel,
                    stop_before="animation",
                )
                report(90, "台本生成結果を整形しています")
                response = build_visual_script_review_response(paths, req.mode, req.detail, req.difficulty)
            else:
                run_all.run_pipeline(
                    teaching_material_file_name=material_name,
                    material_root=plan.material_root,
                    level=level,
                    detail=detail,
                    output_root_name=output_root_name,
                    progress_callback=report,
                    cancel_checker=check_cancel,
                )
                report(90, "生成結果を整形しています")
                response = build_visual_generate_response(paths, req.mode, req.detail, req.difficulty)

        response = attach_generation_ref(response, plan, cache_hit=False)
        response = attach_research_generation_outputs(response, req, plan)
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


def build_audio_preview(
    req: PreviewAudioRequest,
    *,
    owner_user_id: Optional[str],
    owner_session_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    if req.project_id or req.run_id:
        if not req.project_id or not req.run_id or not owner_user_id:
            raise ApiError(400, "PREVIEW_PROJECT_CONTEXT_INVALID", "project_idとrun_idを両方指定してください。")
        from .storage_persistence import assert_preview_audio_input_current

        assert_preview_audio_input_current(
            project_id=req.project_id,
            run_id=req.run_id,
            user_id=owner_user_id,
            scope=req.scope,
            sentences=req.sentences,
        )
    _maybe_prune_preview_audio_cache()
    ordered = sorted(
        [sentence for sentence in req.sentences if str(sentence.get("text", "")).strip()],
        key=lambda sentence: (float(sentence.get("start_sec", 0) or 0), str(sentence.get("id", ""))),
    )
    if not ordered:
        raise ApiError(400, "INVALID_REQUEST", "sentences is required for audio preview")

    client_ref: Dict[str, Any] = {"client": None}
    sentence_entries: List[Dict[str, Any]] = []
    sentence_keys: List[str] = []
    sentence_cache_hits = 0
    for sentence in ordered:
        entry = ensure_preview_sentence_audio(client_ref, sentence)
        sentence_entries.append(entry)
        sentence_keys.append(entry["sentence_key"])
        if entry["cache_hit"]:
            sentence_cache_hits += 1

    clip_key = _preview_clip_key(sentence_keys)
    preview_id = f"pa_{clip_key[:24]}"
    clip_dir = _preview_clip_root() / preview_id
    clip_path = clip_dir / "preview.mp3"
    clip_cache_hit = clip_path.exists()

    with get_named_lock(f"preview_clip:{clip_key}"):
        if not clip_path.exists():
            clip_dir.mkdir(parents=True, exist_ok=True)
            part_paths = [Path(entry["path"]) for entry in sentence_entries]
            if len(part_paths) == 1:
                shutil.copy2(part_paths[0], clip_path)
            else:
                concat_mp3_with_ffmpeg(part_paths, clip_path)
            clip_cache_hit = False
        _grant_preview_clip_access(
            clip_dir,
            clip_key=clip_key,
            owner_user_id=owner_user_id,
            owner_session_id=owner_session_id,
        )
        _register_cache_entry(
            cache_key=f"preview_clip:{clip_key}",
            cache_kind="preview_audio_clip",
            path=clip_path,
            metadata={
                "sentence_keys": sentence_keys,
                "sentence_count": len(sentence_keys),
            },
            cache_hit=clip_cache_hit,
        )

    sentence_timings = _build_preview_sentence_timings(ordered, sentence_entries)
    duration = probe_media_duration(clip_path)
    if duration <= 0 and sentence_timings:
        duration = max(float(row.get("local_end_sec", 0) or 0) for row in sentence_timings)
    persisted_audio = None
    if req.project_id or req.run_id:
        from .storage_persistence import (
            assert_preview_audio_input_current,
            publish_preview_audio_result,
        )

        assert_preview_audio_input_current(
            project_id=req.project_id,
            run_id=req.run_id,
            user_id=owner_user_id,
            scope=req.scope,
            sentences=req.sentences,
        )

        persisted_audio = publish_preview_audio_result(
            project_id=req.project_id,
            run_id=req.run_id,
            user_id=owner_user_id,
            job_id=job_id,
            preview_id=preview_id,
            clip_path=clip_path,
            cache_key=clip_key,
            scope=req.scope,
            duration=round(duration, 3),
            sentence_timings=sentence_timings,
            clip_cache_hit=clip_cache_hit,
            sentence_cache_hits=sentence_cache_hits,
            sentence_count=len(ordered),
        )

    if persisted_audio:
        return persisted_audio["result"]
    return {
        "preview_id": preview_id,
        "audio_url": f"/api/preview/audio/{preview_id}/media",
        "audio_artifact_id": None,
        "audio_manifest_artifact_id": None,
        "duration": round(duration, 3),
        "sentence_timings": sentence_timings,
        "cache_hit": bool(clip_cache_hit),
        "sentence_cache_hits": sentence_cache_hits,
        "sentence_count": len(ordered),
        "stale_key": clip_key,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def preview_audio_request_key(req: PreviewAudioRequest) -> str:
    ordered = sorted(
        [sentence for sentence in req.sentences if str(sentence.get("text", "")).strip()],
        key=lambda sentence: (float(sentence.get("start_sec", 0) or 0), str(sentence.get("id", ""))),
    )
    payload = {
        "v": f"{PREVIEW_AUDIO_VERSION}_job_v1",
        "project_id": req.project_id,
        "run_id": req.run_id,
        "scope": req.scope,
        "slide_idx": req.slide_idx,
        "sentences": [
            {
                "id": sentence.get("id"),
                "slide_idx": sentence.get("slide_idx"),
                "text": str(sentence.get("text", "")).strip(),
                "start_sec": sentence.get("start_sec"),
                "end_sec": sentence.get("end_sec"),
            }
            for sentence in ordered
        ],
        "model": auto_config.API_TTS_MODEL,
        "voice": auto_config.API_TTS_VOICE,
        "speed": auto_config.API_TTS_VOICE_SPEED,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def create_final_render_preview(req: ExportRequest, *, job_id: str, workspace: Path) -> Dict[str, Any]:
    if req.type not in {"video", "video_highlight"}:
        raise ApiError(400, "INVALID_REQUEST", "final render preview requires video or video_highlight")
    out_path = export_video(
        req,
        include_highlights=(req.type == "video_highlight"),
        workspace=workspace,
    )
    return {
        "preview_id": job_id,
        "media_type": "video/mp4",
        "media_url": f"/api/preview/final-render/{job_id}/media",
        "media_path": str(out_path),
        "filename": "lecture_final_preview.mp4",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def generate_review_assignment(req: ReviewAssignmentRequest, *, workspace: Path) -> Dict[str, Any]:
    """
    人手確認済みの領域と台本を使って、ここで初めて台本-領域対応を生成する。

    レビューあり生成では run_all を stop_before="animation" で止めるため、
    この関数が対応付け以降の入口になる。
    """
    from auto_lecture import animation_assignment

    material_name = str((req.generation_ref or {}).get("material_name") or "").strip()
    if not material_name:
        raise ApiError(400, "INVALID_REQUEST", "generation_ref.material_name is required")

    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=Path(workspace) / "material",
        output_root_name=str(Path(workspace) / "assignment_pipeline"),
    )
    slide_infos = load_slide_infos(paths.img_root)
    if not slide_infos:
        raise ApiError(404, "GENERATION_NOT_FOUND", "slide images for this generation were not found")

    grouped_sentences = group_sentences_by_slide(req.sentences, len(slide_infos))
    grouped_highlights = group_highlights_by_slide(req.highlights, len(slide_infos))
    assignment_input_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
    assignment_input_root = Path(paths.output_dir) / "review_assignment_inputs" / assignment_input_id
    region_maps = write_reviewed_lp_outputs(
        paths,
        slide_infos,
        grouped_highlights,
        output_dir=assignment_input_root / "LP_output",
    )
    write_reviewed_script_outputs(
        grouped_sentences,
        output_dir=assignment_input_root / "lecture_texts",
    )

    reviewed_highlights = build_assignment_highlight_seed(req.highlights)
    assignment_mappings: List[Dict[str, Any]] = []
    system_msg = animation_assignment.build_responses_system_message(animation_assignment.build_system_message())
    try:
        client = create_client()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        print(f"[review-assignment] OpenAI client setup failed: {detail}", file=sys.stderr)
        raise ApiError(502, "ASSIGNMENT_CLIENT_SETUP_FAILED", detail) from exc

    for slide_info in slide_infos:
        slide_str = f"{slide_info.index + 1:03d}"
        slide_sents = grouped_sentences[slide_info.index] if slide_info.index < len(grouped_sentences) else []
        sent_texts = [str(sentence.get("text", "")).strip() for sentence in slide_sents if str(sentence.get("text", "")).strip()]
        regions = region_maps[slide_info.index] if slide_info.index < len(region_maps) else []
        overview_path, region_imgs = build_reviewed_region_visuals(
            slide_info,
            regions,
            output_dir=assignment_input_root / "region_visuals",
            slide_str=slide_str,
        )

        if not slide_sents:
            mapping = {"slide": slide_str, "sentences": []}
        elif not regions:
            mapping = {
                "slide": slide_str,
                "sentences": [
                    {"sent_idx": idx, "text": str(sentence.get("text", "")).strip(), "animate": None}
                    for idx, sentence in enumerate(slide_sents, start=1)
                ],
            }
        else:
            try:
                mapping = animation_assignment.generate_mapping_for_slide(
                    client,
                    system_msg=system_msg,
                    slide_str=slide_str,
                    slide_image_path=slide_info.path,
                    regions_json=[row["region"] for row in regions],
                    region_imgs=region_imgs,
                    region_overview_path=overview_path,
                    script_full="\n".join(sent_texts),
                    sentences=[str(sentence.get("text", "")).strip() for sentence in slide_sents],
                )
            except Exception as exc:
                detail = f"slide {slide_str}: {type(exc).__name__}: {exc}"
                print(f"[review-assignment] assignment generation failed: {detail}", file=sys.stderr)
                raise ApiError(
                    502,
                    "ASSIGNMENT_GENERATION_FAILED",
                    detail,
                ) from exc

        animation_assignment.save_mapping_outputs(paths, slide_str, mapping)
        assignment_mappings.append(mapping)
        apply_assignment_mapping_to_highlights(
            reviewed_highlights,
            mapping,
            slide_sents,
            regions,
        )

    highlights = finalize_assignment_highlights(reviewed_highlights)
    total_duration = max(
        [safe_float(sentence.get("end_sec"), 0.0) for sentence in req.sentences if isinstance(sentence, dict)] or [0.0]
    )
    return {
        "ok": True,
        "pipeline_stage": "assignment_ready",
        "generation_ref": req.generation_ref,
        "sentences": req.sentences,
        "highlights": highlights,
        "assignment_mappings": assignment_mappings,
        "assignment_input_id": assignment_input_id,
        "total_duration": round(total_duration, 3),
    }


def export_video(
    req: ExportRequest,
    include_highlights: bool,
    *,
    workspace: Path,
) -> Path:
    from auto_lecture import add_animation_runner_from_mapping, lecture_concat

    if not req.sentences:
        raise ApiError(400, "INVALID_REQUEST", "sentences is required for video export")
    if not req.slides:
        raise ApiError(400, "INVALID_REQUEST", "slides is required for video export")

    export_key = f"api_export_video_{timestamp_slug()}_{short_id()}"
    material_name = f"{export_key}.pdf"
    material_root = Path(workspace) / "material"
    output_root_name = str(Path(workspace) / "pipeline")
    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=material_root,
        output_root_name=output_root_name,
    )

    slide_infos = write_slide_images_from_payload(req.slides, paths.img_root)
    grouped_sentences = group_sentences_by_slide(req.sentences, len(slide_infos))
    grouped_highlights = index_highlights_by_sentence(req.highlights)

    write_custom_lp_outputs(paths, slide_infos, grouped_sentences, grouped_highlights, include_highlights)
    write_custom_mapping_outputs(paths, grouped_sentences, grouped_highlights, include_highlights)

    client_ref: Dict[str, Any] = {"client": None}
    for slide_idx, slide_sents in enumerate(grouped_sentences, start=1):
        slide_audio_dir = Path(paths.tts_output_dir) / f"page{slide_idx}"
        slide_audio_dir.mkdir(parents=True, exist_ok=True)
        for sentence_idx, sentence in enumerate(slide_sents, start=1):
            entry = ensure_preview_sentence_audio(client_ref, sentence)
            shutil.copy2(entry["path"], slide_audio_dir / f"part{sentence_idx:02d}.mp3")

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


def build_visual_script_review_response(
    paths: ProjectPaths,
    mode: str,
    detail: str,
    difficulty: str,
) -> Dict[str, Any]:
    slide_infos = load_slide_infos(paths.img_root)
    slides = build_frontend_slides(slide_infos, paths, mode, detail, difficulty)
    sentences, total_duration = build_visual_script_sentences(paths, slide_infos)
    highlights = build_layout_review_highlights(paths, slide_infos) if mode == "hl" else []
    return {
        "slides": slides,
        "sentences": sentences,
        "highlights": highlights,
        "total_duration": round(total_duration, 3),
        "mode": mode,
        "pipeline_stage": "script_ready",
    }


def build_layout_review_generate_response(
    paths: ProjectPaths,
    mode: str,
    detail: str,
    difficulty: str,
) -> Dict[str, Any]:
    slide_infos = load_slide_infos(paths.img_root)
    slides = build_frontend_slides(slide_infos, paths, mode, detail, difficulty)
    highlights = build_layout_review_highlights(paths, slide_infos)
    return {
        "slides": slides,
        "sentences": [],
        "highlights": highlights,
        "total_duration": 0,
        "mode": mode,
        "generated": False,
        "partial_stage": "layout_ready",
        "pipeline_stage": "layout_ready",
    }


def build_layout_review_highlights(
    paths: ProjectPaths,
    slide_infos: Sequence[SlideImageInfo],
) -> List[Dict[str, Any]]:
    highlights: List[Dict[str, Any]] = []
    for slide_info in slide_infos:
        lp_json_path = Path(paths.lp_dir) / f"result_{slide_info.index + 1:03d}.json"
        regions = load_json_file(lp_json_path, default=[])
        if not isinstance(regions, list):
            continue
        for region_idx, region in enumerate(regions):
            coords = region.get("coordinates") if isinstance(region, dict) else None
            if not isinstance(coords, list) or len(coords) < 4:
                continue
            x, y, w, h = xywh_percent_from_coords(coords, slide_info.width, slide_info.height)
            highlights.append(
                {
                    "id": f"lp_s{slide_info.index + 1:03d}_r{region_idx}",
                    "slide_idx": slide_info.index,
                    "kind": "marker",
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "sentence_ids": [],
                    "source": "layout_parser",
                    "region_id": region.get("id", region_idx) if isinstance(region, dict) else region_idx,
                    "region_type": region.get("type") if isinstance(region, dict) else None,
                    "score": region.get("score") if isinstance(region, dict) else None,
                }
            )
    return highlights


def build_visual_script_sentences(
    paths: ProjectPaths,
    slide_infos: Sequence[SlideImageInfo],
) -> Tuple[List[Dict[str, Any]], float]:
    sentences: List[Dict[str, Any]] = []
    current_t = 0.0
    for slide_info in slide_infos:
        slide_txt_path = Path(paths.explanation_save_dir) / f"slide_{slide_info.index + 1:03d}.txt"
        if not slide_txt_path.exists():
            continue
        text = slide_txt_path.read_text(encoding="utf-8-sig")
        for sentence_text in split_sentences_text(text):
            clean_text = sentence_text.strip()
            if not clean_text:
                continue
            duration = estimate_sentence_duration(clean_text)
            sent_id = f"s{len(sentences) + 1}"
            sentences.append(
                {
                    "id": sent_id,
                    "slide_idx": slide_info.index,
                    "text": clean_text,
                    "start_sec": round(current_t, 3),
                    "end_sec": round(current_t + duration, 3),
                }
            )
            current_t += duration
    return sentences, current_t


def estimate_sentence_duration(text: str) -> float:
    compact = re.sub(r"\s+", "", text)
    return round(max(2.0, min(12.0, len(compact) / 9.0)), 3)


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
        with client.audio.speech.with_streaming_response.create(
            model=auto_config.API_TTS_MODEL,
            voice=auto_config.API_TTS_VOICE,
            input=text,
            response_format="mp3",
            speed=auto_config.API_TTS_VOICE_SPEED,
        ) as response:
            response.stream_to_file(out_path)
        part_paths.append(out_path)
    return part_paths


def ensure_preview_sentence_audio(client_ref: Dict[str, Any], sentence: Dict[str, Any]) -> Dict[str, Any]:
    text = normalize_for_tts(str(sentence.get("text", "")).strip())
    if not text:
        raise ApiError(400, "INVALID_REQUEST", "sentence text must not be empty")
    sentence_key = _preview_sentence_key(text)
    out_path = get_artifact_store().tts_cache_path(sentence_key)
    out_dir = out_path.parent
    cache_hit = out_path.exists()
    with get_named_lock(f"preview_sentence:{sentence_key}"):
        if not out_path.exists():
            if client_ref.get("client") is None:
                client_ref["client"] = create_client()
            client = client_ref["client"]
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = out_dir / f"sentence_{uuid.uuid4().hex[:8]}.tmp.mp3"
            with client.audio.speech.with_streaming_response.create(
                model=auto_config.API_TTS_MODEL,
                voice=auto_config.API_TTS_VOICE,
                input=text,
                response_format="mp3",
                speed=auto_config.API_TTS_VOICE_SPEED,
            ) as response:
                response.stream_to_file(tmp_path)
            tmp_path.replace(out_path)
            cache_hit = False
    _register_cache_entry(
        cache_key=f"tts:{sentence_key}",
        cache_kind="tts_sentence",
        path=out_path,
        metadata={
            "model": auto_config.API_TTS_MODEL,
            "voice": auto_config.API_TTS_VOICE,
            "speed": auto_config.API_TTS_VOICE_SPEED,
            "language": "ja",
        },
        cache_hit=cache_hit,
    )
    duration = probe_media_duration(out_path)
    return {
        "sentence_key": sentence_key,
        "path": str(out_path),
        "duration": duration,
        "cache_hit": cache_hit,
    }


def get_audio_preview_media_path(
    preview_id: str,
    *,
    requester_user_id: Optional[str],
    requester_session_id: Optional[str] = None,
) -> Path:
    safe_id = _safe_preview_id(preview_id)
    clip_dir = _preview_clip_root() / safe_id
    path = clip_dir / "preview.mp3"
    if not path.exists():
        raise ApiError(404, "PREVIEW_AUDIO_NOT_FOUND", "音声プレビューが見つかりません。")
    manifest = _load_preview_clip_manifest(clip_dir)
    owner_user_ids = {str(value) for value in manifest.get("owner_user_ids", []) if value}
    owner_session_ids = {str(value) for value in manifest.get("owner_session_ids", []) if value}
    if requester_user_id not in owner_user_ids and requester_session_id not in owner_session_ids:
        raise ApiError(403, "PREVIEW_AUDIO_FORBIDDEN", "この音声プレビューを取得する権限がありません。")
    clip_key = str(manifest.get("clip_key") or "")
    if clip_key:
        with db_conn() as conn:
            conn.execute(
                """
                UPDATE cache_entries
                SET hit_count = hit_count + 1, last_accessed_at = :last_accessed_at
                WHERE cache_key = :cache_key
                """,
                {
                    "cache_key": f"preview_clip:{clip_key}",
                    "last_accessed_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
    return path


def _load_preview_clip_manifest(clip_dir: Path) -> Dict[str, Any]:
    manifest_path = clip_dir / PREVIEW_CLIP_MANIFEST
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _grant_preview_clip_access(
    clip_dir: Path,
    *,
    clip_key: str,
    owner_user_id: Optional[str],
    owner_session_id: Optional[str],
) -> None:
    clip_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_preview_clip_manifest(clip_dir)
    owner_user_ids = {str(value) for value in manifest.get("owner_user_ids", []) if value}
    owner_session_ids = {str(value) for value in manifest.get("owner_session_ids", []) if value}
    if owner_user_id:
        owner_user_ids.add(str(owner_user_id))
    if owner_session_id:
        owner_session_ids.add(str(owner_session_id))
    now = datetime.now().isoformat(timespec="seconds")
    payload = {
        "version": 1,
        "clip_key": clip_key,
        "owner_user_ids": sorted(owner_user_ids),
        "owner_session_ids": sorted(owner_session_ids),
        "created_at": manifest.get("created_at") or now,
        "updated_at": now,
    }
    tmp_path = clip_dir / f"{PREVIEW_CLIP_MANIFEST}.{uuid.uuid4().hex[:8]}.tmp"
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(clip_dir / PREVIEW_CLIP_MANIFEST)


def _register_cache_entry(
    *,
    cache_key: str,
    cache_kind: str,
    path: Path,
    metadata: Dict[str, Any],
    cache_hit: bool,
) -> None:
    file_path = Path(path)
    if not file_path.exists():
        return
    store = get_artifact_store()
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    now = datetime.now().isoformat(timespec="seconds")
    storage_key = str(file_path.resolve().relative_to(store.root))
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO cache_entries (
                cache_key, cache_kind, storage_key, sha256, size_bytes,
                media_type, metadata_json, hit_count, created_at, last_accessed_at
            ) VALUES (
                :cache_key, :cache_kind, :storage_key, :sha256, :size_bytes,
                'audio/mpeg', :metadata_json, :hit_count, :created_at, :last_accessed_at
            )
            ON CONFLICT(cache_key) DO UPDATE SET
                storage_key = excluded.storage_key,
                sha256 = excluded.sha256,
                size_bytes = excluded.size_bytes,
                metadata_json = excluded.metadata_json,
                hit_count = cache_entries.hit_count + :hit_increment,
                last_accessed_at = excluded.last_accessed_at
            """,
            {
                "cache_key": cache_key,
                "cache_kind": cache_kind,
                "storage_key": storage_key,
                "sha256": digest,
                "size_bytes": file_path.stat().st_size,
                "metadata_json": json_text(metadata),
                "hit_count": 1 if cache_hit else 0,
                "hit_increment": 1 if cache_hit else 0,
                "created_at": now,
                "last_accessed_at": now,
            },
        )


def _preview_cache_ttl_hours() -> int:
    try:
        return max(1, int(str(os.getenv("LECTURE_CRAFT_PREVIEW_CACHE_TTL_HOURS", "168")).strip()))
    except Exception:
        return 168


def _maybe_prune_preview_audio_cache() -> None:
    """Remove only reproducible cache files; project artifacts are never touched."""
    global _PREVIEW_CACHE_LAST_PRUNE
    now_monotonic = time.monotonic()
    if now_monotonic - _PREVIEW_CACHE_LAST_PRUNE < _PREVIEW_CACHE_PRUNE_INTERVAL_SECONDS:
        return
    if not _PREVIEW_CACHE_PRUNE_LOCK.acquire(blocking=False):
        return
    try:
        now_monotonic = time.monotonic()
        if now_monotonic - _PREVIEW_CACHE_LAST_PRUNE < _PREVIEW_CACHE_PRUNE_INTERVAL_SECONDS:
            return
        cutoff = (datetime.now() - timedelta(hours=_preview_cache_ttl_hours())).isoformat(timespec="seconds")
        with db_conn() as conn:
            rows = conn.execute(
                """
                SELECT cache_key, cache_kind, storage_key
                FROM cache_entries
                WHERE cache_kind IN ('tts_sentence', 'preview_audio_clip')
                  AND last_accessed_at < :cutoff
                ORDER BY last_accessed_at
                LIMIT 500
                """,
                {"cutoff": cutoff},
            ).fetchall()
        store = get_artifact_store()
        removed_keys: List[str] = []
        for row in rows:
            try:
                path = store.resolve(row["storage_key"])
                if row["cache_kind"] == "preview_audio_clip":
                    shutil.rmtree(path.parent, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                removed_keys.append(str(row["cache_key"]))
            except Exception:
                LOGGER.exception("Failed to prune preview cache entry %s", row["cache_key"])
        if removed_keys:
            with db_conn() as conn:
                for cache_key in removed_keys:
                    conn.execute(
                        "DELETE FROM cache_entries WHERE cache_key = :cache_key",
                        {"cache_key": cache_key},
                    )
        _PREVIEW_CACHE_LAST_PRUNE = now_monotonic
    finally:
        _PREVIEW_CACHE_PRUNE_LOCK.release()


def _preview_sentence_key(text: str) -> str:
    payload = {
        "v": PREVIEW_AUDIO_VERSION,
        "text": text,
        "model": auto_config.API_TTS_MODEL,
        "voice": auto_config.API_TTS_VOICE,
        "speed": auto_config.API_TTS_VOICE_SPEED,
        "format": "mp3",
        "language": "ja",
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _preview_clip_key(sentence_keys: Sequence[str]) -> str:
    payload = {
        "v": PREVIEW_AUDIO_VERSION,
        "sentence_keys": list(sentence_keys),
        "format": "mp3",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _safe_preview_id(preview_id: str) -> str:
    value = str(preview_id or "").strip()
    if not re.fullmatch(r"pa_[0-9a-f]{16,64}", value):
        raise ApiError(400, "INVALID_PREVIEW_ID", "invalid preview id")
    return value


def _build_preview_sentence_timings(
    sentences: Sequence[Dict[str, Any]],
    entries: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    starts = [
        float(sentence.get("start_sec", 0) or 0)
        for sentence in sentences
        if _is_finite_number(sentence.get("start_sec", 0))
    ]
    global_start = min(starts) if starts else 0.0
    local_t = 0.0
    rows: List[Dict[str, Any]] = []
    for sentence, entry in zip(sentences, entries):
        original_duration = max(
            0.1,
            float(sentence.get("end_sec", 0) or 0) - float(sentence.get("start_sec", 0) or 0),
        )
        duration = float(entry.get("duration") or 0)
        if duration <= 0:
            duration = original_duration if original_duration > 0 else 2.0
        row = {
            "sentence_id": str(sentence.get("id") or ""),
            "slide_idx": int(sentence.get("slide_idx", 0) or 0),
            "text": str(sentence.get("text", "")).strip(),
            "local_start_sec": round(local_t, 3),
            "local_end_sec": round(local_t + duration, 3),
            "start_sec": round(global_start + local_t, 3),
            "end_sec": round(global_start + local_t + duration, 3),
        }
        rows.append(row)
        local_t += duration
    return rows


def _is_finite_number(value: Any) -> bool:
    try:
        parsed = float(value)
        return parsed == parsed and parsed not in {float("inf"), float("-inf")}
    except Exception:
        return False


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return default
    return parsed


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def ensure_pdf_upload(material_name: str, pdf_bytes: bytes, *, material_root: Path) -> Path:
    pdf_root = Path(material_root) / "pdf"
    pdf_root.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_root / material_name
    if not pdf_path.exists():
        pdf_path.write_bytes(pdf_bytes)
    return pdf_path


def ensure_pdf_images(material_name: str, *, material_root: Path) -> List[str]:
    pdf_path = Path(material_root) / "pdf" / material_name
    img_dir = Path(material_root) / "img" / material_name
    if img_dir.exists() and list(img_dir.glob("*.png")):
        return [str(path) for path in sorted(img_dir.glob("*.png"))]
    return pdf_to_images(str(pdf_path), str(img_dir), dpi=150)


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


def _pre_generation_kg_path(paths: ProjectPaths) -> Path:
    return Path(paths.output_dir) / "pre_generation_knowledge_graph.json"


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = str(text or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("KG response did not contain a JSON object")
    value = json.loads(raw[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("KG response must be a JSON object")
    return value


def _normalize_pre_generation_graph(value: Dict[str, Any], *, kg_mode: str) -> Dict[str, Any]:
    nodes = []
    seen_nodes: set[str] = set()
    for row in value.get("nodes") or []:
        if not isinstance(row, dict):
            continue
        label = re.sub(r"\s+", " ", str(row.get("label") or row.get("id") or "")).strip()[:120]
        if not label:
            continue
        node_id = str(row.get("id") or f"concept:{hashlib.sha256(label.encode('utf-8')).hexdigest()[:12]}")[:160]
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        slide_refs = sorted({int(v) for v in (row.get("slide_refs") or []) if str(v).isdigit()})
        nodes.append({"id": node_id, "label": label, "type": "concept", "slide_refs": slide_refs})
    edges = []
    for row in value.get("edges") or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        target = str(row.get("target") or "")
        if source not in seen_nodes or target not in seen_nodes or source == target:
            continue
        edges.append({
            "source": source,
            "target": target,
            "relation": re.sub(r"\s+", "_", str(row.get("relation") or "related_to").strip())[:80],
            "slide_refs": sorted({int(v) for v in (row.get("slide_refs") or []) if str(v).isdigit()}),
        })
    slide_refs = []
    for slide_idx in sorted({idx for node in nodes for idx in node["slide_refs"]}):
        slide_refs.append({
            "slide_idx": slide_idx,
            "node_ids": [node["id"] for node in nodes if slide_idx in node["slide_refs"]],
        })
    return {
        "version": "pre_generation_kg_v1",
        "kg_mode": kg_mode,
        "nodes": nodes,
        "edges": edges,
        "slide_refs": slide_refs,
        "sentence_refs": [],
        "region_refs": [],
        "quality_status": "llm_generated_before_script",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def ensure_pre_generation_knowledge_graph(paths: ProjectPaths, *, kg_mode: str) -> Dict[str, Any]:
    path = _pre_generation_kg_path(paths)
    cached = load_json_file(path, None)
    if isinstance(cached, dict) and cached.get("nodes"):
        return cached
    image_paths = sorted(
        [path for path in Path(paths.img_root).iterdir() if path.suffix.lower() in {".png", ".jpg", ".jpeg"}],
        key=lambda value: value.name,
    )
    if not image_paths:
        raise ApiError(500, "PRE_GENERATION_KG_INPUT_MISSING", "KG生成用のスライド画像がありません。")
    prompt = (
        "講義スライド画像から、台本生成前に使う教育用ナレッジグラフを作成してください。"
        "重要概念と、prerequisite_of / explains / example_of / contrasts_with / part_of / used_for / step_before "
        "の関係を抽出してください。各概念・関係には根拠となる0始まりのslide_refsを付けてください。"
        "スライドに根拠のない概念を追加しないでください。JSON以外は出力しないでください。\n"
        '{"nodes":[{"id":"concept:...","label":"...","slide_refs":[0]}],'
        '"edges":[{"source":"concept:...","target":"concept:...","relation":"prerequisite_of","slide_refs":[0]}]}'
    )
    _response, result = call_responses_text(
        create_client(),
        modelname=os.getenv("LECTURE_CRAFT_MODEL_KG", auto_config.API_MODEL_EXPLANATION),
        messages=[
            build_responses_system_message("講義スライドから根拠付き教育KGを厳密なJSONで構築してください。"),
            build_responses_user_message(prompt, image_paths),
        ],
    )
    graph = _normalize_pre_generation_graph(_extract_json_object(result), kg_mode=kg_mode)
    if not graph["nodes"]:
        raise ApiError(500, "PRE_GENERATION_KG_EMPTY", "台本生成前KGから概念を抽出できませんでした。")
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return graph


def write_research_generation_context(paths: ProjectPaths, req: GenerateRequest) -> None:
    conditions = normalize_generation_conditions(req.generation_conditions)
    memories = req.correction_memories if isinstance(req.correction_memories, list) else []
    if conditions.get("kg_mode") == "off" and not conditions.get("log_reuse_enabled"):
        return
    memory_rows = []
    for row in memories[:8]:
        if (
            not isinstance(row, dict)
            or row.get("preference_kind") != "preference"
            or not row.get("preference_text")
        ):
            continue
        memory_rows.append(
            {
                "preference": row.get("preference_text"),
                "preference_source": row.get("preference_source"),
                "preference_scope": row.get("preference_scope"),
                "preference_reason": row.get("preference_reason"),
                "context_similarity": row.get("context_similarity"),
            }
        )
    consolidated_preference = consolidate_preferences(memory_rows)
    pre_generation_graph = load_json_file(_pre_generation_kg_path(paths), {})
    kg_summary = {
        "nodes": [
            {"id": row.get("id"), "label": row.get("label"), "slide_refs": row.get("slide_refs") or []}
            for row in (pre_generation_graph.get("nodes") or [])[:40]
        ],
        "edges": (pre_generation_graph.get("edges") or [])[:60],
    } if isinstance(pre_generation_graph, dict) else {}
    text = (
        "[LectureCraft Research Context]\n"
        "以下は実験条件と過去の修正傾向です。台本生成時は，スライド内容への忠実性を優先しつつ，"
        "該当する場合だけ説明順序，補足量，言い換え方の参考にしてください。\n\n"
        f"- kg_mode: {conditions.get('kg_mode')}\n"
        f"- log_reuse_enabled: {conditions.get('log_reuse_enabled')}\n"
        f"- prompt_strategy_version: {conditions.get('prompt_strategy_version')}\n"
        f"- reusable_correction_count: {len(memory_rows)}\n\n"
        "[Pre-generation Knowledge Graph]\n"
        f"{json.dumps(kg_summary, ensure_ascii=False, indent=2)}\n\n"
        "[Learned Preferences]\n"
        + (f"{consolidated_preference}\n" if consolidated_preference else "")
        + ("[Retrieved Preference Evidence]\n" if memory_rows else "")
        + "\n".join(
            f"- {row['preference']}"
            for row in memory_rows if row.get("preference")
        )
        + "\n"
    )
    for root in (Path(paths.output_dir), Path(paths.explanation_save_dir)):
        try:
            root.mkdir(parents=True, exist_ok=True)
            (root / "research_generation_context.txt").write_text(text, encoding="utf-8")
        except Exception:
            pass


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
        slide_idx = safe_int(sentence.get("slide_idx"), 0)
        slide_idx = min(max(slide_idx, 0), max(slide_count - 1, 0))
        grouped[slide_idx].append(sentence)
    return grouped


def group_highlights_by_slide(highlights: Sequence[Dict[str, Any]], slide_count: int) -> List[List[Dict[str, Any]]]:
    grouped: List[List[Dict[str, Any]]] = [[] for _ in range(slide_count)]
    for highlight in highlights or []:
        if not isinstance(highlight, dict):
            continue
        slide_idx = safe_int(highlight.get("slide_idx"), 0)
        slide_idx = min(max(slide_idx, 0), max(slide_count - 1, 0))
        grouped[slide_idx].append(highlight)
    return grouped


def write_reviewed_lp_outputs(
    paths: ProjectPaths,
    slide_infos: Sequence[SlideImageInfo],
    grouped_highlights: Sequence[Sequence[Dict[str, Any]]],
    *,
    output_dir: Optional[Path] = None,
) -> List[List[Dict[str, Any]]]:
    reviewed_output_dir = Path(output_dir) if output_dir is not None else Path(paths.output_dir) / "reviewed_LP_output"
    reviewed_output_dir.mkdir(parents=True, exist_ok=True)
    region_maps: List[List[Dict[str, Any]]] = []
    for slide_info in slide_infos:
        slide_highlights = grouped_highlights[slide_info.index] if slide_info.index < len(grouped_highlights) else []
        regions: List[Dict[str, Any]] = []
        slide_region_map: List[Dict[str, Any]] = []

        for hl in slide_highlights:
            highlight_id = str(hl.get("id") or f"review_s{slide_info.index + 1:03d}_r{len(regions)}")
            x1, y1, x2, y2 = coords_from_percent_highlight(hl, slide_info.width, slide_info.height)
            region = {
                "id": len(regions),
                "type": str(hl.get("region_type") or "Figure"),
                "coordinates": [x1, y1, x2, y2],
                "score": safe_float(hl.get("score"), 1.0),
                "source": "human_review",
                "source_highlight_id": highlight_id,
            }
            regions.append(region)
            slide_region_map.append({"highlight_id": highlight_id, "region": region})

        out_path = reviewed_output_dir / f"result_{slide_info.index + 1:03d}.json"
        out_path.write_text(json.dumps(regions, ensure_ascii=False, indent=2), encoding="utf-8")
        region_maps.append(slide_region_map)

    return region_maps


def write_reviewed_script_outputs(
    grouped_sentences: Sequence[Sequence[Dict[str, Any]]],
    *,
    output_dir: Path,
) -> None:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for slide_idx, slide_sentences in enumerate(grouped_sentences, start=1):
        lines = [str(sentence.get("text", "")).strip() for sentence in slide_sentences]
        text = "\n".join([line for line in lines if line])
        (out_dir / f"slide_{slide_idx:03d}.txt").write_text(text, encoding="utf-8")


def build_reviewed_region_visuals(
    slide_info: SlideImageInfo,
    region_map: Sequence[Dict[str, Any]],
    *,
    output_dir: Path,
    slide_str: str,
) -> Tuple[Optional[Path], List[Dict[str, str]]]:
    """Create LLM visual inputs from the exact regions confirmed by the user."""
    if not region_map:
        return None, []

    slide_dir = Path(output_dir) / f"slide_{slide_str}"
    slide_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(slide_info.path) as source:
        original = source.convert("RGB")

    line_width = max(3, min(original.size) // 240)
    font = ImageFont.load_default()
    overview = original.copy()
    overview_draw = ImageDraw.Draw(overview)
    region_imgs: List[Dict[str, str]] = []

    for row in region_map:
        region = row.get("region") if isinstance(row, dict) else None
        if not isinstance(region, dict):
            continue
        coordinates = region.get("coordinates")
        if not isinstance(coordinates, list) or len(coordinates) < 4:
            continue

        x1 = max(0, min(original.width - 1, safe_int(coordinates[0], 0)))
        y1 = max(0, min(original.height - 1, safe_int(coordinates[1], 0)))
        x2 = max(x1 + 1, min(original.width, safe_int(coordinates[2], original.width)))
        y2 = max(y1 + 1, min(original.height, safe_int(coordinates[3], original.height)))
        region_id = str(region.get("id", len(region_imgs)))
        region_type = str(region.get("type") or "Figure")
        label = f"{region_id}: {region_type}"

        overview_draw.rectangle([x1, y1, x2 - 1, y2 - 1], outline=(255, 0, 0), width=line_width)
        label_box = overview_draw.textbbox((0, 0), label, font=font)
        label_w = max(1, label_box[2] - label_box[0])
        label_h = max(1, label_box[3] - label_box[1])
        label_x = x1
        label_y = max(0, y1 - label_h - 6)
        overview_draw.rectangle(
            [label_x, label_y, min(original.width - 1, label_x + label_w + 6), label_y + label_h + 4],
            fill=(255, 0, 0),
        )
        overview_draw.text((label_x + 3, label_y + 2), label, fill=(255, 255, 255), font=font)

        padding = max(12, int(max(x2 - x1, y2 - y1) * 0.12))
        crop_x1 = max(0, x1 - padding)
        crop_y1 = max(0, y1 - padding)
        crop_x2 = min(original.width, x2 + padding)
        crop_y2 = min(original.height, y2 + padding)
        crop = original.crop((crop_x1, crop_y1, crop_x2, crop_y2))
        crop_draw = ImageDraw.Draw(crop)
        crop_draw.rectangle(
            [x1 - crop_x1, y1 - crop_y1, x2 - crop_x1 - 1, y2 - crop_y1 - 1],
            outline=(255, 0, 0),
            width=line_width,
        )
        safe_type = re.sub(r"[^A-Za-z0-9_-]+", "_", region_type).strip("_") or "Region"
        crop_path = slide_dir / f"region_{slide_str}_{region_id}_{safe_type}.png"
        crop.save(crop_path)
        region_imgs.append({"region_id": region_id, "type": region_type, "path": str(crop_path)})

    if not region_imgs:
        return None, []
    overview_path = slide_dir / f"edited_regions_{slide_str}.png"
    overview.save(overview_path)
    return overview_path, region_imgs


def build_assignment_highlight_seed(highlights: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    seed: Dict[str, Dict[str, Any]] = {}
    for highlight in highlights or []:
        if not isinstance(highlight, dict):
            continue
        highlight_id = str(highlight.get("id") or "")
        if not highlight_id:
            continue
        next_highlight = dict(highlight)
        next_highlight["sentence_ids"] = []
        next_highlight.pop("sid", None)
        seed[highlight_id] = next_highlight
    return seed


def apply_assignment_mapping_to_highlights(
    highlights_by_id: Dict[str, Dict[str, Any]],
    mapping: Dict[str, Any],
    slide_sentences: Sequence[Dict[str, Any]],
    region_map: Sequence[Dict[str, Any]],
) -> None:
    for item in mapping.get("sentences") or []:
        if not isinstance(item, dict):
            continue
        animate = item.get("animate")
        if not isinstance(animate, dict):
            continue
        try:
            sent_idx = int(item.get("sent_idx", 0) or 0)
            region_id = int(animate.get("region_id"))
        except Exception:
            continue
        if sent_idx < 1 or sent_idx > len(slide_sentences):
            continue
        if region_id < 0 or region_id >= len(region_map):
            continue

        sentence_id = str(slide_sentences[sent_idx - 1].get("id") or "")
        highlight_id = str(region_map[region_id].get("highlight_id") or "")
        if not sentence_id or not highlight_id or highlight_id not in highlights_by_id:
            continue

        highlight = highlights_by_id[highlight_id]
        sentence_ids = highlight.setdefault("sentence_ids", [])
        if sentence_id not in sentence_ids:
            sentence_ids.append(sentence_id)
        style = str(animate.get("style") or "")
        if style:
            highlight["kind"] = BACK_STYLE_TO_FRONT_KIND.get(style, highlight.get("kind", "marker"))


def finalize_assignment_highlights(highlights_by_id: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for highlight in highlights_by_id.values():
        sentence_ids = [str(sid) for sid in highlight.get("sentence_ids", []) if sid]
        next_highlight = dict(highlight)
        next_highlight["sentence_ids"] = sentence_ids
        if sentence_ids:
            next_highlight["sid"] = sentence_ids[0]
        else:
            next_highlight.pop("sid", None)
        out.append(next_highlight)
    return out


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
    cleaned = clean_script_text(text)
    chunks = [chunk.strip() for chunk in SENTENCE_SPLIT_RE.split(cleaned) if chunk and chunk.strip()]
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
    generation_ref.update({
        "cache_key": plan.request_key,
        "pdf_hash": plan.pdf_hash,
        "cache_hit": cache_hit,
    })
    if plan.generation_run_id:
        generation_ref["run_id"] = plan.generation_run_id
    else:
        generation_ref["material_name"] = plan.material_name
        generation_ref["output_root_name"] = plan.output_root_name
    payload["generation_ref"] = generation_ref
    return payload


def attach_research_generation_outputs(
    response: Dict[str, Any],
    req: GenerateRequest,
    plan: GenerateCachePlan,
) -> Dict[str, Any]:
    payload = dict(response)
    conditions = normalize_generation_conditions(req.generation_conditions)
    kg_mode = conditions.get("kg_mode", "off")
    pre_generation_graph = load_json_file(
        Path(plan.output_root_name) / "pre_generation_knowledge_graph.json",
        None,
    )
    graph = (
        pre_generation_graph
        if isinstance(pre_generation_graph, dict) and pre_generation_graph.get("nodes")
        else build_lightweight_knowledge_graph(payload, kg_mode=kg_mode)
    )
    if graph is not None:
        payload["knowledge_graph"] = graph
    if conditions.get("log_reuse_enabled"):
        preference_count = sum(
            1 for row in (req.correction_memories or [])
            if isinstance(row, dict) and row.get("preference_text")
        )
        payload["generation_ref"] = {
            **(payload.get("generation_ref") or {}),
            "correction_memory_count": len(req.correction_memories or []),
            "preference_memory_count": preference_count,
            "prompt_strategy_version": conditions.get("prompt_strategy_version"),
        }
    persist_generation_research_outputs(req, plan, payload, conditions)
    return payload


def normalize_generation_conditions(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    kg_mode = str(raw.get("kg_mode") or "global_slide")
    if kg_mode not in VALID_KG_MODES:
        kg_mode = "off"
    return {
        "kg_mode": kg_mode,
        "log_reuse_enabled": bool(raw.get("log_reuse_enabled", False)),
        "review_flow_enabled": bool(raw.get("review_flow_enabled", True)),
        "prompt_strategy_version": str(raw.get("prompt_strategy_version") or "baseline_v1")[:80],
    }


def build_lightweight_knowledge_graph(response: Dict[str, Any], *, kg_mode: str) -> Optional[Dict[str, Any]]:
    if kg_mode == "off":
        return None
    slides = response.get("slides") if isinstance(response.get("slides"), list) else []
    sentences = response.get("sentences") if isinstance(response.get("sentences"), list) else []
    highlights = response.get("highlights") if isinstance(response.get("highlights"), list) else []
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    edges_by_key: Dict[str, Dict[str, Any]] = {}
    sentence_refs: List[Dict[str, Any]] = []
    slide_refs: List[Dict[str, Any]] = []
    region_refs: List[Dict[str, Any]] = []

    if kg_mode == "global_slide":
        for idx, slide in enumerate(slides):
            slide_id = f"slide:{idx}"
            nodes_by_id[slide_id] = {
                "id": slide_id,
                "label": slide.get("title") or f"スライド {idx + 1}",
                "type": "slide",
                "slide_idx": idx,
            }

    previous_concepts: List[str] = []
    for sent in sorted(sentences, key=sentence_sort_key):
        slide_idx = int(sent.get("slide_idx", 0) or 0)
        terms = extract_concept_terms(str(sent.get("text") or ""))
        concept_ids: List[str] = []
        for term in terms[:6]:
            concept_id = concept_node_id(term, slide_idx=slide_idx if kg_mode == "slide" else None)
            concept_ids.append(concept_id)
            nodes_by_id.setdefault(
                concept_id,
                {
                    "id": concept_id,
                    "label": term,
                    "type": "concept",
                    "scope": "slide" if kg_mode == "slide" else "global",
                    "slide_idx": slide_idx if kg_mode == "slide" else None,
                },
            )
            if kg_mode == "global_slide":
                add_edge(edges_by_key, f"slide:{slide_idx}", concept_id, "contains", sent.get("id"))
        for left, right in zip(concept_ids, concept_ids[1:]):
            add_edge(edges_by_key, left, right, "co_occurs", sent.get("id"))
        for prev in previous_concepts[-2:]:
            for current in concept_ids[:2]:
                if prev != current:
                    add_edge(edges_by_key, prev, current, "precedes", sent.get("id"))
        previous_concepts.extend(concept_ids)
        sentence_refs.append(
            {
                "sentence_id": sent.get("id"),
                "slide_idx": slide_idx,
                "node_ids": concept_ids,
            }
        )

    for idx, slide in enumerate(slides):
        node_ids = sorted(
            {
                node_id
                for ref in sentence_refs
                if int(ref.get("slide_idx", -1)) == idx
                for node_id in ref.get("node_ids", [])
            }
        )
        slide_refs.append(
            {
                "slide_idx": idx,
                "slide_id": slide.get("id"),
                "node_ids": node_ids,
            }
        )

    sentence_node_map = {
        str(ref.get("sentence_id")): list(ref.get("node_ids") or [])
        for ref in sentence_refs
    }
    for hl in highlights:
        sentence_ids = hl.get("sentence_ids")
        if not isinstance(sentence_ids, list):
            sentence_ids = [hl.get("sid")] if hl.get("sid") else []
        node_ids = sorted({node_id for sid in sentence_ids for node_id in sentence_node_map.get(str(sid), [])})
        region_refs.append(
            {
                "highlight_id": hl.get("id"),
                "slide_idx": hl.get("slide_idx"),
                "sentence_ids": sentence_ids,
                "node_ids": node_ids,
            }
        )

    return {
        "version": "lightweight_kg_v1",
        "kg_mode": kg_mode,
        "nodes": list(nodes_by_id.values()),
        "edges": list(edges_by_key.values()),
        "slide_refs": slide_refs,
        "region_refs": region_refs,
        "sentence_refs": sentence_refs,
        "quality_status": "auto_generated_lightweight",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def extract_concept_terms(text: str) -> List[str]:
    cleaned = re.sub(r"\s+", " ", text or "")
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9_+\-]{2,}|[一-龠ァ-ヶーぁ-んA-Za-z0-9]{2,}", cleaned)
    stopwords = {
        "です", "ます", "こと", "これ", "それ", "ため", "よう", "ここ", "この", "その",
        "について", "つまり", "まず", "次に", "最後", "場合", "説明", "確認",
    }
    terms: List[str] = []
    for item in candidates:
        term = item.strip("，．。、。・:：；;（）()[]「」『』")
        if len(term) < 2 or term in stopwords:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def concept_node_id(term: str, *, slide_idx: Optional[int] = None) -> str:
    scope = f"slide{slide_idx}:" if slide_idx is not None else "global:"
    digest = hashlib.sha1(f"{scope}{term}".encode("utf-8")).hexdigest()[:10]
    return f"concept:{digest}"


def add_edge(
    edges_by_key: Dict[str, Dict[str, Any]],
    source: str,
    target: str,
    relation: str,
    sentence_id: Any = None,
) -> None:
    key = f"{source}->{relation}->{target}"
    edge = edges_by_key.setdefault(
        key,
        {
            "id": f"edge:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}",
            "source": source,
            "target": target,
            "relation": relation,
            "sentence_ids": [],
        },
    )
    if sentence_id and sentence_id not in edge["sentence_ids"]:
        edge["sentence_ids"].append(sentence_id)


def persist_generation_research_outputs(
    req: GenerateRequest,
    plan: GenerateCachePlan,
    response: Dict[str, Any],
    conditions: Dict[str, Any],
) -> None:
    job_id = req.generation_job_id
    if not job_id:
        return
    generation_ref = response.get("generation_ref") if isinstance(response.get("generation_ref"), dict) else {}
    artifact_refs = {
        "cache_key": generation_ref.get("cache_key") or plan.request_key,
        "pdf_hash": generation_ref.get("pdf_hash") or plan.pdf_hash,
        "run_id": generation_ref.get("run_id") or plan.generation_run_id,
    }
    if not plan.generation_run_id:
        artifact_refs.update(
            {
                "material_name": generation_ref.get("material_name") or plan.material_name,
                "output_root_name": generation_ref.get("output_root_name") or plan.output_root_name,
                "response_cache_path": str(plan.response_cache_path),
            }
        )
    result_summary = {
        "slide_count": len(response.get("slides") or []),
        "sentence_count": len(response.get("sentences") or []),
        "highlight_count": len(response.get("highlights") or []),
        "kg_mode": conditions.get("kg_mode"),
        "correction_memory_count": len(req.correction_memories or []),
        "preference_memory_count": sum(
            1 for row in (req.correction_memories or [])
            if isinstance(row, dict) and row.get("preference_text")
        ),
        "knowledge_graph": {
            "node_count": len((response.get("knowledge_graph") or {}).get("nodes") or []),
            "edge_count": len((response.get("knowledge_graph") or {}).get("edges") or []),
        },
    }
    try:
        with db_conn() as conn:
            conn.execute(
                """
                UPDATE generation_runs
                SET status = :status,
                    request_key = COALESCE(request_key, :request_key),
                    pdf_hash = COALESCE(pdf_hash, :pdf_hash),
                    artifact_refs_json = :artifact_refs_json,
                    result_summary_json = :result_summary_json,
                    updated_at = :updated_at
                WHERE job_id = :job_id
                """,
                {
                    "status": "completed",
                    "request_key": plan.request_key,
                    "pdf_hash": plan.pdf_hash,
                    "artifact_refs_json": json_text(artifact_refs),
                    "result_summary_json": json_text(result_summary),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "job_id": job_id,
                },
            )
            graph = response.get("knowledge_graph") if isinstance(response.get("knowledge_graph"), dict) else None
            if graph:
                run = conn.execute(
                    """
                    SELECT id, project_id, user_id, experiment_id
                    FROM generation_runs
                    WHERE job_id = :job_id
                    """,
                    {"job_id": job_id},
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO knowledge_graph_versions (
                        id, project_id, generation_run_id, job_id, user_id, experiment_id, kg_mode,
                        nodes_json, edges_json, slide_refs_json, region_refs_json, sentence_refs_json,
                        quality_status, payload_json, created_at
                    )
                    VALUES (
                        :id, :project_id, :generation_run_id, :job_id, :user_id, :experiment_id, :kg_mode,
                        :nodes_json, :edges_json, :slide_refs_json, :region_refs_json, :sentence_refs_json,
                        :quality_status, :payload_json, :created_at
                    )
                    """,
                    {
                        "id": f"kg_{uuid.uuid4().hex[:12]}",
                        "project_id": run["project_id"] if run else None,
                        "generation_run_id": run["id"] if run else None,
                        "job_id": job_id,
                        "user_id": run["user_id"] if run else None,
                        "experiment_id": run["experiment_id"] if run else None,
                        "kg_mode": graph.get("kg_mode") or conditions.get("kg_mode") or "off",
                        "nodes_json": json_text(graph.get("nodes") or []),
                        "edges_json": json_text(graph.get("edges") or []),
                        "slide_refs_json": json_text(graph.get("slide_refs") or []),
                        "region_refs_json": json_text(graph.get("region_refs") or []),
                        "sentence_refs_json": json_text(graph.get("sentence_refs") or []),
                        "quality_status": graph.get("quality_status") or "auto_generated_lightweight",
                        "payload_json": json_text(graph),
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    },
                )
    except Exception:
        pass


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


def save_research_session(
    req: ResearchSessionRequest,
    *,
    session_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user = session_context.get("user") if isinstance(session_context, dict) else {}
    session_id = str(req.session_id or f"session_{timestamp_slug()}_{short_id()}")
    research_payload = req.research if isinstance(req.research, dict) else {}
    research_project = research_payload.get("project") if isinstance(research_payload.get("project"), dict) else {}
    research_extensions = (
        research_payload.get("extensions")
        if isinstance(research_payload.get("extensions"), dict)
        else {}
    )
    payload = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "trigger": req.trigger,
        "mode": req.mode,
        "actor_user_id": user.get("id"),
        "actor_user_kind": user.get("kind"),
        "actor_role": user.get("role"),
        "auth_session_id": session_context.get("session_id") if isinstance(session_context, dict) else None,
        "experiment_id": session_context.get("experiment_id") if isinstance(session_context, dict) else None,
        "participant_label": session_context.get("participant_label") if isinstance(session_context, dict) else None,
        "project_id": research_project.get("id") or research_extensions.get("project_id"),
        "project_name": research_project.get("name") or research_extensions.get("project_name"),
        "project_version": research_project.get("version_number") or research_extensions.get("project_version"),
        "generation_ref": req.generation_ref,
        "settings": req.settings,
        "operation_logs": req.operation_logs,
        "research": research_payload,
    }
    snapshot_id = _persist_research_session_snapshot(payload)
    return {
        "ok": True,
        "session_id": session_id,
        "snapshot_id": snapshot_id,
        "summary": research_payload.get("summary") if isinstance(research_payload, dict) else {},
    }


def _persist_research_session_snapshot(payload: Dict[str, Any]) -> str:
    snapshot_id = f"research_{uuid.uuid4().hex[:12]}"
    with db_conn() as conn:
        project_id = payload.get("project_id")
        if project_id:
            project_row = conn.execute(
                "SELECT id FROM projects WHERE id = :project_id",
                {"project_id": project_id},
            ).fetchone()
            if project_row is None:
                project_id = None
        conn.execute(
            """
            INSERT INTO research_session_snapshots (
                id, session_id, trigger, saved_at, actor_user_id, experiment_id, project_id, payload_json
            )
            VALUES (
                :id, :session_id, :trigger, :saved_at, :actor_user_id, :experiment_id, :project_id, :payload_json
            )
            """,
            {
                "id": snapshot_id,
                "session_id": payload.get("session_id"),
                "trigger": payload.get("trigger"),
                "saved_at": payload.get("saved_at"),
                "actor_user_id": payload.get("actor_user_id"),
                "experiment_id": payload.get("experiment_id"),
                "project_id": project_id,
                "payload_json": json_text(payload),
            },
        )
    return snapshot_id
