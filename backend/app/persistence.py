from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .db import db_conn, json_text
from .service import ApiError


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
PASSWORD_MIN_LENGTH = 8
PBKDF2_ITERATIONS = 390_000


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _loads(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _normalize_username(username: str) -> str:
    cleaned = str(username or "").strip().lower()
    if not USERNAME_PATTERN.fullmatch(cleaned):
        raise ApiError(
            400,
            "INVALID_USERNAME",
            "ユーザ名は 3〜40 文字の英数字・._- を使ってください。",
        )
    return cleaned


def _validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < PASSWORD_MIN_LENGTH:
        raise ApiError(400, "INVALID_PASSWORD", "パスワードは 8 文字以上にしてください。")
    return value


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${digest_b64}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _is_unique_error(exc: Exception) -> bool:
    message = str(exc)
    return "UNIQUE constraint failed" in message or "duplicate key value violates unique constraint" in message


def _create_session_record(
    *,
    conn: Any,
    user_id: str,
    experiment_id: Optional[str] = None,
    participant_label: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now_iso()
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session_token = secrets.token_urlsafe(32)
    conn.execute(
        """
        INSERT INTO user_sessions (
            id, user_id, session_token, experiment_id, participant_label,
            created_at, updated_at, last_seen_at
        )
        VALUES (:id, :user_id, :session_token, :experiment_id, :participant_label, :created_at, :updated_at, :last_seen_at)
        """,
        {
            "id": session_id,
            "user_id": user_id,
            "session_token": session_token,
            "experiment_id": experiment_id,
            "participant_label": participant_label,
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        },
    )
    return {
        "session_id": session_id,
        "session_token": session_token,
    }


def _build_auth_payload(user_row: Any, session_row: Dict[str, Any], experiment_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        **session_row,
        "experiment_id": experiment_id,
        "user": {
            "id": user_row["id"],
            "username": user_row.get("username") if isinstance(user_row, dict) else user_row["username"],
            "kind": user_row.get("user_kind") if isinstance(user_row, dict) else user_row["user_kind"],
            "role": user_row.get("role") if isinstance(user_row, dict) else user_row["role"],
            "email": user_row.get("email") if isinstance(user_row, dict) else user_row["email"],
        },
    }


def _count_admins(conn: Any) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS total FROM users WHERE role = :role",
        {"role": "admin"},
    ).fetchone()
    return int((row["total"] if row else 0) or 0)


def register_user(username: str, password: str) -> Dict[str, Any]:
    now = _now_iso()
    clean_username = _normalize_username(username)
    password_value = _validate_password(password)
    password_hash = _hash_password(password_value)
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    role = "user"
    with db_conn() as conn:
        if _count_admins(conn) == 0:
            role = "admin"
        try:
            conn.execute(
                """
                INSERT INTO users (
                    id, user_kind, username, password_hash, role, email, is_active, created_at, updated_at
                )
                VALUES (:id, :user_kind, :username, :password_hash, :role, :email, :is_active, :created_at, :updated_at)
                """,
                {
                    "id": user_id,
                    "user_kind": "registered",
                    "username": clean_username,
                    "password_hash": password_hash,
                    "role": role,
                    "email": None,
                    "is_active": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        except Exception as exc:
            if _is_unique_error(exc):
                raise ApiError(409, "USERNAME_EXISTS", "そのユーザ名はすでに使われています。") from exc
            raise
        session_row = _create_session_record(conn=conn, user_id=user_id)
        user_row = conn.execute(
            """
            SELECT id, user_kind, username, role, email
            FROM users
            WHERE id = :user_id
            """,
            {"user_id": user_id},
        ).fetchone()
    return _build_auth_payload(user_row, session_row)


def login_user(username: str, password: str) -> Dict[str, Any]:
    clean_username = _normalize_username(username)
    password_value = _validate_password(password)
    with db_conn() as conn:
        user_row = conn.execute(
            """
            SELECT id, user_kind, username, role, email, password_hash, is_active
            FROM users
            WHERE username = :username
            """,
            {"username": clean_username},
        ).fetchone()
        if user_row is None or not user_row["password_hash"]:
            raise ApiError(401, "INVALID_LOGIN", "ユーザ名またはパスワードが違います。")
        if int(user_row["is_active"] or 0) != 1:
            raise ApiError(403, "USER_DISABLED", "このアカウントは現在利用できません。")
        if not _verify_password(password_value, user_row["password_hash"]):
            raise ApiError(401, "INVALID_LOGIN", "ユーザ名またはパスワードが違います。")
        session_row = _create_session_record(conn=conn, user_id=user_row["id"])
    return _build_auth_payload(user_row, session_row)


def logout_session(session_token: str) -> Dict[str, Any]:
    token = str(session_token or "").strip()
    if not token:
        return {"ok": True}
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM user_sessions WHERE session_token = :session_token",
            {"session_token": token},
        )
    return {"ok": True}


def create_guest_session() -> Dict[str, Any]:
    now = _now_iso()
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (id, user_kind, role, email, is_active, created_at, updated_at)
            VALUES (:id, :user_kind, :role, :email, :is_active, :created_at, :updated_at)
            """,
            {
                "id": user_id,
                "user_kind": "guest",
                "role": "user",
                "email": None,
                "is_active": 1,
                "created_at": now,
                "updated_at": now,
            },
        )
        session_row = _create_session_record(conn=conn, user_id=user_id)
        user_row = conn.execute(
            "SELECT id, user_kind, username, role, email FROM users WHERE id = :user_id",
            {"user_id": user_id},
        ).fetchone()
    return _build_auth_payload(user_row, session_row)


def get_session_context(session_token: str) -> Dict[str, Any]:
    token = str(session_token or "").strip()
    if not token:
        raise ApiError(401, "AUTH_REQUIRED", "ログインが必要です。")
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
                u.username,
                u.role,
                u.email,
                u.is_active
            FROM user_sessions AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.session_token = :session_token
            """,
            {"session_token": token},
        ).fetchone()
        if row is None:
            raise ApiError(401, "INVALID_SESSION", "セッションが無効です。再ログインしてください。")
        if int(row["is_active"] or 0) != 1:
            raise ApiError(403, "USER_DISABLED", "このアカウントは現在利用できません。")
        conn.execute(
            """
            UPDATE user_sessions
            SET updated_at = :updated_at, last_seen_at = :last_seen_at
            WHERE id = :session_id
            """,
            {"updated_at": now, "last_seen_at": now, "session_id": row["session_id"]},
        )
    return {
        "session_id": row["session_id"],
        "session_token": row["session_token"],
        "experiment_id": row["experiment_id"],
        "participant_label": row["participant_label"],
        "user": {
            "id": row["user_id"],
            "username": row["username"],
            "kind": row["user_kind"],
            "role": row["role"],
            "email": row["email"],
        },
    }


def list_projects_for_user(user_id: str) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, created_at, updated_at, experiment_id, latest_state_json
            FROM projects
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            """,
            {"user_id": user_id},
        ).fetchall()
    return [_project_summary_from_row(row) for row in rows]


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


def get_project_for_user(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at, experiment_id, latest_state_json
            FROM projects
            WHERE id = :project_id AND user_id = :user_id
            """,
            {"project_id": project_id, "user_id": user_id},
        ).fetchone()
    if row is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
    return _project_payload_from_row(row)


def _next_project_version(conn: Any, project_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS max_version FROM project_versions WHERE project_id = :project_id",
        {"project_id": project_id},
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
            "SELECT id, created_at FROM projects WHERE id = :project_id AND user_id = :user_id",
            {"project_id": project_id, "user_id": user_id},
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
                VALUES (
                    :id, :user_id, :experiment_id, :name, :latest_state_json,
                    :generation_refs_json, :review_states_json, :created_at, :updated_at
                )
                """,
                {
                    "id": project_id,
                    "user_id": user_id,
                    "experiment_id": experiment_id,
                    "name": clean_name,
                    "latest_state_json": payload_json,
                    "generation_refs_json": generation_refs_json,
                    "review_states_json": review_states_json,
                    "created_at": created_at,
                    "updated_at": now,
                },
            )
        else:
            created_at = existing["created_at"]
            conn.execute(
                """
                UPDATE projects
                SET
                    experiment_id = :experiment_id,
                    name = :name,
                    latest_state_json = :latest_state_json,
                    generation_refs_json = :generation_refs_json,
                    review_states_json = :review_states_json,
                    updated_at = :updated_at
                WHERE id = :project_id AND user_id = :user_id
                """,
                {
                    "experiment_id": experiment_id,
                    "name": clean_name,
                    "latest_state_json": payload_json,
                    "generation_refs_json": generation_refs_json,
                    "review_states_json": review_states_json,
                    "updated_at": now,
                    "project_id": project_id,
                    "user_id": user_id,
                },
            )
        version_number = _next_project_version(conn, project_id)
        conn.execute(
            """
            INSERT INTO project_versions (
                id, project_id, version_number, saved_by_user_id, snapshot_json, created_at
            )
            VALUES (:id, :project_id, :version_number, :saved_by_user_id, :snapshot_json, :created_at)
            """,
            {
                "id": f"ver_{uuid.uuid4().hex[:12]}",
                "project_id": project_id,
                "version_number": version_number,
                "saved_by_user_id": user_id,
                "snapshot_json": payload_json,
                "created_at": now,
            },
        )
        row = conn.execute(
            """
            SELECT id, name, created_at, updated_at, experiment_id, latest_state_json
            FROM projects
            WHERE id = :project_id AND user_id = :user_id
            """,
            {"project_id": project_id, "user_id": user_id},
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
            "DELETE FROM projects WHERE id = :project_id AND user_id = :user_id",
            {"project_id": project_id, "user_id": user_id},
        )
    if int(getattr(deleted, "rowcount", 0) or 0) == 0:
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
            "SELECT id FROM projects WHERE id = :project_id AND user_id = :user_id",
            {"project_id": project_id, "user_id": user_id},
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
                    VALUES (
                        :id, :project_id, :user_id, :external_event_id, :action_type, :slide_idx,
                        :entity_type, :entity_id, :source, :before_json, :after_json, :payload_json, :created_at
                    )
                    """,
                    {
                        "id": f"evt_{uuid.uuid4().hex[:12]}",
                        "project_id": project_id,
                        "user_id": user_id,
                        "external_event_id": external_event_id,
                        "action_type": str(event.get("action_type") or "unknown"),
                        "slide_idx": event.get("slide_idx"),
                        "entity_type": event.get("entity_type"),
                        "entity_id": event.get("entity_id"),
                        "source": event.get("source"),
                        "before_json": json_text(event.get("before")) if event.get("before") is not None else None,
                        "after_json": json_text(event.get("after")) if event.get("after") is not None else None,
                        "payload_json": json_text(event.get("payload") or {}),
                        "created_at": str(event.get("created_at") or _now_iso()),
                    },
                )
                saved += 1
            except Exception as exc:
                if _is_unique_error(exc):
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
        if scope_key is None:
            existing = conn.execute(
                "SELECT id FROM review_settings WHERE scope_type = :scope_type AND scope_key IS NULL",
                {"scope_type": scope_type},
            ).fetchone()
        else:
            existing = conn.execute(
                "SELECT id FROM review_settings WHERE scope_type = :scope_type AND scope_key = :scope_key",
                {"scope_type": scope_type, "scope_key": scope_key},
            ).fetchone()
        row_id = existing["id"] if existing else f"review_{uuid.uuid4().hex[:12]}"
        if existing is None:
            conn.execute(
                """
                INSERT INTO review_settings (
                    id, scope_type, scope_key, layout_review_mode, script_review_mode, created_at, updated_at
                ) VALUES (:id, :scope_type, :scope_key, :layout_review_mode, :script_review_mode, :created_at, :updated_at)
                """,
                {
                    "id": row_id,
                    "scope_type": scope_type,
                    "scope_key": scope_key,
                    "layout_review_mode": layout_review_mode,
                    "script_review_mode": script_review_mode,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        else:
            conn.execute(
                """
                UPDATE review_settings
                SET layout_review_mode = :layout_review_mode, script_review_mode = :script_review_mode, updated_at = :updated_at
                WHERE id = :id
                """,
                {
                    "layout_review_mode": layout_review_mode,
                    "script_review_mode": script_review_mode,
                    "updated_at": now,
                    "id": row_id,
                },
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
            "SELECT id, name, invite_code FROM experiments WHERE invite_code = :invite_code",
            {"invite_code": code},
        ).fetchone()
        if experiment is None:
            raise ApiError(404, "EXPERIMENT_NOT_FOUND", "実験コードが見つかりません。")
        conn.execute(
            "UPDATE users SET user_kind = :user_kind, updated_at = :updated_at WHERE id = :user_id",
            {"user_kind": "experiment_participant", "updated_at": now, "user_id": context["user"]["id"]},
        )
        conn.execute(
            """
            UPDATE user_sessions
            SET experiment_id = :experiment_id, updated_at = :updated_at, last_seen_at = :last_seen_at
            WHERE id = :session_id
            """,
            {
                "experiment_id": experiment["id"],
                "updated_at": now,
                "last_seen_at": now,
                "session_id": context["session_id"],
            },
        )
        existing = conn.execute(
            """
            SELECT id FROM experiment_participants
            WHERE experiment_id = :experiment_id AND user_id = :user_id
            """,
            {"experiment_id": experiment["id"], "user_id": context["user"]["id"]},
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO experiment_participants (id, experiment_id, user_id, joined_at)
                VALUES (:id, :experiment_id, :user_id, :joined_at)
                """,
                {
                    "id": f"participant_{uuid.uuid4().hex[:12]}",
                    "experiment_id": experiment["id"],
                    "user_id": context["user"]["id"],
                    "joined_at": now,
                },
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
                ) VALUES (
                    :id, :project_id, :user_id, :slide_idx, :highlight_id, :review_source, :decision,
                    :before_json, :after_json, :created_at
                )
                """,
                {
                    "id": f"lrev_{uuid.uuid4().hex[:12]}",
                    "project_id": project_id,
                    "user_id": user_id,
                    "slide_idx": record.get("slide_idx"),
                    "highlight_id": record.get("highlight_id"),
                    "review_source": str(record.get("review_source") or "human"),
                    "decision": str(record.get("decision") or "accepted"),
                    "before_json": json_text(record.get("before")) if record.get("before") is not None else None,
                    "after_json": json_text(record.get("after")) if record.get("after") is not None else None,
                    "created_at": str(record.get("created_at") or _now_iso()),
                },
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
                ) VALUES (
                    :id, :project_id, :user_id, :slide_idx, :sentence_id, :review_step,
                    :before_text, :after_text, :changed_fields_json, :created_at
                )
                """,
                {
                    "id": f"srev_{uuid.uuid4().hex[:12]}",
                    "project_id": project_id,
                    "user_id": user_id,
                    "slide_idx": record.get("slide_idx"),
                    "sentence_id": record.get("sentence_id"),
                    "review_step": str(record.get("review_step") or "script_review"),
                    "before_text": record.get("before_text"),
                    "after_text": record.get("after_text"),
                    "changed_fields_json": json_text(record.get("changed_fields") or []),
                    "created_at": str(record.get("created_at") or _now_iso()),
                },
            )
            saved += 1
    return {"saved": saved}


def get_project_review_state(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        project = conn.execute(
            "SELECT review_states_json FROM projects WHERE id = :project_id AND user_id = :user_id",
            {"project_id": project_id, "user_id": user_id},
        ).fetchone()
        if project is None:
            raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
    return _loads(project["review_states_json"], {})
