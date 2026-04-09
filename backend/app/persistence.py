from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .db import db_conn, json_text
from .service import ApiError


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _loads(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _project_summary_from_row(row: Any) -> Dict[str, Any]:
    data = _loads(row["latest_state_json"], {})
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "mode": data.get("mode"),
        "slide_count": len(data.get("slides") or []),
        "sentence_count": len(data.get("sentences") or []),
        "highlight_count": len(data.get("highlights") or []),
        "experiment_id": row["experiment_id"],
    }


def _project_payload_from_row(row: Any) -> Dict[str, Any]:
    data = _loads(row["latest_state_json"], {})
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "experiment_id": row["experiment_id"],
        "data": data,
    }


def create_guest_session() -> Dict[str, Any]:
    now = _now_iso()
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session_token = secrets.token_urlsafe(32)
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (id, user_kind, email, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, "guest", None, now, now),
        )
        conn.execute(
            """
            INSERT INTO user_sessions (
                id, user_id, session_token, experiment_id, participant_label,
                created_at, updated_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, user_id, session_token, None, None, now, now, now),
        )
    return {
        "session_token": session_token,
        "session_id": session_id,
        "user": {"id": user_id, "kind": "guest"},
    }


def get_session_context(session_token: str) -> Dict[str, Any]:
    token = str(session_token or "").strip()
    if not token:
        raise ApiError(401, "AUTH_REQUIRED", "ゲストセッションが見つかりません。/api/auth/guest を先に実行してください。")
    now = _now_iso()
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.session_token,
                s.experiment_id,
                s.participant_label,
                u.id AS user_id,
                u.user_kind,
                u.email
            FROM user_sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.session_token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            raise ApiError(401, "INVALID_SESSION", "セッションが無効です。再読み込みしてやり直してください。")
        conn.execute(
            "UPDATE user_sessions SET updated_at = ?, last_seen_at = ? WHERE id = ?",
            (now, now, row["session_id"]),
        )
    return {
        "session_id": row["session_id"],
        "session_token": row["session_token"],
        "experiment_id": row["experiment_id"],
        "participant_label": row["participant_label"],
        "user": {
            "id": row["user_id"],
            "kind": row["user_kind"],
            "email": row["email"],
        },
    }


def list_projects_for_user(user_id: str) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, created_at, updated_at, experiment_id, latest_state_json
            FROM projects
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
    return [_project_summary_from_row(row) for row in rows]


def get_project_for_user(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at, experiment_id, latest_state_json
            FROM projects
            WHERE id = ? AND user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()
    if row is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
    return _project_payload_from_row(row)


def _next_project_version(conn: Any, project_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS max_version FROM project_versions WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    return int((row["max_version"] if row else 0) or 0) + 1


def save_project_for_user(
    *,
    user_id: str,
    experiment_id: Optional[str],
    project_id: str,
    name: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    now = _now_iso()
    clean_name = str(name or "").strip() or "新しいプロジェクト"
    review_states = data.get("review_states") if isinstance(data, dict) else {}
    generation_ref = data.get("generation_ref") if isinstance(data, dict) else {}
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        payload_json = json_text(data)
        review_states_json = json_text(review_states if isinstance(review_states, dict) else {})
        generation_refs_json = json_text(generation_ref if isinstance(generation_ref, dict) else {})
        if existing is None:
            created_at = now
            conn.execute(
                """
                INSERT INTO projects (
                    id, user_id, experiment_id, name, latest_state_json,
                    generation_refs_json, review_states_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    user_id,
                    experiment_id,
                    clean_name,
                    payload_json,
                    generation_refs_json,
                    review_states_json,
                    created_at,
                    now,
                ),
            )
        else:
            created_at = existing["created_at"]
            conn.execute(
                """
                UPDATE projects
                SET
                    experiment_id = ?,
                    name = ?,
                    latest_state_json = ?,
                    generation_refs_json = ?,
                    review_states_json = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (
                    experiment_id,
                    clean_name,
                    payload_json,
                    generation_refs_json,
                    review_states_json,
                    now,
                    project_id,
                    user_id,
                ),
            )
        version_number = _next_project_version(conn, project_id)
        conn.execute(
            """
            INSERT INTO project_versions (
                id, project_id, version_number, saved_by_user_id, snapshot_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"ver_{uuid.uuid4().hex[:12]}",
                project_id,
                version_number,
                user_id,
                payload_json,
                now,
            ),
        )
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at, experiment_id, latest_state_json
            FROM projects
            WHERE id = ? AND user_id = ?
            """,
            (project_id, user_id),
        ).fetchone()
    return {
        **_project_payload_from_row(row),
        "version_number": version_number,
        "project_meta": {
            "id": project_id,
            "name": clean_name,
            "created_at": created_at,
            "updated_at": now,
        },
    }


def delete_project_for_user(project_id: str, user_id: str) -> None:
    with db_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        )
    if deleted.rowcount == 0:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")


def save_project_events(
    *,
    project_id: str,
    user_id: str,
    events: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    saved = 0
    skipped = 0
    with db_conn() as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if project is None:
            raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
        for event in events:
            external_event_id = str(event.get("external_event_id") or event.get("id") or "").strip()
            if not external_event_id:
                skipped += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO edit_events (
                        id, project_id, user_id, external_event_id, action_type, slide_idx,
                        entity_type, entity_id, source, before_json, after_json, payload_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"evt_{uuid.uuid4().hex[:12]}",
                        project_id,
                        user_id,
                        external_event_id,
                        str(event.get("action_type") or "unknown"),
                        event.get("slide_idx"),
                        event.get("entity_type"),
                        event.get("entity_id"),
                        event.get("source"),
                        json_text(event.get("before")) if event.get("before") is not None else None,
                        json_text(event.get("after")) if event.get("after") is not None else None,
                        json_text(event.get("payload") or {}),
                        str(event.get("created_at") or _now_iso()),
                    ),
                )
                saved += 1
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    skipped += 1
                    continue
                raise
    return {"saved": saved, "skipped": skipped}


def get_review_settings() -> Dict[str, Any]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, scope_type, scope_key, layout_review_mode, script_review_mode, created_at, updated_at
            FROM review_settings
            ORDER BY scope_type ASC, COALESCE(scope_key, '') ASC
            """
        ).fetchall()
    global_row = next((row for row in rows if row["scope_type"] == "global" and row["scope_key"] is None), None)
    experiment_rows = [row for row in rows if row["scope_type"] == "experiment"]
    return {
        "global": {
            "layout_review_mode": global_row["layout_review_mode"] if global_row else "off",
            "script_review_mode": global_row["script_review_mode"] if global_row else "off",
            "updated_at": global_row["updated_at"] if global_row else None,
        },
        "experiments": [
            {
                "experiment_id": row["scope_key"],
                "layout_review_mode": row["layout_review_mode"],
                "script_review_mode": row["script_review_mode"],
                "updated_at": row["updated_at"],
            }
            for row in experiment_rows
        ],
    }


def upsert_review_settings(
    *,
    scope_type: str,
    scope_key: Optional[str],
    layout_review_mode: str,
    script_review_mode: str,
) -> Dict[str, Any]:
    now = _now_iso()
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM review_settings WHERE scope_type = ? AND scope_key IS ?",
            (scope_type, scope_key),
        ).fetchone()
        row_id = existing["id"] if existing else f"review_{uuid.uuid4().hex[:12]}"
        if existing is None:
            conn.execute(
                """
                INSERT INTO review_settings (
                    id, scope_type, scope_key, layout_review_mode, script_review_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, scope_type, scope_key, layout_review_mode, script_review_mode, now, now),
            )
        else:
            conn.execute(
                """
                UPDATE review_settings
                SET layout_review_mode = ?, script_review_mode = ?, updated_at = ?
                WHERE id = ?
                """,
                (layout_review_mode, script_review_mode, now, row_id),
            )
    return {
        "scope_type": scope_type,
        "scope_key": scope_key,
        "layout_review_mode": layout_review_mode,
        "script_review_mode": script_review_mode,
        "updated_at": now,
    }


def join_experiment(*, session_token: str, invite_code: str) -> Dict[str, Any]:
    context = get_session_context(session_token)
    code = str(invite_code or "").strip()
    if not code:
        raise ApiError(400, "INVALID_INVITE_CODE", "実験コードを入力してください。")
    now = _now_iso()
    with db_conn() as conn:
        experiment = conn.execute(
            "SELECT id, name, invite_code FROM experiments WHERE invite_code = ?",
            (code,),
        ).fetchone()
        if experiment is None:
            raise ApiError(404, "EXPERIMENT_NOT_FOUND", "実験コードが見つかりません。")
        conn.execute(
            "UPDATE users SET user_kind = ?, updated_at = ? WHERE id = ?",
            ("experiment_participant", now, context["user"]["id"]),
        )
        conn.execute(
            """
            UPDATE user_sessions
            SET experiment_id = ?, updated_at = ?, last_seen_at = ?
            WHERE id = ?
            """,
            (experiment["id"], now, now, context["session_id"]),
        )
        existing = conn.execute(
            """
            SELECT id FROM experiment_participants
            WHERE experiment_id = ? AND user_id = ?
            """,
            (experiment["id"], context["user"]["id"]),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO experiment_participants (id, experiment_id, user_id, joined_at)
                VALUES (?, ?, ?, ?)
                """,
                (f"participant_{uuid.uuid4().hex[:12]}", experiment["id"], context["user"]["id"], now),
            )
    return {
        "experiment": {
            "id": experiment["id"],
            "name": experiment["name"],
            "invite_code": experiment["invite_code"],
        },
        "user": {
            **context["user"],
            "kind": "experiment_participant",
        },
    }


def save_layout_review_records(
    *,
    project_id: str,
    user_id: str,
    records: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    saved = 0
    with db_conn() as conn:
        for record in records:
            conn.execute(
                """
                INSERT INTO layout_review_records (
                    id, project_id, user_id, slide_idx, highlight_id, review_source, decision,
                    before_json, after_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"lrev_{uuid.uuid4().hex[:12]}",
                    project_id,
                    user_id,
                    record.get("slide_idx"),
                    record.get("highlight_id"),
                    str(record.get("review_source") or "human"),
                    str(record.get("decision") or "accepted"),
                    json_text(record.get("before")) if record.get("before") is not None else None,
                    json_text(record.get("after")) if record.get("after") is not None else None,
                    str(record.get("created_at") or _now_iso()),
                ),
            )
            saved += 1
    return {"saved": saved}


def save_script_review_records(
    *,
    project_id: str,
    user_id: str,
    records: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    saved = 0
    with db_conn() as conn:
        for record in records:
            conn.execute(
                """
                INSERT INTO script_review_records (
                    id, project_id, user_id, slide_idx, sentence_id, review_step,
                    before_text, after_text, changed_fields_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"srev_{uuid.uuid4().hex[:12]}",
                    project_id,
                    user_id,
                    record.get("slide_idx"),
                    record.get("sentence_id"),
                    str(record.get("review_step") or "script_review"),
                    record.get("before_text"),
                    record.get("after_text"),
                    json_text(record.get("changed_fields") or []),
                    str(record.get("created_at") or _now_iso()),
                ),
            )
            saved += 1
    return {"saved": saved}


def get_project_review_state(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        project = conn.execute(
            "SELECT review_states_json FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        if project is None:
            raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
    return _loads(project["review_states_json"], {})
