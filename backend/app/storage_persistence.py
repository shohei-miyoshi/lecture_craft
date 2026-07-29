from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, List, Optional

from .db import db_conn, json_text
from .service import ApiError
from .storage import StoredFile, get_artifact_store


VALID_USAGE_CONTEXTS = {"general", "research"}
VALID_ANALYSIS_STATUSES = {"candidate", "included", "excluded"}
VALID_REVIEW_STAGES = ("layout", "script", "assignment")
MAX_PROJECT_PDF_BYTES = 60 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return default


def _row_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def _assert_json_safe(value: Any, path: str = "data") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            clean_key = str(key).lower()
            if clean_key in {"pdf_base64", "upload_base64", "image_base64", "data_url", "session_token", "api_key"}:
                raise ApiError(400, "BINARY_STATE_NOT_ALLOWED", f"{path}.{key} はサーバ状態へ保存できません。")
            _assert_json_safe(item, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _assert_json_safe(item, f"{path}[{idx}]")


def _project_owner(conn: Any, project_id: str, user_id: str) -> Any:
    row = conn.execute(
        """
        SELECT id, user_id, experiment_id, name, usage_context, analysis_status,
               latest_state_json, current_source_artifact_id, active_run_id,
               archived_at, created_at, updated_at
        FROM projects
        WHERE id = :project_id AND user_id = :user_id
        """,
        {"project_id": project_id, "user_id": user_id},
    ).fetchone()
    if row is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", "プロジェクトが見つかりません。")
    return row


def _draft_row(conn: Any, project_id: str) -> Any:
    return conn.execute(
        "SELECT project_id, version, state_json, updated_at FROM project_drafts WHERE project_id = :project_id",
        {"project_id": project_id},
    ).fetchone()


def _artifact_payload(row: Any) -> Dict[str, Any]:
    data = _row_dict(row)
    if not data:
        return {}
    return {
        "id": data["id"],
        "project_id": data["project_id"],
        "generation_run_id": data.get("generation_run_id"),
        "project_revision_id": data.get("project_revision_id"),
        "job_id": data.get("job_id"),
        "kind": data["artifact_kind"],
        "stage": data["stage"],
        "status": data["status"],
        "original_filename": data["original_filename"],
        "media_type": data["media_type"],
        "sha256": data["sha256"],
        "size_bytes": int(data["size_bytes"] or 0),
        "metadata": _loads(data.get("metadata_json"), {}),
        "content_url": f"/api/artifacts/{data['id']}/content",
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def register_stored_file(
    stored: StoredFile,
    *,
    project_id: str,
    user_id: Optional[str],
    artifact_kind: str,
    stage: str,
    run_id: Optional[str] = None,
    revision_id: Optional[str] = None,
    job_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = _now_iso()
    try:
        with db_conn() as conn:
            conn.execute(
                """
                INSERT INTO artifacts (
                    id, project_id, generation_run_id, project_revision_id, job_id,
                    artifact_kind, stage, status, storage_backend, storage_key,
                    original_filename, media_type, sha256, size_bytes, metadata_json,
                    created_by_user_id, created_at, updated_at
                ) VALUES (
                    :id, :project_id, :generation_run_id, :project_revision_id, :job_id,
                    :artifact_kind, :stage, 'active', 'local', :storage_key,
                    :original_filename, :media_type, :sha256, :size_bytes, :metadata_json,
                    :created_by_user_id, :created_at, :updated_at
                )
                """,
                {
                    "id": stored.artifact_id,
                    "project_id": project_id,
                    "generation_run_id": run_id,
                    "project_revision_id": revision_id,
                    "job_id": job_id,
                    "artifact_kind": artifact_kind,
                    "stage": stage,
                    "storage_key": stored.storage_key,
                    "original_filename": stored.original_filename,
                    "media_type": stored.media_type,
                    "sha256": stored.sha256,
                    "size_bytes": stored.size_bytes,
                    "metadata_json": json_text(metadata or {}),
                    "created_by_user_id": user_id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            row = conn.execute("SELECT * FROM artifacts WHERE id = :id", {"id": stored.artifact_id}).fetchone()
    except Exception:
        stored.path.unlink(missing_ok=True)
        raise
    return _artifact_payload(row)


def publish_json_artifact(
    payload: Dict[str, Any],
    *,
    project_id: str,
    user_id: Optional[str],
    artifact_kind: str,
    stage: str,
    run_id: Optional[str] = None,
    revision_id: Optional[str] = None,
    job_id: Optional[str] = None,
    filename: str = "data.json",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    stream = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    stored = get_artifact_store().put_stream(
        stream,
        project_id=project_id,
        run_id=run_id,
        stage=stage,
        original_filename=filename,
        media_type="application/json",
    )
    return register_stored_file(
        stored,
        project_id=project_id,
        user_id=user_id,
        artifact_kind=artifact_kind,
        stage=stage,
        run_id=run_id,
        revision_id=revision_id,
        job_id=job_id,
        metadata=metadata,
    )


def link_artifacts(source_id: str, target_id: str, relation_type: str) -> None:
    now = _now_iso()
    with db_conn() as conn:
        existing = conn.execute(
            """
            SELECT id FROM artifact_relations
            WHERE source_artifact_id = :source AND target_artifact_id = :target
              AND relation_type = :relation_type
            """,
            {"source": source_id, "target": target_id, "relation_type": relation_type},
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO artifact_relations (
                    id, source_artifact_id, target_artifact_id, relation_type, created_at
                ) VALUES (:id, :source, :target, :relation_type, :created_at)
                """,
                {
                    "id": f"arel_{uuid.uuid4().hex}",
                    "source": source_id,
                    "target": target_id,
                    "relation_type": relation_type,
                    "created_at": now,
                },
            )


def create_project_v2(
    *,
    user_id: str,
    experiment_id: Optional[str],
    name: str,
    usage_context: str = "general",
) -> Dict[str, Any]:
    context = usage_context if usage_context in VALID_USAGE_CONTEXTS else "general"
    now = _now_iso()
    project_id = f"project_{uuid.uuid4().hex}"
    state = {
        "project_meta": {
            "id": project_id,
            "name": str(name or "").strip() or "新しいプロジェクト",
            "created_at": now,
            "updated_at": now,
            "version_number": 1,
        },
        "slides": [],
        "sentences": [],
        "highlights": [],
        "input_pdf": None,
        "generation_ref": None,
    }
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, user_id, experiment_id, name, latest_state_json,
                generation_refs_json, review_states_json, usage_context,
                analysis_status, created_at, updated_at
            ) VALUES (
                :id, :user_id, :experiment_id, :name, '{}', '{}', '{}',
                :usage_context, :analysis_status, :created_at, :updated_at
            )
            """,
            {
                "id": project_id,
                "user_id": user_id,
                "experiment_id": experiment_id,
                "name": state["project_meta"]["name"],
                "usage_context": context,
                "analysis_status": "candidate" if context == "research" else "excluded",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            """
            INSERT INTO project_drafts (
                project_id, version, state_json, updated_by_user_id, created_at, updated_at
            ) VALUES (:project_id, 1, :state_json, :user_id, :created_at, :updated_at)
            """,
            {
                "project_id": project_id,
                "state_json": json_text(state),
                "user_id": user_id,
                "created_at": now,
                "updated_at": now,
            },
        )
    return get_project_v2(project_id, user_id)


def _input_pdf_from_artifact(artifact: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not artifact:
        return None
    return {
        "name": artifact["original_filename"],
        "type": artifact["media_type"],
        "size": artifact["size_bytes"],
        "sha256": artifact["sha256"],
        "storage_key": artifact["id"],
        "artifact_id": artifact["id"],
        "artifact_kind": "input_pdf",
        "available": artifact["status"] == "active",
        "download_url": artifact["content_url"],
    }


def _legacy_input_pdf_payload(value: Any, project_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    storage_key = str(value.get("sha256") or value.get("storage_key") or "").strip()
    if not storage_key:
        return None
    available = bool(value.get("available", True))
    try:
        size = int(value.get("size") or 0)
    except Exception:
        size = 0
    return {
        "name": str(value.get("name") or "slides.pdf"),
        "type": str(value.get("type") or "application/pdf"),
        "size": size,
        "last_modified": value.get("last_modified"),
        "sha256": storage_key,
        "storage_key": storage_key,
        "artifact_kind": "input_pdf",
        "available": available,
        "download_url": f"/api/projects/{project_id}/pdf" if available else None,
    }


def _review_states(conn: Any, run_id: Optional[str]) -> Dict[str, Any]:
    if not run_id:
        return {}
    rows = conn.execute(
        """
        SELECT stage, status, version_number, output_revision_id, invalidated_reason,
               confirmed_at, updated_at
        FROM review_stage_versions
        WHERE generation_run_id = :run_id
        ORDER BY stage, version_number DESC
        """,
        {"run_id": run_id},
    ).fetchall()
    result: Dict[str, Any] = {}
    for row in rows:
        if row["stage"] in result:
            continue
        result[row["stage"]] = {
            "status": row["status"],
            "version_number": row["version_number"],
            "revision_id": row["output_revision_id"],
            "invalidated_reason": row["invalidated_reason"],
            "confirmed_at": row["confirmed_at"],
            "updated_at": row["updated_at"],
        }
    return result


def _restore_slide_artifact_refs(
    conn: Any,
    state: Dict[str, Any],
    run_id: Optional[str],
) -> Dict[str, Any]:
    slides = state.get("slides")
    if not run_id or not isinstance(slides, list) or not slides:
        return state
    rows = conn.execute(
        """
        SELECT *
        FROM artifacts
        WHERE generation_run_id = :run_id
          AND artifact_kind = 'slide_image'
          AND status = 'active'
        ORDER BY created_at
        """,
        {"run_id": run_id},
    ).fetchall()
    by_index: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        artifact = _artifact_payload(row)
        try:
            slide_idx = int(artifact.get("metadata", {}).get("slide_idx", 0))
        except (TypeError, ValueError):
            continue
        by_index.setdefault(slide_idx, artifact)
    if not by_index:
        return state

    restored_slides = []
    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict):
            restored_slides.append(slide)
            continue
        artifact = by_index.get(idx)
        if not artifact:
            restored_slides.append(slide)
            continue
        restored_slides.append(
            {
                **slide,
                "image_artifact_id": artifact["id"],
                "image_url": artifact["content_url"],
                "image_available": True,
            }
        )
    return {**state, "slides": restored_slides}


def get_project_v2(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        draft = _draft_row(conn, project_id)
        artifact_row = None
        if project["current_source_artifact_id"]:
            artifact_row = conn.execute(
                "SELECT * FROM artifacts WHERE id = :id",
                {"id": project["current_source_artifact_id"]},
            ).fetchone()
        source = _artifact_payload(artifact_row)
        review_states = _review_states(conn, project["active_run_id"])
        state = _loads(draft["state_json"] if draft else project["latest_state_json"], {})
        if not isinstance(state, dict):
            state = {}
        state = _restore_slide_artifact_refs(conn, state, project["active_run_id"])
    input_pdf = _input_pdf_from_artifact(source)
    if input_pdf is None:
        input_pdf = _legacy_input_pdf_payload(state.get("input_pdf"), project["id"])
    state = {
        **state,
        "project_meta": {
            **(state.get("project_meta") if isinstance(state.get("project_meta"), dict) else {}),
            "id": project["id"],
            "name": project["name"],
            "created_at": project["created_at"],
            "updated_at": project["updated_at"],
            "version_number": int(draft["version"] if draft else 1),
        },
        "input_pdf": input_pdf,
        "review_states": review_states,
    }
    return {
        "id": project["id"],
        "name": project["name"],
        "created_at": project["created_at"],
        "updated_at": project["updated_at"],
        "experiment_id": project["experiment_id"],
        "usage_context": project["usage_context"],
        "analysis_status": project["analysis_status"],
        "archived_at": project["archived_at"],
        "active_run_id": project["active_run_id"],
        "draft_version": int(draft["version"] if draft else 1),
        "source_artifact": source or None,
        "review_states": review_states,
        "data": state,
    }


def list_projects_v2(user_id: str) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.experiment_id, p.usage_context, p.analysis_status,
                   p.current_source_artifact_id, p.active_run_id, p.archived_at,
                   p.created_at, p.updated_at,
                   COALESCE(d.version, 1) AS draft_version,
                   COALESCE(d.state_json, p.latest_state_json, '{}') AS effective_state_json
            FROM projects AS p
            LEFT JOIN project_drafts AS d ON d.project_id = p.id
            WHERE p.user_id = :user_id AND p.archived_at IS NULL
            ORDER BY p.updated_at DESC
            """,
            {"user_id": user_id},
        ).fetchall()
    result = []
    for row in rows:
        state = _loads(row["effective_state_json"], {})
        if not isinstance(state, dict):
            state = {}
        input_pdf = state.get("input_pdf") if isinstance(state, dict) else None
        legacy_pdf = _legacy_input_pdf_payload(input_pdf, row["id"])
        result.append(
            {
                "id": row["id"],
                "name": row["name"],
                "experiment_id": row["experiment_id"],
                "usage_context": row["usage_context"],
                "analysis_status": row["analysis_status"],
                "active_run_id": row["active_run_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "draft_version": int(row["draft_version"] or 1),
                "mode": state.get("mode"),
                "slide_count": len(state.get("slides") or []),
                "sentence_count": len(state.get("sentences") or []),
                "highlight_count": len(state.get("highlights") or []),
                "input_pdf": legacy_pdf,
                "has_pdf": bool(row["current_source_artifact_id"] or (legacy_pdf and legacy_pdf["available"])),
            }
        )
    return result


def save_source_pdf(
    *,
    project_id: str,
    user_id: str,
    stream: BinaryIO,
    filename: str,
    media_type: str,
) -> Dict[str, Any]:
    if get_artifact_store().disk_status()["generation_blocked"]:
        raise ApiError(507, "STORAGE_CAPACITY_EXCEEDED", "保存領域が90％を超えたため，新しいPDFを保存できません。")
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        previous_id = project["current_source_artifact_id"]
        previous_run_id = project["active_run_id"]
        previous_artifact = None
        if previous_id:
            previous_artifact = conn.execute(
                "SELECT * FROM artifacts WHERE id = :artifact_id",
                {"artifact_id": previous_id},
            ).fetchone()
    header = stream.read(1024)
    if b"%PDF" not in header:
        raise ApiError(400, "INVALID_PDF", "PDFファイルとして認識できません。")
    stream.seek(0)
    try:
        stored = get_artifact_store().put_stream(
            stream,
            project_id=project_id,
            run_id=None,
            stage="source",
            original_filename=filename or "slides.pdf",
            media_type="application/pdf",
            max_bytes=MAX_PROJECT_PDF_BYTES,
        )
    except ValueError as exc:
        raise ApiError(413 if "large" in str(exc) else 400, "INVALID_PDF", str(exc)) from exc
    previous_payload = _artifact_payload(previous_artifact)
    if previous_payload and previous_payload.get("sha256") == stored.sha256:
        stored.path.unlink(missing_ok=True)
        current = get_project_v2(project_id, user_id)
        return {
            "ok": True,
            "unchanged": True,
            "artifact": current["source_artifact"],
            "input_pdf": current["data"]["input_pdf"],
            "draft_version": current["draft_version"],
        }
    artifact = register_stored_file(
        stored,
        project_id=project_id,
        user_id=user_id,
        artifact_kind="input_pdf",
        stage="source",
        metadata={"client_media_type": media_type},
    )
    now = _now_iso()
    try:
        with db_conn() as conn:
            _project_owner(conn, project_id, user_id)
            draft = _draft_row(conn, project_id)
            state = _loads(draft["state_json"] if draft else "{}", {})
            state = {
                **state,
                "slides": [],
                "sentences": [],
                "highlights": [],
                "total_duration": 0,
                "generated": False,
                "generation_ref": None,
                "review_states": {},
                "input_pdf": _input_pdf_from_artifact(artifact),
            }
            next_version = int(draft["version"] or 0) + 1
            conn.execute(
                """
                UPDATE projects
                SET current_source_artifact_id = :artifact_id, active_run_id = NULL,
                    updated_at = :updated_at
                WHERE id = :project_id
                """,
                {"artifact_id": artifact["id"], "updated_at": now, "project_id": project_id},
            )
            conn.execute(
                """
                UPDATE project_drafts
                SET version = :version, state_json = :state_json,
                    updated_by_user_id = :user_id, updated_at = :updated_at
                WHERE project_id = :project_id
                """,
                {
                    "version": next_version,
                    "state_json": json_text(state),
                    "user_id": user_id,
                    "updated_at": now,
                    "project_id": project_id,
                },
            )
            if previous_id:
                conn.execute(
                    """
                    UPDATE artifacts
                    SET status = 'superseded', updated_at = :updated_at
                    WHERE id = :artifact_id
                    """,
                    {"updated_at": now, "artifact_id": previous_id},
                )
            if previous_run_id:
                conn.execute(
                    """
                    UPDATE generation_runs
                    SET status = 'superseded', updated_at = :updated_at
                    WHERE id = :run_id AND status IN ('queued', 'running', 'completed')
                    """,
                    {"updated_at": now, "run_id": previous_run_id},
                )
                conn.execute(
                    """
                    UPDATE jobs
                    SET cancel_requested = 1, message = :message, updated_at = :updated_at
                    WHERE generation_run_id = :run_id AND status IN ('queued', 'running')
                    """,
                    {
                        "message": "入力PDFが差し替えられたため停止します",
                        "updated_at": now,
                        "run_id": previous_run_id,
                    },
                )
                _mark_stale(conn, previous_run_id, VALID_REVIEW_STAGES, "source_pdf_replaced", now)
                conn.execute(
                    """
                    UPDATE artifacts
                    SET status = 'stale', updated_at = :updated_at
                    WHERE generation_run_id = :run_id AND status = 'active'
                    """,
                    {"updated_at": now, "run_id": previous_run_id},
                )
    except Exception:
        with db_conn() as conn:
            conn.execute("DELETE FROM artifacts WHERE id = :artifact_id", {"artifact_id": artifact["id"]})
        stored.path.unlink(missing_ok=True)
        raise
    if previous_id:
        link_artifacts(previous_id, artifact["id"], "superseded_by")
    return {
        "ok": True,
        "artifact": artifact,
        "input_pdf": _input_pdf_from_artifact(artifact),
        "draft_version": next_version,
    }


def _script_signature(state: Dict[str, Any]) -> str:
    rows = [
        {
            "id": row.get("id"),
            "slide_idx": row.get("slide_idx"),
            "text": row.get("text"),
            "start_sec": row.get("start_sec"),
            "end_sec": row.get("end_sec"),
        }
        for row in (state.get("sentences") or [])
        if isinstance(row, dict)
    ]
    return hashlib.sha256(json_text(rows).encode("utf-8")).hexdigest()


def assert_preview_audio_input_current(
    *,
    project_id: str,
    run_id: str,
    user_id: str,
    scope: str,
    sentences: List[Dict[str, Any]],
) -> None:
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        run = conn.execute(
            """
            SELECT id FROM generation_runs
            WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
            """,
            {"run_id": run_id, "project_id": project_id, "user_id": user_id},
        ).fetchone()
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "音声プレビューを保存する生成runが見つかりません。")
        draft = _draft_row(conn, project_id)
        current_state = _loads(draft["state_json"] if draft else "{}", {})
    requested_signature = _script_signature({"sentences": sentences})
    if scope == "all":
        current_signature = _script_signature(current_state)
    else:
        requested_ids = {str(row.get("id")) for row in sentences if isinstance(row, dict)}
        current_signature = _script_signature({
            "sentences": [
                row
                for row in (current_state.get("sentences") or [])
                if isinstance(row, dict) and str(row.get("id")) in requested_ids
            ],
        })
    if current_signature != requested_signature:
        raise ApiError(
            409,
            "PREVIEW_AUDIO_INPUT_STALE",
            "音声生成中に台本が更新されました。最新の台本で再度プレビューしてください。",
        )


def _layout_signature(state: Dict[str, Any]) -> str:
    rows = [
        {
            "id": row.get("id"),
            "slide_idx": row.get("slide_idx"),
            "x": row.get("x"),
            "y": row.get("y"),
            "w": row.get("w"),
            "h": row.get("h"),
            "kind": row.get("kind"),
            "region_id": row.get("region_id"),
            "region_type": row.get("region_type"),
        }
        for row in (state.get("highlights") or [])
        if isinstance(row, dict)
    ]
    return hashlib.sha256(json_text(rows).encode("utf-8")).hexdigest()


def _assignment_signature(state: Dict[str, Any]) -> str:
    rows = [
        {
            "id": row.get("id"),
            "sentence_ids": row.get("sentence_ids"),
            "sid": row.get("sid"),
        }
        for row in (state.get("highlights") or [])
        if isinstance(row, dict)
    ]
    return hashlib.sha256(json_text(rows).encode("utf-8")).hexdigest()


def _mark_stale(conn: Any, run_id: Optional[str], stages: Iterable[str], reason: str, now: str) -> None:
    if not run_id:
        return
    for stage in stages:
        conn.execute(
            """
            UPDATE review_stage_versions
            SET status = 'stale', invalidated_reason = :reason, updated_at = :updated_at
            WHERE generation_run_id = :run_id AND stage = :stage AND status = 'confirmed'
            """,
            {"reason": reason, "updated_at": now, "run_id": run_id, "stage": stage},
        )


def save_project_draft(
    *,
    project_id: str,
    user_id: str,
    base_version: int,
    state: Dict[str, Any],
    name: Optional[str] = None,
) -> Dict[str, Any]:
    _assert_json_safe(state)
    now = _now_iso()
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        draft = _draft_row(conn, project_id)
        current_version = int(draft["version"] or 0)
        if int(base_version) != current_version:
            raise ApiError(
                409,
                "DRAFT_VERSION_CONFLICT",
                f"別の保存が先に反映されています。現在のversionは{current_version}です。",
            )
        previous = _loads(draft["state_json"], {})
        next_state = dict(state)
        source_row = None
        if project["current_source_artifact_id"]:
            source_row = conn.execute(
                "SELECT * FROM artifacts WHERE id = :id",
                {"id": project["current_source_artifact_id"]},
            ).fetchone()
        next_state = _restore_slide_artifact_refs(conn, next_state, project["active_run_id"])
        next_state["input_pdf"] = _input_pdf_from_artifact(_artifact_payload(source_row))
        clean_name = str(name or project["name"]).strip() or project["name"]
        next_version = current_version + 1
        next_state["project_meta"] = {
            **(next_state.get("project_meta") if isinstance(next_state.get("project_meta"), dict) else {}),
            "id": project_id,
            "name": clean_name,
            "created_at": project["created_at"],
            "updated_at": now,
            "version_number": next_version,
        }
        script_changed = _script_signature(previous) != _script_signature(next_state)
        layout_changed = _layout_signature(previous) != _layout_signature(next_state)
        assignment_changed = _assignment_signature(previous) != _assignment_signature(next_state)
        render_changed = layout_changed or script_changed or assignment_changed
        conn.execute(
            """
            UPDATE project_drafts
            SET version = :version, state_json = :state_json,
                updated_by_user_id = :user_id, updated_at = :updated_at
            WHERE project_id = :project_id
            """,
            {
                "version": next_version,
                "state_json": json_text(next_state),
                "user_id": user_id,
                "updated_at": now,
                "project_id": project_id,
            },
        )
        conn.execute(
            "UPDATE projects SET name = :name, updated_at = :updated_at WHERE id = :project_id",
            {"name": clean_name, "updated_at": now, "project_id": project_id},
        )
        if layout_changed:
            _mark_stale(conn, project["active_run_id"], ("layout", "assignment"), "layout_edited", now)
        if script_changed:
            _mark_stale(conn, project["active_run_id"], ("script", "assignment"), "script_edited", now)
            conn.execute(
                """
                UPDATE artifacts SET status = 'stale', updated_at = :updated_at
                WHERE project_id = :project_id AND artifact_kind IN ('preview_audio', 'preview_audio_manifest')
                  AND status = 'active'
                """,
                {"updated_at": now, "project_id": project_id},
            )
        elif assignment_changed:
            _mark_stale(conn, project["active_run_id"], ("assignment",), "assignment_edited", now)
        if render_changed:
            conn.execute(
                """
                UPDATE artifacts SET status = 'stale', updated_at = :updated_at
                WHERE project_id = :project_id
                  AND artifact_kind IN ('final_render', 'final_render_manifest')
                  AND status = 'active'
                """,
                {"updated_at": now, "project_id": project_id},
            )
    return get_project_v2(project_id, user_id)


def create_revision(
    conn: Any,
    *,
    project_id: str,
    user_id: str,
    run_id: Optional[str],
    revision_kind: str,
) -> Dict[str, Any]:
    draft = _draft_row(conn, project_id)
    if draft is None:
        raise ApiError(409, "DRAFT_NOT_FOUND", "保存対象のdraftがありません。")
    last = conn.execute(
        """
        SELECT id, revision_number FROM project_revisions
        WHERE project_id = :project_id
        ORDER BY revision_number DESC LIMIT 1
        """,
        {"project_id": project_id},
    ).fetchone()
    revision_number = int(last["revision_number"] or 0) + 1 if last else 1
    revision_id = f"revision_{uuid.uuid4().hex}"
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO project_revisions (
            id, project_id, generation_run_id, revision_number, revision_kind,
            parent_revision_id, draft_version, state_json, created_by_user_id, created_at
        ) VALUES (
            :id, :project_id, :run_id, :revision_number, :revision_kind,
            :parent_revision_id, :draft_version, :state_json, :user_id, :created_at
        )
        """,
        {
            "id": revision_id,
            "project_id": project_id,
            "run_id": run_id,
            "revision_number": revision_number,
            "revision_kind": revision_kind,
            "parent_revision_id": last["id"] if last else None,
            "draft_version": int(draft["version"]),
            "state_json": draft["state_json"],
            "user_id": user_id,
            "created_at": now,
        },
    )
    return {
        "id": revision_id,
        "revision_number": revision_number,
        "parent_revision_id": last["id"] if last else None,
        "draft_version": int(draft["version"]),
        "revision_kind": revision_kind,
        "created_at": now,
    }


def checkpoint_project(project_id: str, user_id: str, revision_kind: str = "manual_save") -> Dict[str, Any]:
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        revision = create_revision(
            conn,
            project_id=project_id,
            user_id=user_id,
            run_id=project["active_run_id"],
            revision_kind=revision_kind,
        )
    return revision


def confirm_review_stage(
    *,
    project_id: str,
    user_id: str,
    run_id: str,
    stage: str,
    draft_version: int,
) -> Dict[str, Any]:
    if stage not in VALID_REVIEW_STAGES:
        raise ApiError(400, "INVALID_REVIEW_STAGE", "確認ステップが不正です。")
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        run = conn.execute(
            """
            SELECT mode FROM generation_runs
            WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
            """,
            {"run_id": run_id, "project_id": project_id, "user_id": user_id},
        ).fetchone()
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", "生成runが見つかりません。")
    run_mode = str(run["mode"])
    if stage == "assignment" and run_mode != "hl":
        raise ApiError(409, "ASSIGNMENT_NOT_REQUIRED", "この提示形態では領域と台本の対応確認は行いません。")
    if stage == "script" and run_mode == "hl":
        with db_conn() as conn:
            existing_layout = conn.execute(
                """
                SELECT id FROM review_stage_versions
                WHERE generation_run_id = :run_id
                  AND stage = 'layout' AND status = 'confirmed'
                ORDER BY version_number DESC LIMIT 1
                """,
                {"run_id": run_id},
            ).fetchone()
        if existing_layout is None:
            confirm_review_stage(
                project_id=project_id,
                user_id=user_id,
                run_id=run_id,
                stage="layout",
                draft_version=draft_version,
            )
    now = _now_iso()
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        draft = _draft_row(conn, project_id)
        if int(draft["version"]) != int(draft_version):
            raise ApiError(409, "DRAFT_VERSION_CONFLICT", "最新の編集内容を保存してから確認してください。")
        required_stages = (
            ("layout",)
            if stage == "script" and run_mode == "hl"
            else ("layout", "script")
            if stage == "assignment"
            else ()
        )
        for required_stage in required_stages:
            required = conn.execute(
                """
                SELECT id FROM review_stage_versions
                WHERE generation_run_id = :run_id AND stage = :stage AND status = 'confirmed'
                ORDER BY version_number DESC LIMIT 1
                """,
                {"run_id": run_id, "stage": required_stage},
            ).fetchone()
            if required is None:
                raise ApiError(409, "REVIEW_STAGE_ORDER_INVALID", f"{required_stage}確認を先に完了してください。")
        revision = create_revision(
            conn,
            project_id=project_id,
            user_id=user_id,
            run_id=run_id,
            revision_kind=f"{stage}_confirmed",
        )
        latest = conn.execute(
            """
            SELECT COALESCE(MAX(version_number), 0) AS max_version
            FROM review_stage_versions
            WHERE generation_run_id = :run_id AND stage = :stage
            """,
            {"run_id": run_id, "stage": stage},
        ).fetchone()
        version_number = int(latest["max_version"] or 0) + 1
        conn.execute(
            """
            UPDATE review_stage_versions
            SET status = 'superseded', updated_at = :updated_at
            WHERE generation_run_id = :run_id AND stage = :stage AND status = 'confirmed'
            """,
            {"updated_at": now, "run_id": run_id, "stage": stage},
        )
        stage_id = f"review_{uuid.uuid4().hex}"
        conn.execute(
            """
            INSERT INTO review_stage_versions (
                id, project_id, generation_run_id, stage, version_number, status,
                input_revision_id, output_revision_id, confirmed_by_user_id,
                confirmed_at, updated_at
            ) VALUES (
                :id, :project_id, :run_id, :stage, :version_number, 'confirmed',
                :input_revision_id, :output_revision_id, :user_id, :confirmed_at, :updated_at
            )
            """,
            {
                "id": stage_id,
                "project_id": project_id,
                "run_id": run_id,
                "stage": stage,
                "version_number": version_number,
                "input_revision_id": revision.get("parent_revision_id"),
                "output_revision_id": revision["id"],
                "user_id": user_id,
                "confirmed_at": now,
                "updated_at": now,
            },
        )
    return {
        "ok": True,
        "stage": stage,
        "status": "confirmed",
        "stage_version": version_number,
        "revision": revision,
        "review_states": get_project_v2(project_id, user_id)["review_states"],
    }


def _confirmed_stage_revision(conn: Any, run_id: str, stage: str) -> Any:
    row = conn.execute(
        """
        SELECT rsv.id AS stage_id, rsv.output_revision_id, pr.state_json, pr.draft_version
        FROM review_stage_versions AS rsv
        JOIN project_revisions AS pr ON pr.id = rsv.output_revision_id
        WHERE rsv.generation_run_id = :run_id
          AND rsv.stage = :stage
          AND rsv.status = 'confirmed'
        ORDER BY rsv.version_number DESC
        LIMIT 1
        """,
        {"run_id": run_id, "stage": stage},
    ).fetchone()
    if row is None:
        raise ApiError(
            409,
            "REVIEW_STAGE_NOT_CONFIRMED",
            f"{stage}確認済みrevisionがありません。",
        )
    return row


def create_final_render_input_revision(
    *,
    project_id: str,
    user_id: str,
    run_id: str,
    draft_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Freeze the latest saved draft used by a plain video render."""
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        run = conn.execute(
            """
            SELECT mode FROM generation_runs
            WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
            """,
            {"run_id": run_id, "project_id": project_id, "user_id": user_id},
        ).fetchone()
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "生成runが見つかりません。")
        if str(run["mode"]) == "audio":
            raise ApiError(409, "VIDEO_RENDER_NOT_AVAILABLE", "音声のみの生成runから動画は生成できません。")
        draft = _draft_row(conn, project_id)
        if draft is None:
            raise ApiError(409, "DRAFT_NOT_FOUND", "動画生成対象の保存済みデータがありません。")
        if draft_version is not None and int(draft["version"]) != int(draft_version):
            raise ApiError(409, "DRAFT_VERSION_CONFLICT", "最新の編集内容を保存してから動画を生成してください。")
        return create_revision(
            conn,
            project_id=project_id,
            user_id=user_id,
            run_id=run_id,
            revision_kind="render_input",
        )


def get_review_assignment_context(
    *,
    project_id: str,
    user_id: str,
    run_id: str,
) -> Dict[str, Any]:
    """Return the immutable layout/script revisions used by assignment generation."""
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        run = conn.execute(
            """
            SELECT id, source_artifact_id, mode, detail, difficulty
            FROM generation_runs
            WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
            """,
            {"run_id": run_id, "project_id": project_id, "user_id": user_id},
        ).fetchone()
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "生成runが見つかりません。")
        if str(run["mode"]) != "hl":
            raise ApiError(409, "ASSIGNMENT_NOT_REQUIRED", "この提示形態では領域と台本の対応付けを生成しません。")
        layout_revision = _confirmed_stage_revision(conn, run_id, "layout")
        script_revision = _confirmed_stage_revision(conn, run_id, "script")
        slide_rows = conn.execute(
            """
            SELECT *
            FROM artifacts
            WHERE generation_run_id = :run_id
              AND artifact_kind = 'slide_image'
              AND status = 'active'
            ORDER BY created_at
            """,
            {"run_id": run_id},
        ).fetchall()

    layout_state = _loads(layout_revision["state_json"], {})
    script_state = _loads(script_revision["state_json"], {})
    if not isinstance(layout_state.get("highlights"), list):
        raise ApiError(409, "LAYOUT_REVISION_INVALID", "領域確認revisionに領域データがありません。")
    if not isinstance(script_state.get("sentences"), list):
        raise ApiError(409, "SCRIPT_REVISION_INVALID", "台本確認revisionに台本データがありません。")

    slide_artifacts = []
    for row in slide_rows:
        artifact = _artifact_payload(row)
        artifact["path"] = get_artifact_store().resolve(row["storage_key"])
        slide_artifacts.append(artifact)
    slide_artifacts.sort(
        key=lambda row: (
            int(row.get("metadata", {}).get("slide_idx", 0)),
            str(row.get("created_at") or ""),
        )
    )
    unique_slides: Dict[int, Dict[str, Any]] = {}
    for artifact in slide_artifacts:
        slide_idx = int(artifact.get("metadata", {}).get("slide_idx", 0))
        unique_slides.setdefault(slide_idx, artifact)
    ordered_slide_artifacts = [unique_slides[idx] for idx in sorted(unique_slides)]
    if not ordered_slide_artifacts:
        raise ApiError(409, "SLIDE_ARTIFACTS_MISSING", "対応付けに使用するスライド画像がありません。")

    return {
        "project_id": project_id,
        "user_id": user_id,
        "run_id": run_id,
        "source_artifact_id": run["source_artifact_id"],
        "mode": run["mode"],
        "detail": run["detail"],
        "difficulty": run["difficulty"],
        "layout_stage_id": layout_revision["stage_id"],
        "layout_revision_id": layout_revision["output_revision_id"],
        "script_stage_id": script_revision["stage_id"],
        "script_revision_id": script_revision["output_revision_id"],
        "slides": script_state.get("slides") or layout_state.get("slides") or [],
        "sentences": script_state["sentences"],
        "highlights": layout_state["highlights"],
        "settings": script_state.get("settings") or {},
        "slide_artifacts": ordered_slide_artifacts,
    }


def assert_review_assignment_context_current(context: Dict[str, Any]) -> None:
    with db_conn() as conn:
        for stage, stage_id in (
            ("layout", context["layout_stage_id"]),
            ("script", context["script_stage_id"]),
        ):
            row = conn.execute(
                """
                SELECT id
                FROM review_stage_versions
                WHERE id = :id AND generation_run_id = :run_id
                  AND stage = :stage AND status = 'confirmed'
                """,
                {"id": stage_id, "run_id": context["run_id"], "stage": stage},
            ).fetchone()
            if row is None:
                raise ApiError(
                    409,
                    "REVIEW_INPUT_BECAME_STALE",
                    "対応付け生成中に領域または台本が変更されました。再確認してから生成してください。",
                )


def get_final_render_context(
    *,
    project_id: str,
    user_id: str,
    run_id: str,
    render_type: str = "video_highlight",
    input_revision_id: Optional[str] = None,
) -> Dict[str, Any]:
    if render_type not in {"video", "video_highlight"}:
        raise ApiError(400, "INVALID_RENDER_TYPE", "動画の種類が不正です。")
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        run = conn.execute(
            """
            SELECT id, source_artifact_id, mode, detail, difficulty
            FROM generation_runs
            WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
            """,
            {"run_id": run_id, "project_id": project_id, "user_id": user_id},
        ).fetchone()
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "生成runが見つかりません。")
        run_mode = str(run["mode"])
        if run_mode == "audio":
            raise ApiError(409, "VIDEO_RENDER_NOT_AVAILABLE", "音声のみの生成runから動画は生成できません。")
        if render_type == "video_highlight":
            if run_mode != "hl":
                raise ApiError(409, "HIGHLIGHT_RENDER_NOT_AVAILABLE", "ハイライトあり動画はハイライトありモードで生成してください。")
            input_revision = _confirmed_stage_revision(conn, run_id, "assignment")
            input_stage = "assignment"
        elif input_revision_id:
            input_revision = conn.execute(
                """
                SELECT id AS stage_id, id AS output_revision_id, state_json, draft_version
                FROM project_revisions
                WHERE id = :revision_id AND project_id = :project_id
                  AND generation_run_id = :run_id AND revision_kind = 'render_input'
                """,
                {
                    "revision_id": input_revision_id,
                    "project_id": project_id,
                    "run_id": run_id,
                },
            ).fetchone()
            if input_revision is None:
                raise ApiError(409, "FINAL_RENDER_REVISION_INVALID", "動画生成用revisionが見つかりません。")
            input_stage = "render_input"
        else:
            input_revision = _confirmed_stage_revision(conn, run_id, "script")
            input_stage = "script"
        slide_rows = conn.execute(
            """
            SELECT *
            FROM artifacts
            WHERE generation_run_id = :run_id
              AND artifact_kind = 'slide_image'
              AND status = 'active'
            ORDER BY created_at
            """,
            {"run_id": run_id},
        ).fetchall()
    state = _loads(input_revision["state_json"], {})
    if not state.get("sentences") or not state.get("slides"):
        raise ApiError(409, "FINAL_RENDER_REVISION_INVALID", "最終確認revisionに講義データがありません。")
    by_index: Dict[int, Dict[str, Any]] = {}
    for row in slide_rows:
        artifact = _artifact_payload(row)
        artifact["path"] = get_artifact_store().resolve(row["storage_key"])
        slide_idx = int(artifact.get("metadata", {}).get("slide_idx", 0))
        by_index.setdefault(slide_idx, artifact)
    if len(by_index) < len(state.get("slides") or []):
        raise ApiError(409, "SLIDE_ARTIFACTS_MISSING", "最終動画に使用するスライド画像が不足しています。")
    return {
        "project_id": project_id,
        "user_id": user_id,
        "run_id": run_id,
        "source_artifact_id": run["source_artifact_id"],
        "mode": run["mode"],
        "detail": run["detail"],
        "difficulty": run["difficulty"],
        "render_type": render_type,
        "input_stage": input_stage,
        "input_stage_id": input_revision["stage_id"],
        "input_revision_id": input_revision["output_revision_id"],
        "input_draft_version": int(input_revision["draft_version"]),
        "assignment_stage_id": input_revision["stage_id"] if input_stage == "assignment" else None,
        "assignment_revision_id": input_revision["output_revision_id"] if input_stage == "assignment" else None,
        "state": state,
        "slide_artifacts": [by_index[idx] for idx in sorted(by_index)],
    }


def assert_final_render_context_current(context: Dict[str, Any]) -> None:
    with db_conn() as conn:
        if context["input_stage"] == "render_input":
            row = conn.execute(
                """
                SELECT pr.id
                FROM project_revisions AS pr
                JOIN projects AS p ON p.id = pr.project_id
                JOIN project_drafts AS pd ON pd.project_id = p.id
                WHERE pr.id = :id AND pr.generation_run_id = :run_id
                  AND pr.revision_kind = 'render_input'
                  AND p.active_run_id = :run_id
                  AND pd.version = :draft_version
                """,
                {
                    "id": context["input_revision_id"],
                    "run_id": context["run_id"],
                    "draft_version": context["input_draft_version"],
                },
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT id FROM review_stage_versions
                WHERE id = :id AND generation_run_id = :run_id
                  AND stage = :stage AND status = 'confirmed'
                """,
                {
                    "id": context["input_stage_id"],
                    "run_id": context["run_id"],
                    "stage": context["input_stage"],
                },
            ).fetchone()
    if row is None:
        raise ApiError(
            409,
            "FINAL_RENDER_INPUT_BECAME_STALE",
            "動画生成中に台本または対応付けが変更されました。結果は採用できません。",
        )


def create_generation_run_v2(
    *,
    project_id: str,
    user_id: str,
    experiment_id: Optional[str],
    source_artifact_id: str,
    mode: str,
    detail: str,
    difficulty: str,
    conditions: Dict[str, Any],
    usage_context: str,
) -> Dict[str, Any]:
    disk = get_artifact_store().disk_status()
    if disk["generation_blocked"]:
        raise ApiError(507, "STORAGE_CAPACITY_EXCEEDED", "保存領域が90％を超えたため，新規生成を停止しています。")
    context = usage_context if usage_context in VALID_USAGE_CONTEXTS else "general"
    now = _now_iso()
    run_id = f"run_{uuid.uuid4().hex}"
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        if project["current_source_artifact_id"] != source_artifact_id:
            raise ApiError(409, "SOURCE_PDF_NOT_CURRENT", "現在のプロジェクトに保存されているPDFを指定してください。")
        source = conn.execute(
            """
            SELECT id, sha256, original_filename FROM artifacts
            WHERE id = :artifact_id AND project_id = :project_id
              AND artifact_kind = 'input_pdf' AND status = 'active'
            """,
            {"artifact_id": source_artifact_id, "project_id": project_id},
        ).fetchone()
        if source is None:
            raise ApiError(404, "SOURCE_PDF_NOT_FOUND", "生成に使用するPDFが見つかりません。")
        previous_run_id = project["active_run_id"]
        if previous_run_id:
            conn.execute(
                """
                UPDATE generation_runs
                SET status = 'superseded', updated_at = :updated_at
                WHERE id = :run_id AND status IN ('queued', 'running', 'completed')
                """,
                {"run_id": previous_run_id, "updated_at": now},
            )
            conn.execute(
                """
                UPDATE jobs
                SET cancel_requested = 1, message = :message, updated_at = :updated_at
                WHERE generation_run_id = :run_id AND status IN ('queued', 'running')
                """,
                {
                    "run_id": previous_run_id,
                    "message": "新しい生成runが開始されたため停止します",
                    "updated_at": now,
                },
            )
            _mark_stale(conn, previous_run_id, VALID_REVIEW_STAGES, "new_run_started", now)
            conn.execute(
                """
                UPDATE artifacts
                SET status = 'stale', updated_at = :updated_at
                WHERE generation_run_id = :run_id AND status = 'active'
                """,
                {"run_id": previous_run_id, "updated_at": now},
            )
        conn.execute(
            """
            INSERT INTO generation_runs (
                id, job_id, project_id, user_id, experiment_id, request_key, pdf_hash,
                filename, mode, detail, difficulty, condition_json, prompt_strategy_version,
                status, artifact_refs_json, result_summary_json, source_artifact_id,
                usage_context, analysis_status, model_json, prompt_json, created_at, updated_at
            ) VALUES (
                :id, NULL, :project_id, :user_id, :experiment_id, NULL, :pdf_hash,
                :filename, :mode, :detail, :difficulty, :condition_json, :prompt_version,
                'queued', '{}', '{}', :source_artifact_id,
                :usage_context, :analysis_status, :model_json, :prompt_json, :created_at, :updated_at
            )
            """,
            {
                "id": run_id,
                "project_id": project_id,
                "user_id": user_id,
                "experiment_id": experiment_id or project["experiment_id"],
                "pdf_hash": source["sha256"],
                "filename": source["original_filename"],
                "mode": mode,
                "detail": detail,
                "difficulty": difficulty,
                "condition_json": json_text(conditions),
                "prompt_version": conditions.get("prompt_strategy_version"),
                "source_artifact_id": source_artifact_id,
                "usage_context": context,
                "analysis_status": "candidate" if context == "research" else "excluded",
                "model_json": json_text(
                    {
                        "explanation": os.getenv("LECTURE_CRAFT_MODEL_EXPLANATION", "gpt-5"),
                        "animation": os.getenv("LECTURE_CRAFT_MODEL_ANIMATION", "gpt-5"),
                        "tts": "gpt-4o-mini-tts",
                    }
                ),
                "prompt_json": json_text(
                    {
                        "strategy_version": conditions.get("prompt_strategy_version"),
                        "kg_mode": conditions.get("kg_mode", "off"),
                        "log_reuse_enabled": bool(conditions.get("log_reuse_enabled")),
                    }
                ),
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            """
            UPDATE projects
            SET active_run_id = :run_id, usage_context = :usage_context, updated_at = :updated_at
            WHERE id = :project_id
            """,
            {
                "run_id": run_id,
                "usage_context": context,
                "updated_at": now,
                "project_id": project_id,
            },
        )
    return get_generation_run_v2(run_id, user_id=user_id)


def generation_run_input(run_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT gr.*, a.storage_key, a.original_filename, a.media_type
            FROM generation_runs AS gr
            JOIN artifacts AS a ON a.id = gr.source_artifact_id
            WHERE gr.id = :run_id
            """,
            {"run_id": run_id},
        ).fetchone()
    if row is None:
        raise ApiError(404, "RUN_SOURCE_NOT_FOUND", "生成runの入力PDFが見つかりません。")
    data = _row_dict(row)
    path = get_artifact_store().resolve(data["storage_key"])
    if not path.exists():
        raise ApiError(404, "RUN_SOURCE_FILE_MISSING", "生成runの入力PDFファイルが見つかりません。")
    return {
        "run_id": data["id"],
        "project_id": data["project_id"],
        "user_id": data["user_id"],
        "experiment_id": data["experiment_id"],
        "source_artifact_id": data["source_artifact_id"],
        "source_path": path,
        "filename": data["original_filename"],
        "mode": data["mode"],
        "detail": data["detail"],
        "difficulty": data["difficulty"],
        "conditions": _loads(data["condition_json"], {}),
    }


def assert_generation_run_current(*, run_id: str, project_id: str, user_id: str) -> None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT p.active_run_id, p.current_source_artifact_id, gr.source_artifact_id, gr.status
            FROM projects AS p
            JOIN generation_runs AS gr ON gr.project_id = p.id
            WHERE p.id = :project_id AND p.user_id = :user_id AND gr.id = :run_id
            """,
            {"project_id": project_id, "user_id": user_id, "run_id": run_id},
        ).fetchone()
    if (
        row is None
        or row["active_run_id"] != run_id
        or row["current_source_artifact_id"] != row["source_artifact_id"]
        or row["status"] in {"superseded", "failed", "cancelled"}
    ):
        raise ApiError(
            409,
            "GENERATION_RUN_STALE",
            "生成中に入力PDFまたは有効なrunが変更されたため，旧生成結果は反映しません。",
        )


def _classify_pipeline_artifact(relative: Path) -> tuple[str, str]:
    parts = relative.parts
    text = "/".join(parts).lower()
    suffix = relative.suffix.lower()
    if "/img/" in f"/{text}" and suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return "slide_image", "layout/slides"
    if "lp_output" in text:
        return ("layout_json" if suffix == ".json" else "layout_visual"), "layout/raw"
    if "lecture_text" in text or suffix == ".txt":
        return "generated_script", "script/generated"
    if "tts" in text or suffix in {".mp3", ".wav", ".m4a"}:
        return "generated_audio", "preview_audio/generated"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "generated_video", "final_render/generated"
    if "mapping" in text or "assignment" in text:
        return "assignment_output", "assignment/generated"
    return "pipeline_intermediate", "pipeline/intermediate"


def publish_generation_workspace(
    *,
    run_id: str,
    job_id: str,
    project_id: str,
    user_id: str,
    workspace: Path,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    store = get_artifact_store()
    published: List[Dict[str, Any]] = []
    slide_artifacts: List[Dict[str, Any]] = []
    source_artifact_id = generation_run_input(run_id)["source_artifact_id"]
    ignored_suffixes = {".tmp", ".lock", ".pyc"}
    for path in sorted(Path(workspace).rglob("*")):
        if not path.is_file() or path.suffix.lower() in ignored_suffixes or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(workspace)
        if len(relative.parts) >= 2 and relative.parts[0] == "material" and relative.parts[1] == "pdf":
            continue
        kind, stage = _classify_pipeline_artifact(relative)
        metadata: Dict[str, Any] = {"workspace_relative_path": str(relative)}
        if kind == "slide_image":
            digits = "".join(ch for ch in path.stem if ch.isdigit())
            metadata["slide_idx"] = max(0, int(digits or len(slide_artifacts) + 1) - 1)
        stored = store.put_file(
            path,
            project_id=project_id,
            run_id=run_id,
            stage=stage,
            original_filename=path.name,
        )
        artifact = register_stored_file(
            stored,
            project_id=project_id,
            user_id=user_id,
            artifact_kind=kind,
            stage=stage,
            run_id=run_id,
            job_id=job_id,
            metadata=metadata,
        )
        link_artifacts(source_artifact_id, artifact["id"], "input_to")
        published.append(artifact)
        if kind == "slide_image":
            slide_artifacts.append(artifact)

    slide_artifacts.sort(key=lambda row: int(row.get("metadata", {}).get("slide_idx", 0)))
    rewritten = dict(result)
    rewritten_slides = []
    for idx, slide in enumerate(result.get("slides") or []):
        clean_slide = {
            key: value
            for key, value in dict(slide).items()
            if key not in {"image_base64", "image_data_url", "image_blob_url"}
        }
        if idx < len(slide_artifacts):
            clean_slide.update(
                {
                    "image_artifact_id": slide_artifacts[idx]["id"],
                    "image_url": slide_artifacts[idx]["content_url"],
                    "image_available": True,
                }
            )
        rewritten_slides.append(clean_slide)
    rewritten["slides"] = rewritten_slides
    rewritten["generation_ref"] = {
        **(rewritten.get("generation_ref") or {}),
        "run_id": run_id,
        "job_id": job_id,
        "source_artifact_id": source_artifact_id,
    }
    if isinstance(rewritten.get("knowledge_graph"), dict):
        kg_artifact = publish_json_artifact(
            rewritten["knowledge_graph"],
            project_id=project_id,
            user_id=user_id,
            artifact_kind="knowledge_graph",
            stage="knowledge_graph/generated",
            run_id=run_id,
            job_id=job_id,
            filename="knowledge_graph.json",
        )
        link_artifacts(source_artifact_id, kg_artifact["id"], "input_to")
        published.append(kg_artifact)
    result_artifact = publish_json_artifact(
        rewritten,
        project_id=project_id,
        user_id=user_id,
        artifact_kind="generation_result",
        stage="script/result",
        run_id=run_id,
        job_id=job_id,
        filename="generation_result.json",
        metadata={
            "slide_count": len(rewritten_slides),
            "sentence_count": len(rewritten.get("sentences") or []),
            "highlight_count": len(rewritten.get("highlights") or []),
        },
    )
    link_artifacts(source_artifact_id, result_artifact["id"], "input_to")
    published.append(result_artifact)
    return {
        "result": rewritten,
        "result_artifact": result_artifact,
        "artifacts": published,
    }


def publish_review_assignment_workspace(
    *,
    context: Dict[str, Any],
    job_id: str,
    workspace: Path,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Persist reviewed assignment inputs and outputs without keeping the work tree."""
    store = get_artifact_store()
    published: List[Dict[str, Any]] = []
    revision_ids = [context["layout_revision_id"], context["script_revision_id"]]
    for path in sorted(Path(workspace).rglob("*")):
        if not path.is_file() or "material" in path.relative_to(workspace).parts:
            continue
        relative = path.relative_to(workspace)
        text = "/".join(relative.parts).lower()
        if "region_visuals" in text:
            kind, stage = "reviewed_layout_visual", "assignment/input/layout_visual"
        elif "lp_output" in text and path.suffix.lower() == ".json":
            kind, stage = "reviewed_layout_json", "assignment/input/layout_json"
        elif "lecture_texts" in text:
            kind, stage = "confirmed_script_input", "assignment/input/script"
        elif "mapping" in text or "animation" in text:
            kind, stage = "assignment_mapping", "assignment/output"
        else:
            kind, stage = "assignment_intermediate", "assignment/intermediate"
        stored = store.put_file(
            path,
            project_id=context["project_id"],
            run_id=context["run_id"],
            stage=stage,
            original_filename=path.name,
        )
        artifact = register_stored_file(
            stored,
            project_id=context["project_id"],
            user_id=context["user_id"],
            artifact_kind=kind,
            stage=stage,
            run_id=context["run_id"],
            job_id=job_id,
            metadata={
                "workspace_relative_path": str(relative),
                "input_revision_ids": revision_ids,
            },
        )
        link_artifacts(context["source_artifact_id"], artifact["id"], "input_to")
        published.append(artifact)

    clean_result = {
        **result,
        "generation_ref": {
            "run_id": context["run_id"],
            "job_id": job_id,
            "source_artifact_id": context["source_artifact_id"],
            "layout_revision_id": context["layout_revision_id"],
            "script_revision_id": context["script_revision_id"],
        },
    }
    result_artifact = publish_json_artifact(
        clean_result,
        project_id=context["project_id"],
        user_id=context["user_id"],
        artifact_kind="assignment_result",
        stage="assignment/result",
        run_id=context["run_id"],
        job_id=job_id,
        filename="assignment_result.json",
        metadata={
            "input_revision_ids": revision_ids,
            "sentence_count": len(clean_result.get("sentences") or []),
            "highlight_count": len(clean_result.get("highlights") or []),
        },
    )
    link_artifacts(context["source_artifact_id"], result_artifact["id"], "input_to")
    published.append(result_artifact)
    return {
        "result": clean_result,
        "result_artifact": result_artifact,
        "artifacts": published,
    }


def apply_review_assignment_result(
    *,
    context: Dict[str, Any],
    result: Dict[str, Any],
    result_artifact_id: str,
) -> Dict[str, Any]:
    _assert_json_safe(result)
    now = _now_iso()
    with db_conn() as conn:
        for stage, stage_id in (
            ("layout", context["layout_stage_id"]),
            ("script", context["script_stage_id"]),
        ):
            current = conn.execute(
                """
                SELECT id FROM review_stage_versions
                WHERE id = :id AND generation_run_id = :run_id
                  AND stage = :stage AND status = 'confirmed'
                """,
                {"id": stage_id, "run_id": context["run_id"], "stage": stage},
            ).fetchone()
            if current is None:
                raise ApiError(
                    409,
                    "REVIEW_INPUT_BECAME_STALE",
                    "対応付け生成中に領域または台本が変更されました。結果は適用していません。",
                )
        draft = _draft_row(conn, context["project_id"])
        current_state = _loads(draft["state_json"], {})
        next_version = int(draft["version"] or 0) + 1
        next_state = {
            **current_state,
            "sentences": result.get("sentences") or context["sentences"],
            "highlights": result.get("highlights") or [],
            "generation_ref": {
                **(current_state.get("generation_ref") or {}),
                **(result.get("generation_ref") or {}),
            },
        }
        project_meta = next_state.get("project_meta") if isinstance(next_state.get("project_meta"), dict) else {}
        next_state["project_meta"] = {
            **project_meta,
            "updated_at": now,
            "version_number": next_version,
        }
        conn.execute(
            """
            UPDATE project_drafts
            SET version = :version, state_json = :state_json,
                updated_by_user_id = :user_id, updated_at = :updated_at
            WHERE project_id = :project_id
            """,
            {
                "version": next_version,
                "state_json": json_text(next_state),
                "user_id": context["user_id"],
                "updated_at": now,
                "project_id": context["project_id"],
            },
        )
        revision = create_revision(
            conn,
            project_id=context["project_id"],
            user_id=context["user_id"],
            run_id=context["run_id"],
            revision_kind="assignment_generated",
        )
        conn.execute(
            """
            UPDATE artifacts
            SET project_revision_id = :revision_id, updated_at = :updated_at
            WHERE id = :artifact_id
            """,
            {
                "revision_id": revision["id"],
                "updated_at": now,
                "artifact_id": result_artifact_id,
            },
        )
    return {
        "draft_version": next_version,
        "revision": revision,
        "state": next_state,
    }


def publish_final_render_result(
    *,
    context: Dict[str, Any],
    job_id: str,
    media_path: Path,
    render_type: str,
) -> Dict[str, Any]:
    assert_final_render_context_current(context)
    stored = get_artifact_store().put_file(
        media_path,
        project_id=context["project_id"],
        run_id=context["run_id"],
        stage="final_render",
        original_filename="lecture.mp4",
        media_type="video/mp4",
    )
    try:
        assert_final_render_context_current(context)
    except Exception:
        stored.path.unlink(missing_ok=True)
        raise
    with db_conn() as conn:
        revision = create_revision(
            conn,
            project_id=context["project_id"],
            user_id=context["user_id"],
            run_id=context["run_id"],
            revision_kind="rendered",
        )
    media_artifact = register_stored_file(
        stored,
        project_id=context["project_id"],
        user_id=context["user_id"],
        artifact_kind="final_render",
        stage="final_render",
        run_id=context["run_id"],
        revision_id=revision["id"],
        job_id=job_id,
        metadata={
            "render_type": render_type,
            "input_revision_id": context["input_revision_id"],
        },
    )
    link_artifacts(context["source_artifact_id"], media_artifact["id"], "input_to")
    manifest = {
        "preview_id": job_id,
        "media_type": "video/mp4",
        "media_url": media_artifact["content_url"],
        "media_artifact_id": media_artifact["id"],
        "filename": "lecture.mp4",
        "render_type": render_type,
        "run_id": context["run_id"],
        "input_revision_id": context["input_revision_id"],
        "render_revision_id": revision["id"],
        "created_at": _now_iso(),
    }
    manifest_artifact = publish_json_artifact(
        manifest,
        project_id=context["project_id"],
        user_id=context["user_id"],
        artifact_kind="final_render_manifest",
        stage="final_render",
        run_id=context["run_id"],
        revision_id=revision["id"],
        job_id=job_id,
        filename="final_render_manifest.json",
        metadata={"media_artifact_id": media_artifact["id"]},
    )
    link_artifacts(media_artifact["id"], manifest_artifact["id"], "described_by")
    return {
        "result": manifest,
        "result_artifact": manifest_artifact,
        "media_artifact": media_artifact,
        "revision": revision,
    }


def publish_preview_audio_result(
    *,
    project_id: str,
    run_id: str,
    user_id: str,
    job_id: Optional[str],
    preview_id: str,
    clip_path: Path,
    cache_key: str,
    scope: str,
    duration: float,
    sentence_timings: List[Dict[str, Any]],
    clip_cache_hit: bool,
    sentence_cache_hits: int,
    sentence_count: int,
) -> Dict[str, Any]:
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        run = conn.execute(
            """
            SELECT id, source_artifact_id
            FROM generation_runs
            WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
            """,
            {"run_id": run_id, "project_id": project_id, "user_id": user_id},
        ).fetchone()
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "音声プレビューを保存する生成runが見つかりません。")
        if project["active_run_id"] != run_id:
            raise ApiError(409, "RUN_NOT_ACTIVE", "現在のプロジェクトに対応するrunではありません。")
        script_stage = conn.execute(
            """
            SELECT output_revision_id
            FROM review_stage_versions
            WHERE generation_run_id = :run_id AND stage = 'script' AND status = 'confirmed'
            ORDER BY version_number DESC LIMIT 1
            """,
            {"run_id": run_id},
        ).fetchone()

    digest = hashlib.sha256()
    with Path(clip_path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    clip_sha256 = digest.hexdigest()
    with db_conn() as conn:
        existing = conn.execute(
            """
            SELECT * FROM artifacts
            WHERE generation_run_id = :run_id AND artifact_kind = 'preview_audio'
              AND sha256 = :sha256 AND status = 'active'
            ORDER BY created_at DESC LIMIT 1
            """,
            {"run_id": run_id, "sha256": clip_sha256},
        ).fetchone()
    revision_id = script_stage["output_revision_id"] if script_stage else None
    reused = existing is not None
    if reused:
        audio_artifact = _artifact_payload(existing)
    else:
        stored = get_artifact_store().put_file(
            Path(clip_path),
            project_id=project_id,
            run_id=run_id,
            stage="preview_audio/clips",
            original_filename="preview.mp3",
            media_type="audio/mpeg",
        )
        audio_artifact = register_stored_file(
            stored,
            project_id=project_id,
            user_id=user_id,
            artifact_kind="preview_audio",
            stage="preview_audio/clips",
            run_id=run_id,
            revision_id=revision_id,
            job_id=job_id,
            metadata={
                "cache_key": cache_key,
                "scope": scope,
                "duration": duration,
                "sentence_count": sentence_count,
            },
        )
    manifest = {
        "version": 1,
        "preview_id": preview_id,
        "project_id": project_id,
        "run_id": run_id,
        "audio_url": audio_artifact["content_url"],
        "audio_artifact_id": audio_artifact["id"],
        "script_revision_id": revision_id,
        "cache_key": cache_key,
        "scope": scope,
        "duration": duration,
        "sentence_timings": sentence_timings,
        "cache_hit": bool(clip_cache_hit),
        "sentence_cache_hits": int(sentence_cache_hits),
        "sentence_count": int(sentence_count),
        "stale_key": cache_key,
        "created_at": _now_iso(),
    }
    manifest_artifact = publish_json_artifact(
        manifest,
        project_id=project_id,
        user_id=user_id,
        artifact_kind="preview_audio_manifest",
        stage="preview_audio/manifests",
        run_id=run_id,
        revision_id=revision_id,
        job_id=job_id,
        filename="preview_audio_manifest.json",
        metadata={"audio_artifact_id": audio_artifact["id"], "cache_key": cache_key},
    )
    if not reused:
        link_artifacts(run["source_artifact_id"], audio_artifact["id"], "input_to")
    link_artifacts(audio_artifact["id"], manifest_artifact["id"], "described_by")
    result = {
        **manifest,
        "audio_manifest_artifact_id": manifest_artifact["id"],
    }
    return {
        "result": result,
        "audio_artifact": audio_artifact,
        "manifest_artifact": manifest_artifact,
        "reused": reused,
    }


def publish_failed_job_workspace(
    *,
    project_id: str,
    run_id: Optional[str],
    user_id: Optional[str],
    job_id: str,
    error: str,
) -> List[Dict[str, Any]]:
    workspace = get_artifact_store().work_dir(job_id)
    published: List[Dict[str, Any]] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".txt", ".log"}:
            continue
        if path.stat().st_size > 20 * 1024 * 1024:
            continue
        stored = get_artifact_store().put_file(
            path,
            project_id=project_id,
            run_id=run_id,
            stage="debug",
            original_filename=path.name,
        )
        published.append(
            register_stored_file(
                stored,
                project_id=project_id,
                user_id=user_id,
                artifact_kind="job_debug",
                stage="debug",
                run_id=run_id,
                job_id=job_id,
                metadata={
                    "workspace_relative_path": str(path.relative_to(workspace)),
                    "error": error[:1000],
                },
            )
        )
    return published


def apply_generated_result(
    *,
    project_id: str,
    user_id: str,
    run_id: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    _assert_json_safe(result)
    now = _now_iso()
    with db_conn() as conn:
        project = _project_owner(conn, project_id, user_id)
        run = conn.execute(
            "SELECT source_artifact_id, status FROM generation_runs WHERE id = :run_id AND project_id = :project_id",
            {"run_id": run_id, "project_id": project_id},
        ).fetchone()
        if (
            run is None
            or project["active_run_id"] != run_id
            or project["current_source_artifact_id"] != run["source_artifact_id"]
            or run["status"] in {"superseded", "failed", "cancelled"}
        ):
            raise ApiError(
                409,
                "GENERATION_RUN_STALE",
                "生成中に入力PDFまたは有効なrunが変更されたため，旧生成結果は反映しません。",
            )
        draft = _draft_row(conn, project_id)
        previous = _loads(draft["state_json"], {})
        next_version = int(draft["version"] or 0) + 1
        source_row = conn.execute(
            "SELECT * FROM artifacts WHERE id = :id",
            {"id": project["current_source_artifact_id"]},
        ).fetchone()
        reviewed_layout = conn.execute(
            """
            SELECT pr.state_json
            FROM review_stage_versions AS rsv
            JOIN project_revisions AS pr ON pr.id = rsv.output_revision_id
            WHERE rsv.generation_run_id = :run_id
              AND rsv.stage = 'layout'
              AND rsv.status = 'confirmed'
            ORDER BY rsv.version_number DESC
            LIMIT 1
            """,
            {"run_id": run_id},
        ).fetchone()
        reviewed_layout_state = _loads(reviewed_layout["state_json"], {}) if reviewed_layout else {}
        previous_ref = previous.get("generation_ref") if isinstance(previous.get("generation_ref"), dict) else {}
        preserve_partial_layout = (
            previous_ref.get("run_id") == run_id
            and previous_ref.get("partial_stage") == "layout_ready"
            and isinstance(previous.get("highlights"), list)
        )
        merged_result = dict(result)
        if isinstance(reviewed_layout_state.get("highlights"), list):
            merged_result["highlights"] = reviewed_layout_state["highlights"]
        elif preserve_partial_layout:
            merged_result["highlights"] = previous["highlights"]
        next_state = {
            **previous,
            **merged_result,
            "input_pdf": _input_pdf_from_artifact(_artifact_payload(source_row)),
            "project_meta": {
                **(previous.get("project_meta") if isinstance(previous.get("project_meta"), dict) else {}),
                "id": project_id,
                "name": project["name"],
                "created_at": project["created_at"],
                "updated_at": now,
                "version_number": next_version,
            },
        }
        conn.execute(
            """
            UPDATE project_drafts
            SET version = :version, state_json = :state_json,
                updated_by_user_id = :user_id, updated_at = :updated_at
            WHERE project_id = :project_id
            """,
            {
                "version": next_version,
                "state_json": json_text(next_state),
                "user_id": user_id,
                "updated_at": now,
                "project_id": project_id,
            },
        )
        conn.execute(
            """
            UPDATE projects SET active_run_id = :run_id, updated_at = :updated_at
            WHERE id = :project_id
            """,
            {"run_id": run_id, "updated_at": now, "project_id": project_id},
        )
        revision = create_revision(
            conn,
            project_id=project_id,
            user_id=user_id,
            run_id=run_id,
            revision_kind="generation_completed",
        )
    return {"draft_version": next_version, "revision": revision, "state": next_state}


def attach_job_to_run(run_id: str, job_id: str) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE generation_runs
            SET job_id = :job_id, status = 'queued', updated_at = :updated_at
            WHERE id = :run_id
            """,
            {"job_id": job_id, "updated_at": _now_iso(), "run_id": run_id},
        )


def mark_generation_run_submission_failed(run_id: str, message: str) -> None:
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE generation_runs
            SET status = 'failed', result_summary_json = :summary, updated_at = :updated_at
            WHERE id = :run_id AND status = 'queued'
            """,
            {
                "run_id": run_id,
                "summary": json_text({"error": {"code": "JOB_PERSISTENCE_FAILED", "message": str(message)}}),
                "updated_at": _now_iso(),
            },
        )


def get_generation_run_v2(run_id: str, *, user_id: Optional[str] = None, admin: bool = False) -> Dict[str, Any]:
    with db_conn() as conn:
        query = "SELECT * FROM generation_runs WHERE id = :run_id"
        params: Dict[str, Any] = {"run_id": run_id}
        if not admin:
            query += " AND user_id = :user_id"
            params["user_id"] = user_id
        row = conn.execute(query, params).fetchone()
        if row is None:
            raise ApiError(404, "RUN_NOT_FOUND", "生成runが見つかりません。")
        artifacts = conn.execute(
            "SELECT * FROM artifacts WHERE generation_run_id = :run_id ORDER BY created_at",
            {"run_id": run_id},
        ).fetchall()
        job = conn.execute(
            "SELECT * FROM jobs WHERE generation_run_id = :run_id ORDER BY created_at DESC LIMIT 1",
            {"run_id": run_id},
        ).fetchone()
        reviews = _review_states(conn, run_id)
    data = _row_dict(row)
    return {
        "id": data["id"],
        "job_id": data.get("job_id"),
        "project_id": data.get("project_id"),
        "user_id": data.get("user_id") if admin else None,
        "experiment_id": data.get("experiment_id"),
        "source_artifact_id": data.get("source_artifact_id"),
        "mode": data["mode"],
        "detail": data["detail"],
        "difficulty": data["difficulty"],
        "conditions": _loads(data.get("condition_json"), {}),
        "models": _loads(data.get("model_json"), {}),
        "prompt": _loads(data.get("prompt_json"), {}),
        "prompt_strategy_version": data.get("prompt_strategy_version"),
        "usage_context": data.get("usage_context") or "general",
        "analysis_status": data.get("analysis_status") or "candidate",
        "status": data["status"],
        "result_summary": _loads(data.get("result_summary_json"), {}),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "job": _job_public_payload(job),
        "review_states": reviews,
        "artifacts": [_artifact_payload(item) for item in artifacts],
    }


def _job_public_payload(row: Any) -> Optional[Dict[str, Any]]:
    data = _row_dict(row)
    if not data:
        return None
    return {
        "job_id": data["id"],
        "kind": data["kind"],
        "status": data["status"],
        "progress": int(data["progress"] or 0),
        "message": data["message"],
        "error": _loads(data.get("error_json"), None),
        "partial_result": _loads(data.get("partial_result_json"), None),
        "cancel_requested": bool(data.get("cancel_requested")),
        "retry_count": int(data.get("retry_count") or 0),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def get_artifact_for_request(
    artifact_id: str,
    *,
    requester_user_id: str,
    requester_role: str,
) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT a.*, p.user_id AS owner_user_id
            FROM artifacts AS a
            JOIN projects AS p ON p.id = a.project_id
            WHERE a.id = :artifact_id
            """,
            {"artifact_id": artifact_id},
        ).fetchone()
    if row is None:
        raise ApiError(404, "ARTIFACT_NOT_FOUND", "成果物が見つかりません。")
    if requester_role != "admin" and row["owner_user_id"] != requester_user_id:
        raise ApiError(403, "ARTIFACT_FORBIDDEN", "この成果物を取得する権限がありません。")
    path = get_artifact_store().resolve(row["storage_key"])
    if not path.exists() or not path.is_file():
        raise ApiError(404, "ARTIFACT_FILE_MISSING", "成果物ファイルが見つかりません。")
    return {
        "path": path,
        "filename": row["original_filename"],
        "media_type": row["media_type"],
        "artifact": _artifact_payload(row),
    }


def list_admin_artifacts(
    *,
    project_id: Optional[str] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    where = ["1 = 1"]
    params: Dict[str, Any] = {"limit": min(500, max(1, int(limit)))}
    for column, key, value in (
        ("a.project_id", "project_id", project_id),
        ("a.generation_run_id", "run_id", run_id),
        ("p.user_id", "user_id", user_id),
        ("p.experiment_id", "experiment_id", experiment_id),
        ("a.artifact_kind", "kind", kind),
        ("a.status", "status", status),
    ):
        if value:
            where.append(f"{column} = :{key}")
            params[key] = value
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT a.*, p.user_id AS owner_user_id, p.name AS project_name
            FROM artifacts AS a
            JOIN projects AS p ON p.id = a.project_id
            WHERE {' AND '.join(where)}
            ORDER BY a.created_at DESC
            LIMIT :limit
            """,
            params,
        ).fetchall()
        totals = conn.execute(
            """
            SELECT COUNT(*) AS artifact_count, COALESCE(SUM(size_bytes), 0) AS total_bytes
            FROM artifacts
            """
        ).fetchone()
    payload = []
    for row in rows:
        item = _artifact_payload(row)
        item["owner_user_id"] = row["owner_user_id"]
        item["project_name"] = row["project_name"]
        payload.append(item)
    return {
        "items": payload,
        "total_artifact_count": int(totals["artifact_count"] or 0),
        "total_artifact_bytes": int(totals["total_bytes"] or 0),
        "storage": get_artifact_store().disk_status(),
    }


def list_admin_runs(
    *,
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    usage_context: Optional[str] = None,
    analysis_status: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    where = ["1 = 1"]
    params: Dict[str, Any] = {"limit": min(500, max(1, int(limit)))}
    for column, key, value in (
        ("gr.project_id", "project_id", project_id),
        ("gr.user_id", "user_id", user_id),
        ("gr.experiment_id", "experiment_id", experiment_id),
        ("gr.usage_context", "usage_context", usage_context),
        ("gr.analysis_status", "analysis_status", analysis_status),
        ("gr.status", "status", status),
    ):
        if value:
            where.append(f"{column} = :{key}")
            params[key] = value
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT gr.*, p.name AS project_name
            FROM generation_runs AS gr
            LEFT JOIN projects AS p ON p.id = gr.project_id
            WHERE {' AND '.join(where)}
            ORDER BY gr.created_at DESC
            LIMIT :limit
            """,
            params,
        ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "project_name": row["project_name"],
                "user_id": row["user_id"],
                "experiment_id": row["experiment_id"],
                "mode": row["mode"],
                "status": row["status"],
                "usage_context": row["usage_context"],
                "analysis_status": row["analysis_status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    }


def update_run_analysis_status(run_id: str, analysis_status: str) -> Dict[str, Any]:
    if analysis_status not in VALID_ANALYSIS_STATUSES:
        raise ApiError(400, "INVALID_ANALYSIS_STATUS", "分析対象の状態が不正です。")
    with db_conn() as conn:
        run = conn.execute(
            "SELECT usage_context FROM generation_runs WHERE id = :run_id",
            {"run_id": run_id},
        ).fetchone()
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "生成runが見つかりません。")
        if run["usage_context"] != "research" and analysis_status != "excluded":
            raise ApiError(409, "GENERAL_RUN_NOT_RESEARCH_DATA", "通常利用のrunは実験データに採用できません。")
        updated = conn.execute(
            """
            UPDATE generation_runs
            SET analysis_status = :analysis_status, updated_at = :updated_at
            WHERE id = :run_id
            """,
            {"analysis_status": analysis_status, "updated_at": _now_iso(), "run_id": run_id},
        )
    return get_generation_run_v2(run_id, admin=True)


def archive_project_v2(project_id: str, user_id: str) -> None:
    now = _now_iso()
    with db_conn() as conn:
        _project_owner(conn, project_id, user_id)
        conn.execute(
            "UPDATE projects SET archived_at = :archived_at, updated_at = :updated_at WHERE id = :project_id",
            {"archived_at": now, "updated_at": now, "project_id": project_id},
        )
