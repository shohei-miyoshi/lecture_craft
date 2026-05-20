from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from auto_lecture import config as auto_config
from auto_lecture import deck_scan, lecture_script
from auto_lecture.audio_only_lecture import (
    ensure_audio_only_dir,
    step_extract_materials,
    step_generate_narration,
    step_generate_outline,
    step_stitch_script,
)
from auto_lecture.gpt_client import create_client
from auto_lecture.paths import build_paths

from .kg_preview_service import get_kg_preview_result
from .service import ApiError, DETAIL_MAP, LEVEL_MAP, MATERIAL_ROOT, ensure_pdf_images


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_COMPARE_ROOT = PROJECT_ROOT / "outputs" / "script_compare" / "catalog"


def _canonical_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _short_id() -> str:
    import uuid

    return uuid.uuid4().hex[:8]


def _extract_project_pdf_ref(project_data: Dict[str, Any]) -> Dict[str, str]:
    data = project_data if isinstance(project_data, dict) else {}
    pdf_ref = data.get("pdf_ref") if isinstance(data.get("pdf_ref"), dict) else {}
    material_name = _canonical_text(
        pdf_ref.get("material_name")
        or (data.get("generation_ref") or {}).get("material_name")
    )
    filename = _canonical_text(
        pdf_ref.get("filename")
        or data.get("pdf_name")
        or (data.get("project_meta") or {}).get("name")
        or material_name
    )
    if not material_name:
        raise ApiError(
            400,
            "PROJECT_SOURCE_PDF_REQUIRED",
            "このプロジェクトには source PDF が紐づいていません。PDF を保持した状態で保存し直してください。",
        )
    return {"material_name": material_name, "filename": filename or material_name}


def _build_kg_guidance_payload(kg_payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "result_id": kg_payload.get("result_id"),
        "variant": kg_payload.get("variant") or {},
        "summary": kg_payload.get("summary") or {},
        "graph": kg_payload.get("graph") or {},
        "triplets": kg_payload.get("triplets") or [],
        "structured": kg_payload.get("structured") or {},
        "notes": kg_payload.get("summary", {}).get("notes") or [],
    }


def _catalog_result_path(compare_id: str) -> Path:
    return SCRIPT_COMPARE_ROOT / compare_id / "result.json"


def _read_catalog_payload(compare_id: str) -> Dict[str, Any]:
    path = _catalog_result_path(compare_id)
    if not path.exists():
        raise ApiError(404, "SCRIPT_COMPARE_NOT_FOUND", f"compare_id '{compare_id}' は見つかりません。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApiError(500, "SCRIPT_COMPARE_READ_FAILED", f"compare_id '{compare_id}' を読み込めませんでした: {exc}") from exc


def _build_catalog_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    settings = payload.get("settings") or {}
    kg_result = payload.get("kg_result") or {}
    baseline = payload.get("baseline") or {}
    kg_assisted = payload.get("kg_assisted") or {}
    return {
        "compare_id": payload.get("compare_id"),
        "created_at": payload.get("created_at"),
        "project_id": payload.get("project_id"),
        "owner_user_id": payload.get("owner_user_id"),
        "source_pdf": payload.get("source_pdf") or {},
        "settings": {
            "mode": settings.get("mode"),
            "detail": settings.get("detail"),
            "difficulty": settings.get("difficulty"),
            "level_code": settings.get("level_code"),
            "detail_code": settings.get("detail_code"),
        },
        "kg_result": {
            "result_id": kg_result.get("result_id"),
            "created_at": kg_result.get("created_at"),
            "variant": kg_result.get("variant") or {},
            "summary": kg_result.get("summary") or {},
        },
        "baseline_stats": baseline.get("stats") or {},
        "kg_assisted_stats": kg_assisted.get("stats") or {},
        "notes": payload.get("notes") or [],
    }


def _script_stats(text: str) -> Dict[str, int]:
    source = str(text or "").strip()
    if not source:
        return {"char_count": 0, "line_count": 0, "sentence_count": 0}
    lines = [row for row in source.splitlines() if row.strip()]
    sentence_count = len([row for row in re.split(r"(?<=[。！？])", source) if row.strip()])
    return {
        "char_count": len(source),
        "line_count": len(lines),
        "sentence_count": sentence_count,
    }


def _run_script_flow(
    *,
    client: Any,
    material_name: str,
    output_root_name: str,
    level: str,
    detail: str,
    kg_guidance: Dict[str, Any] | None,
    materials_result: Any,
) -> Dict[str, Any]:
    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=MATERIAL_ROOT,
        output_root_name=output_root_name,
    )
    audio_only_dir = ensure_audio_only_dir(paths)
    outline_result = step_generate_outline(
        client=client,
        materials_all_path=materials_result.materials_all_path,
        audio_only_dir=audio_only_dir,
        img_paths=materials_result.img_paths,
        kg_guidance=kg_guidance,
        model_name=auto_config.API_MODEL_AUDIO_OUTLINE,
    )
    script_raw_path = step_generate_narration(
        client=client,
        materials_slide_paths=materials_result.materials_slide_paths,
        outline_json=outline_result.outline_json,
        audio_only_dir=audio_only_dir,
        img_paths=materials_result.img_paths,
        kg_guidance=kg_guidance,
        model_name=auto_config.API_MODEL_AUDIO_NARRATION,
    )
    script_final_path = step_stitch_script(
        client=client,
        script_path=script_raw_path,
        level=level,
        detail=detail,
        model_name=auto_config.API_MODEL_AUDIO_STITCH,
    )
    script_text = script_final_path.read_text(encoding="utf-8")
    return {
        "flow_mode": "audio",
        "lecture_title": outline_result.lecture_title,
        "outline_json": outline_result.outline_json,
        "script_text": script_text,
        "stats": _script_stats(script_text),
        "artifacts": {
            "output_dir": str(paths.output_dir),
            "audio_only_dir": str(audio_only_dir),
            "materials_all_path": str(materials_result.materials_all_path),
            "outline_json_path": str(outline_result.outline_json_path),
            "outline_txt_path": str(outline_result.outline_txt_path),
            "script_raw_path": str(script_raw_path),
            "script_path": str(script_final_path),
        },
    }


def _copy_deck_scan_overview(source_path: Path, target_output_root_name: str, material_name: str) -> Dict[str, Any]:
    paths = build_paths(
        teaching_material_file_name=material_name,
        material_root=MATERIAL_ROOT,
        output_root_name=target_output_root_name,
    )
    target_path = Path(paths.all_page_scan_output_dir) / "deck_scan_overview.txt"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return {"paths": paths, "deck_scan_overview_path": target_path}


def _run_visual_script_flow(
    *,
    client: Any,
    material_name: str,
    output_root_name: str,
    level: str,
    detail: str,
    kg_guidance: Dict[str, Any] | None,
    deck_scan_overview_path: Path,
) -> Dict[str, Any]:
    copied = _copy_deck_scan_overview(deck_scan_overview_path, output_root_name, material_name)
    paths = copied["paths"]
    explanations = lecture_script.run_lecture_script(
        client=client,
        paths=paths,
        level=level,
        detail=detail,
        kg_guidance=kg_guidance,
    )
    script_text = "\n\n".join([str(text).strip() for text in explanations if str(text).strip()]).strip()
    all_explanations_path = Path(paths.explanation_save_dir) / "all_explanations.txt"
    return {
        "flow_mode": "visual",
        "lecture_title": Path(material_name).stem,
        "outline_json": None,
        "script_text": script_text,
        "stats": _script_stats(script_text),
        "artifacts": {
            "output_dir": str(paths.output_dir),
            "explanation_save_dir": str(paths.explanation_save_dir),
            "deck_scan_overview_path": str(copied["deck_scan_overview_path"]),
            "all_explanations_path": str(all_explanations_path),
        },
    }


def render_script_compare(
    *,
    project_id: str,
    project_data: Dict[str, Any],
    kg_result_id: str,
    mode: str,
    detail: str,
    difficulty: str,
    owner_user_id: str | None = None,
) -> Dict[str, Any]:
    pdf_ref = _extract_project_pdf_ref(project_data)
    material_name = pdf_ref["material_name"]
    ensure_pdf_images(material_name)

    kg_payload = get_kg_preview_result(
        kg_result_id,
        user_id=owner_user_id,
        project_id=project_id,
    )
    kg_guidance = _build_kg_guidance_payload(kg_payload)

    compare_id = f"scriptcmp_{_timestamp_slug()}_{_short_id()}"
    output_dir = SCRIPT_COMPARE_ROOT / compare_id
    output_dir.mkdir(parents=True, exist_ok=True)

    level = LEVEL_MAP[difficulty]
    detail_code = DETAIL_MAP[detail]
    client = create_client()
    if mode == "audio":
        shared_paths = build_paths(
            teaching_material_file_name=material_name,
            material_root=MATERIAL_ROOT,
            output_root_name=f"script_compare/{compare_id}/shared_audio",
        )
        materials_result = step_extract_materials(
            client=client,
            paths=shared_paths,
            max_workers=auto_config.AUDIO_MATERIAL_MAX_WORKERS,
            model_name=auto_config.API_MODEL_AUDIO_MATERIAL,
        )
        baseline = _run_script_flow(
            client=client,
            material_name=material_name,
            output_root_name=f"script_compare/{compare_id}/baseline",
            level=level,
            detail=detail_code,
            kg_guidance=None,
            materials_result=materials_result,
        )
        kg_assisted = _run_script_flow(
            client=client,
            material_name=material_name,
            output_root_name=f"script_compare/{compare_id}/kg_assisted",
            level=level,
            detail=detail_code,
            kg_guidance=kg_guidance,
            materials_result=materials_result,
        )
        notes = [
            "比較対象は通常の音声台本フローと、保存済み KG を補助情報として加えた音声台本フローです。",
            "材料抽出は共通化し、差分は outline / narration prompt に渡す KG ガイドのみです。",
        ]
    else:
        shared_paths = build_paths(
            teaching_material_file_name=material_name,
            material_root=MATERIAL_ROOT,
            output_root_name=f"script_compare/{compare_id}/shared_visual",
        )
        deck_scan_overview_path = Path(
            deck_scan.run_deck_scan(
                client=client,
                paths=shared_paths,
                level=level,
                detail=detail_code,
            )
        )
        baseline = _run_visual_script_flow(
            client=client,
            material_name=material_name,
            output_root_name=f"script_compare/{compare_id}/baseline",
            level=level,
            detail=detail_code,
            kg_guidance=None,
            deck_scan_overview_path=deck_scan_overview_path,
        )
        kg_assisted = _run_visual_script_flow(
            client=client,
            material_name=material_name,
            output_root_name=f"script_compare/{compare_id}/kg_assisted",
            level=level,
            detail=detail_code,
            kg_guidance=kg_guidance,
            deck_scan_overview_path=deck_scan_overview_path,
        )
        notes = [
            "比較対象は通常の動画用台本フローと、保存済み KG を補助情報として加えた動画用台本フローです。",
            "deck_scan は共通化し、差分は slide narration prompt に渡す KG ガイドのみです。",
        ]
        if mode == "hl":
            notes.append("HL動画モードでも、台本生成段階は動画モードと同じ visual script フローを使っています。")

    payload = {
        "ok": True,
        "compare_id": compare_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "project_id": project_id,
        "owner_user_id": owner_user_id,
        "source_pdf": pdf_ref,
        "settings": {
            "mode": mode,
            "detail": detail,
            "difficulty": difficulty,
            "level_code": level,
            "detail_code": detail_code,
        },
        "kg_result": {
            "result_id": kg_payload.get("result_id"),
            "created_at": kg_payload.get("created_at"),
            "variant": kg_payload.get("variant") or {},
            "summary": kg_payload.get("summary") or {},
        },
        "baseline": baseline,
        "kg_assisted": kg_assisted,
        "artifacts": {
            "output_dir": str(output_dir),
            "result_path": str(output_dir / "result.json"),
        },
        "notes": notes,
    }

    (output_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def list_script_compare_results(
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    limit: int = 24,
) -> Dict[str, Any]:
    SCRIPT_COMPARE_ROOT.mkdir(parents=True, exist_ok=True)
    items = []

    for result_path in sorted(SCRIPT_COMPARE_ROOT.glob("*/result.json"), reverse=True):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        owner_user_id = _canonical_text(payload.get("owner_user_id"))
        payload_project_id = _canonical_text(payload.get("project_id"))
        if user_id and owner_user_id and owner_user_id != _canonical_text(user_id):
            continue
        if project_id and payload_project_id != _canonical_text(project_id):
            continue
        items.append(_build_catalog_item(payload))

    items.sort(key=lambda row: _canonical_text(row.get("created_at")), reverse=True)
    safe_limit = max(1, min(int(limit or 24), 100))
    return {"results": items[:safe_limit], "total": len(items)}


def get_script_compare_result(
    compare_id: str,
    *,
    user_id: str | None = None,
    project_id: str | None = None,
) -> Dict[str, Any]:
    payload = _read_catalog_payload(compare_id)
    owner_user_id = _canonical_text(payload.get("owner_user_id"))
    payload_project_id = _canonical_text(payload.get("project_id"))
    if user_id and owner_user_id and owner_user_id != _canonical_text(user_id):
        raise ApiError(404, "SCRIPT_COMPARE_NOT_FOUND", f"compare_id '{compare_id}' は見つかりません。")
    if project_id and payload_project_id != _canonical_text(project_id):
        raise ApiError(404, "SCRIPT_COMPARE_NOT_FOUND", f"project '{project_id}' に compare_id '{compare_id}' は存在しません。")
    return payload
