from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .db import db_conn, json_text
from .service import ApiError
from .storage import get_artifact_store


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
PASSWORD_MIN_LENGTH = 8
PBKDF2_ITERATIONS = 390_000
GLOBAL_GENERATION_CONDITION_KEY = "generation_conditions_global"
DEFAULT_GENERATION_CONDITIONS: Dict[str, Any] = {
    "kg_mode": "off",
    "log_reuse_enabled": False,
    "review_flow_enabled": True,
    "prompt_strategy_version": "baseline_v1",
}
VALID_KG_MODES = {"off", "slide", "global", "global_slide"}
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MATERIAL_ROOT = BACKEND_ROOT / "teachingmaterial"
MATERIAL_PDF_ROOT = MATERIAL_ROOT / "pdf"
MATERIAL_IMG_ROOT = MATERIAL_ROOT / "img"
OUTPUT_ROOT = BACKEND_ROOT / "outputs"
PROJECT_ARTIFACT_ROOT = OUTPUT_ROOT / "project_artifacts"
MAX_PROJECT_PDF_BYTES = 60 * 1024 * 1024


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_artifact_part(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return safe[:120] or "item"


def _project_artifact_dir(user_id: str, project_id: str) -> Path:
    return PROJECT_ARTIFACT_ROOT / _safe_artifact_part(user_id) / _safe_artifact_part(project_id)


def _project_pdf_path(user_id: str, project_id: str, sha256: str) -> Path:
    return _project_artifact_dir(user_id, project_id) / f"input_pdf_{_safe_artifact_part(sha256)[:64]}.pdf"


def _project_slide_dir(user_id: str, project_id: str) -> Path:
    return _project_artifact_dir(user_id, project_id) / "slides"


def _project_slide_image_path(user_id: str, project_id: str, slide_idx: int) -> Path:
    return _project_slide_dir(user_id, project_id) / f"{slide_idx + 1:03d}.png"


def _copy_artifact_file(src: Path, dst: Path) -> bool:
    if not src.exists() or not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        return True
    tmp_path = dst.with_suffix(f"{dst.suffix}.tmp")
    shutil.copy2(src, tmp_path)
    tmp_path.replace(dst)
    return True


def _generation_ref_from_data(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    generation_ref = data.get("generation_ref")
    return generation_ref if isinstance(generation_ref, dict) else {}


def _generation_material_name(data: Any) -> Optional[str]:
    material_name = str(_generation_ref_from_data(data).get("material_name") or "").strip()
    if not material_name:
        return None
    return Path(material_name.replace("\\", "/")).name


def _resolve_output_child(relative_path: Any) -> Optional[Path]:
    raw = str(relative_path or "").strip()
    if not raw:
        return None
    raw_path = Path(raw)
    if raw_path.is_absolute() or ".." in raw_path.parts:
        return None
    root = OUTPUT_ROOT.resolve()
    candidate = (root / raw_path).resolve()
    try:
        if not candidate.is_relative_to(root):
            return None
    except AttributeError:
        if os.path.commonpath([str(root), str(candidate)]) != str(root):
            return None
    return candidate


def _project_pdf_meta_from_generation(
    *,
    user_id: str,
    project_id: str,
    data: Dict[str, Any],
    existing_pdf: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    generation_ref = _generation_ref_from_data(data)
    material_name = _generation_material_name(data)
    if not material_name:
        return existing_pdf

    source_path = MATERIAL_PDF_ROOT / material_name
    if not source_path.exists():
        return existing_pdf

    sha256 = str(generation_ref.get("pdf_hash") or "").strip()
    if not sha256:
        sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()

    out_path = _project_pdf_path(user_id, project_id, sha256)
    if not _copy_artifact_file(source_path, out_path):
        return existing_pdf

    input_pdf = data.get("input_pdf") if isinstance(data.get("input_pdf"), dict) else {}
    return {
        "name": str(input_pdf.get("name") or material_name),
        "type": "application/pdf",
        "size": int(source_path.stat().st_size),
        "last_modified": input_pdf.get("last_modified"),
        "sha256": sha256,
        "storage_key": sha256,
        "available": True,
        "artifact_kind": "input_pdf",
        "download_url": f"/api/projects/{project_id}/pdf",
    }


def _generation_slide_source_paths(data: Dict[str, Any]) -> List[Path]:
    material_name = _generation_material_name(data)
    if material_name:
        material_img_dir = MATERIAL_IMG_ROOT / material_name
        paths = sorted(path for path in material_img_dir.glob("*.png") if path.is_file())
        if paths:
            return paths

    output_root = _resolve_output_child(_generation_ref_from_data(data).get("output_root_name"))
    if output_root:
        lp_dir = output_root / "LP_output"
        paths = sorted(path for path in lp_dir.glob("result_*.png") if path.is_file())
        if paths:
            return paths
    return []


def _prepare_project_slide_artifacts(
    *,
    user_id: str,
    project_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    slides = data.get("slides")
    if not isinstance(slides, list) or not slides:
        return data

    source_paths = _generation_slide_source_paths(data)
    if not source_paths:
        return data

    next_slides: List[Any] = []
    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict):
            next_slides.append(slide)
            continue
        source_path = source_paths[idx] if idx < len(source_paths) else None
        copied = False
        if source_path is not None:
            copied = _copy_artifact_file(source_path, _project_slide_image_path(user_id, project_id, idx))
        next_slides.append(
            {
                **slide,
                "image_available": bool(slide.get("image_available") or copied),
                "image_url": f"/api/projects/{project_id}/slides/{idx}/image" if copied else slide.get("image_url"),
            }
        )
    return {**data, "slides": next_slides}


def _prepare_project_generated_artifacts(
    *,
    user_id: str,
    project_id: str,
    data: Dict[str, Any],
    existing_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data

    existing_pdf = _sanitize_input_pdf_meta((existing_data or {}).get("input_pdf"))
    current_pdf = _sanitize_input_pdf_meta(data.get("input_pdf"))
    if not current_pdf or not current_pdf.get("available"):
        generated_pdf = _project_pdf_meta_from_generation(
            user_id=user_id,
            project_id=project_id,
            data=data,
            existing_pdf=existing_pdf,
        )
        if generated_pdf:
            data = {**data, "input_pdf": generated_pdf}

    return _prepare_project_slide_artifacts(user_id=user_id, project_id=project_id, data=data)


def _sanitize_input_pdf_meta(input_pdf: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(input_pdf, dict):
        return None
    meta = {key: value for key, value in input_pdf.items() if key not in {"upload_base64", "base64", "data_url"}}
    if not meta.get("sha256") and not meta.get("storage_key"):
        return None
    sha256 = str(meta.get("sha256") or meta.get("storage_key") or "").strip()
    if not sha256:
        return None
    try:
        size = int(meta.get("size") or 0)
    except Exception:
        size = 0
    return {
        "name": str(meta.get("name") or "slides.pdf"),
        "type": str(meta.get("type") or "application/pdf"),
        "size": size,
        "last_modified": meta.get("last_modified"),
        "sha256": sha256,
        "storage_key": sha256,
        "available": bool(meta.get("available", True)),
        "artifact_kind": "input_pdf",
        "download_url": meta.get("download_url"),
    }


def _project_input_pdf_meta_with_url(input_pdf: Any, project_id: str) -> Optional[Dict[str, Any]]:
    meta = _sanitize_input_pdf_meta(input_pdf)
    if not meta:
        return None
    return {
        **meta,
        "download_url": f"/api/projects/{project_id}/pdf" if meta.get("available") else None,
    }


def _prepare_project_input_pdf(
    *,
    user_id: str,
    project_id: str,
    data: Dict[str, Any],
    existing_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data

    existing_pdf = _sanitize_input_pdf_meta((existing_data or {}).get("input_pdf"))
    if "input_pdf" not in data:
        if existing_pdf:
            return {**data, "input_pdf": existing_pdf}
        return data

    input_pdf = data.get("input_pdf")
    if input_pdf is None:
        return {**data, "input_pdf": None}
    if not isinstance(input_pdf, dict):
        return {**data, "input_pdf": existing_pdf}

    upload_b64 = str(input_pdf.get("upload_base64") or "").strip()
    if not upload_b64:
        meta = _sanitize_input_pdf_meta(input_pdf) or existing_pdf
        return {**data, "input_pdf": meta}

    if upload_b64.startswith("data:"):
        upload_b64 = upload_b64.split(",", 1)[-1]
    try:
        pdf_bytes = base64.b64decode(upload_b64)
    except Exception as exc:
        raise ApiError(400, "INVALID_PROJECT_PDF", "PDF の保存データを読み取れません。") from exc
    if not pdf_bytes:
        raise ApiError(400, "INVALID_PROJECT_PDF", "PDF が空です。")
    if len(pdf_bytes) > MAX_PROJECT_PDF_BYTES:
        raise ApiError(413, "PROJECT_PDF_TOO_LARGE", "PDF が大きすぎます。60MB 以下にしてください。")
    if not pdf_bytes.startswith(b"%PDF"):
        raise ApiError(400, "INVALID_PROJECT_PDF", "PDF ファイルではない可能性があります。")

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    out_path = _project_pdf_path(user_id, project_id, sha256)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not out_path.exists():
        tmp_path = out_path.with_suffix(".tmp")
        tmp_path.write_bytes(pdf_bytes)
        tmp_path.replace(out_path)

    meta = {
        "name": str(input_pdf.get("name") or "slides.pdf"),
        "type": "application/pdf",
        "size": len(pdf_bytes),
        "last_modified": input_pdf.get("last_modified"),
        "sha256": sha256,
        "storage_key": sha256,
        "available": True,
        "artifact_kind": "input_pdf",
        "download_url": f"/api/projects/{project_id}/pdf",
    }
    return {**data, "input_pdf": meta}


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _session_ttl_hours() -> int:
    raw = os.getenv("LECTURE_CRAFT_SESSION_TTL_HOURS", "24")
    try:
        return max(1, int(raw))
    except Exception:
        return 24


def _session_expires_at(now: Optional[datetime] = None) -> str:
    current = now or datetime.now()
    return (current + timedelta(hours=_session_ttl_hours())).isoformat(timespec="seconds")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _loads(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str) or not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _normalize_generation_conditions(value: Any) -> Dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    kg_mode = str(raw.get("kg_mode") or DEFAULT_GENERATION_CONDITIONS["kg_mode"])
    if kg_mode not in VALID_KG_MODES:
        kg_mode = DEFAULT_GENERATION_CONDITIONS["kg_mode"]
    prompt_strategy_version = str(
        raw.get("prompt_strategy_version") or DEFAULT_GENERATION_CONDITIONS["prompt_strategy_version"]
    ).strip() or DEFAULT_GENERATION_CONDITIONS["prompt_strategy_version"]
    return {
        "kg_mode": kg_mode,
        "log_reuse_enabled": bool(raw.get("log_reuse_enabled", DEFAULT_GENERATION_CONDITIONS["log_reuse_enabled"])),
        "review_flow_enabled": bool(raw.get("review_flow_enabled", DEFAULT_GENERATION_CONDITIONS["review_flow_enabled"])),
        "prompt_strategy_version": prompt_strategy_version[:80],
    }


def _condition_payload(value: Any, *, source: str, experiment_id: Optional[str] = None, updated_at: Optional[str] = None) -> Dict[str, Any]:
    return {
        **_normalize_generation_conditions(value),
        "source": source,
        "experiment_id": experiment_id,
        "updated_at": updated_at,
    }


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
    now_dt = datetime.now()
    now = now_dt.isoformat(timespec="seconds")
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    session_token = secrets.token_urlsafe(32)
    expires_at = _session_expires_at(now_dt)
    conn.execute(
        """
        INSERT INTO user_sessions (
            id, user_id, session_token, experiment_id, participant_label,
            created_at, updated_at, expires_at, last_seen_at
        )
        VALUES (:id, :user_id, :session_token, :experiment_id, :participant_label, :created_at, :updated_at, :expires_at, :last_seen_at)
        """,
        {
            "id": session_id,
            "user_id": user_id,
            "session_token": session_token,
            "experiment_id": experiment_id,
            "participant_label": participant_label,
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
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


def build_csrf_token(session_token: str) -> str:
    token = str(session_token or "").strip()
    if not token:
        return ""
    return hashlib.sha256(f"lecturecraft-csrf:{token}".encode("utf-8")).hexdigest()


def public_session_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    session_token = payload.get("session_token")
    public_payload = {
        key: value
        for key, value in payload.items()
        if key != "session_token"
    }
    public_payload["csrf_token"] = build_csrf_token(session_token)
    return public_payload


def register_user(username: str, password: str) -> Dict[str, Any]:
    now = _now_iso()
    clean_username = _normalize_username(username)
    password_value = _validate_password(password)
    password_hash = _hash_password(password_value)
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    with db_conn() as conn:
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
                    "role": "user",
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
    now_dt = datetime.now()
    now = now_dt.isoformat(timespec="seconds")
    next_expires_at = _session_expires_at(now_dt)
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT
                s.id AS session_id,
                s.session_token,
                s.experiment_id,
                s.participant_label,
                s.expires_at,
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
        expires_at = _parse_iso(row["expires_at"])
        if expires_at is not None and expires_at <= now_dt:
            conn.execute(
                "DELETE FROM user_sessions WHERE id = :session_id",
                {"session_id": row["session_id"]},
            )
            conn.raw.commit()
            raise ApiError(401, "SESSION_EXPIRED", "セッションの有効期限が切れました。再ログインしてください。")
        conn.execute(
            """
            UPDATE user_sessions
            SET updated_at = :updated_at, expires_at = :expires_at, last_seen_at = :last_seen_at
            WHERE id = :session_id
            """,
            {
                "updated_at": now,
                "expires_at": next_expires_at,
                "last_seen_at": now,
                "session_id": row["session_id"],
            },
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


def ensure_bootstrap_admin() -> Dict[str, Any] | None:
    username_raw = str(os.getenv("LECTURE_CRAFT_BOOTSTRAP_ADMIN_USERNAME") or "").strip()
    password_raw = os.getenv("LECTURE_CRAFT_BOOTSTRAP_ADMIN_PASSWORD")
    if not username_raw and not password_raw:
        return None
    if not username_raw or password_raw is None:
        raise RuntimeError(
            "LECTURE_CRAFT_BOOTSTRAP_ADMIN_USERNAME と "
            "LECTURE_CRAFT_BOOTSTRAP_ADMIN_PASSWORD は両方設定してください。"
        )

    now = _now_iso()
    clean_username = _normalize_username(username_raw)
    password_value = _validate_password(password_raw)
    password_hash = _hash_password(password_value)
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM users
            WHERE username = :username
            """,
            {"username": clean_username},
        ).fetchone()
        if row is None:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
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
                    "role": "admin",
                    "email": None,
                    "is_active": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            return {"created": True, "username": clean_username}
        conn.execute(
            """
            UPDATE users
            SET password_hash = :password_hash, role = :role, is_active = :is_active, updated_at = :updated_at
            WHERE id = :user_id
            """,
            {
                "password_hash": password_hash,
                "role": "admin",
                "is_active": 1,
                "updated_at": now,
                "user_id": row["id"],
            },
        )
    return {"created": False, "username": clean_username}


def guest_sessions_enabled() -> bool:
    return _truthy_env("LECTURE_CRAFT_ENABLE_GUEST_SESSIONS", default=False)


def _row_has_key(row: Any, key: str) -> bool:
    if isinstance(row, dict):
        return key in row
    try:
        return key in row.keys()
    except Exception:
        return False


def list_projects_for_user(user_id: str) -> List[Dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.name,
                p.created_at,
                p.updated_at,
                p.experiment_id,
                p.latest_state_json,
                (
                    SELECT COALESCE(MAX(version_number), 0)
                    FROM project_versions
                    WHERE project_id = p.id
                ) AS version_number
            FROM projects AS p
            WHERE p.user_id = :user_id
            ORDER BY p.updated_at DESC
            """,
            {"user_id": user_id},
        ).fetchall()
    return [_project_summary_from_row(row) for row in rows]


def _project_summary_from_row(row: Any) -> Dict[str, Any]:
    data = _loads(row["latest_state_json"], {})
    version_number = row["version_number"] if _row_has_key(row, "version_number") else None
    input_pdf = _project_input_pdf_meta_with_url(data.get("input_pdf"), row["id"]) if isinstance(data, dict) else None
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
        "version_number": version_number,
        "input_pdf": input_pdf,
        "has_pdf": bool(input_pdf and input_pdf.get("available")),
    }


def _project_payload_from_row(row: Any) -> Dict[str, Any]:
    data = _loads(row["latest_state_json"], {})
    version_number = row["version_number"] if _row_has_key(row, "version_number") else None
    existing_meta = data.get("project_meta") if isinstance(data, dict) else {}
    input_pdf = _project_input_pdf_meta_with_url(data.get("input_pdf"), row["id"]) if isinstance(data, dict) else None
    project_meta = {
        **(existing_meta if isinstance(existing_meta, dict) else {}),
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version_number": version_number,
    }
    if isinstance(data, dict):
        data = {
            **data,
            "project_meta": project_meta,
            "input_pdf": input_pdf,
        }
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "experiment_id": row["experiment_id"],
        "version_number": version_number,
        "data": data,
    }


def get_project_for_user(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT
                p.id,
                p.name,
                p.created_at,
                p.updated_at,
                p.experiment_id,
                p.latest_state_json,
                (
                    SELECT COALESCE(MAX(version_number), 0)
                    FROM project_versions
                    WHERE project_id = p.id
                ) AS version_number
            FROM projects AS p
            WHERE p.id = :project_id AND p.user_id = :user_id
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
            "SELECT id, created_at, latest_state_json FROM projects WHERE id = :project_id AND user_id = :user_id",
            {"project_id": project_id, "user_id": user_id},
        ).fetchone()
        existing_data = _loads(existing["latest_state_json"], {}) if existing is not None else {}
        data = _prepare_project_input_pdf(
            user_id=user_id,
            project_id=project_id,
            data=data,
            existing_data=existing_data,
        )
        data = _prepare_project_generated_artifacts(
            user_id=user_id,
            project_id=project_id,
            data=data,
            existing_data=existing_data,
        )
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
        version_id = f"ver_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO project_versions (
                id, project_id, version_number, saved_by_user_id, snapshot_json, created_at
            )
            VALUES (
                :id,
                :project_id,
                (
                    SELECT COALESCE(MAX(version_number), 0) + 1
                    FROM project_versions
                    WHERE project_id = :project_id
                ),
                :saved_by_user_id,
                :snapshot_json,
                :created_at
            )
            """,
            {
                "id": version_id,
                "project_id": project_id,
                "saved_by_user_id": user_id,
                "snapshot_json": payload_json,
                "created_at": now,
            },
        )
        version_row = conn.execute(
            "SELECT version_number FROM project_versions WHERE id = :id",
            {"id": version_id},
        ).fetchone()
        version_number = int(version_row["version_number"] if version_row else 1)
        generation_job_id = generation_ref.get("job_id") if isinstance(generation_ref, dict) else None
        if generation_job_id:
            conn.execute(
                """
                UPDATE generation_runs
                SET project_id = COALESCE(project_id, :project_id), updated_at = :updated_at
                WHERE job_id = :job_id AND user_id = :user_id
                """,
                {
                    "project_id": project_id,
                    "updated_at": now,
                    "job_id": generation_job_id,
                    "user_id": user_id,
                },
            )
            conn.execute(
                """
                UPDATE knowledge_graph_versions
                SET project_id = COALESCE(project_id, :project_id)
                WHERE job_id = :job_id AND user_id = :user_id
                """,
                {
                    "project_id": project_id,
                    "job_id": generation_job_id,
                    "user_id": user_id,
                },
            )
        row = conn.execute(
            """
            SELECT
                p.id,
                p.name,
                p.created_at,
                p.updated_at,
                p.experiment_id,
                p.latest_state_json,
                (
                    SELECT COALESCE(MAX(version_number), 0)
                    FROM project_versions
                    WHERE project_id = p.id
                ) AS version_number
            FROM projects AS p
            WHERE p.id = :project_id AND p.user_id = :user_id
            """,
            {"project_id": project_id, "user_id": user_id},
        ).fetchone()
    payload = _project_payload_from_row(row)
    project_meta = {
        **(payload.get("data", {}).get("project_meta", {}) if isinstance(payload.get("data"), dict) else {}),
        "id": project_id,
        "name": clean_name,
        "created_at": created_at,
        "updated_at": now,
        "version_number": version_number,
    }
    if isinstance(payload.get("data"), dict):
        payload["data"] = {
            **payload["data"],
            "project_meta": project_meta,
        }
    return {
        **payload,
        "version_number": version_number,
        "project_meta": project_meta,
    }


def delete_project_for_user(project_id: str, user_id: str) -> None:
    with db_conn() as conn:
        deleted = conn.execute(
            "DELETE FROM projects WHERE id = :project_id AND user_id = :user_id",
            {"project_id": project_id, "user_id": user_id},
        )
    if int(getattr(deleted, "rowcount", 0) or 0) == 0:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
    shutil.rmtree(_project_artifact_dir(user_id, project_id), ignore_errors=True)


def get_project_pdf_artifact(project_id: str, user_id: str) -> Dict[str, Any]:
    project = get_project_for_user(project_id, user_id)
    data = project.get("data", {}) if isinstance(project.get("data"), dict) else {}
    input_pdf = _sanitize_input_pdf_meta(data.get("input_pdf"))
    if not input_pdf or not input_pdf.get("available"):
        input_pdf = _project_pdf_meta_from_generation(
            user_id=user_id,
            project_id=project_id,
            data=data,
            existing_pdf=input_pdf,
        )
    if not input_pdf or not input_pdf.get("available"):
        raise ApiError(404, "PROJECT_PDF_NOT_FOUND", "保存済みPDFが見つかりません。")
    sha256 = str(input_pdf.get("sha256") or input_pdf.get("storage_key") or "").strip()
    path = _project_pdf_path(user_id, project_id, sha256)
    if not path.exists():
        generated_pdf = _project_pdf_meta_from_generation(
            user_id=user_id,
            project_id=project_id,
            data=data,
            existing_pdf=input_pdf,
        )
        if generated_pdf:
            input_pdf = generated_pdf
            sha256 = str(input_pdf.get("sha256") or input_pdf.get("storage_key") or "").strip()
            path = _project_pdf_path(user_id, project_id, sha256)
    if not path.exists():
        raise ApiError(404, "PROJECT_PDF_NOT_FOUND", "保存済みPDFファイルが見つかりません。")
    return {
        "path": path,
        "filename": input_pdf.get("name") or "slides.pdf",
        "media_type": input_pdf.get("type") or "application/pdf",
        "meta": input_pdf,
    }


def get_project_slide_image_artifact(project_id: str, user_id: str, slide_idx: int) -> Dict[str, Any]:
    if slide_idx < 0:
        raise ApiError(400, "INVALID_SLIDE_INDEX", "slide index must be non-negative")

    project = get_project_for_user(project_id, user_id)
    data = project.get("data") if isinstance(project.get("data"), dict) else {}
    path = _project_slide_image_path(user_id, project_id, slide_idx)
    if not path.exists():
        _prepare_project_slide_artifacts(user_id=user_id, project_id=project_id, data=data)
    if not path.exists():
        raise ApiError(404, "PROJECT_SLIDE_IMAGE_NOT_FOUND", "保存済みスライド画像が見つかりません。")
    return {
        "path": path,
        "filename": f"slide_{slide_idx + 1:03d}.png",
        "media_type": "image/png",
    }


def save_project_events(
    *,
    project_id: str,
    user_id: str,
    events: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    saved = 0
    skipped = 0
    with db_conn() as conn:
        project = _require_owned_project(conn, project_id, user_id)
        experiment_id = project["experiment_id"] if project else None
        for event in events:
            external_event_id = str(event.get("external_event_id") or event.get("id") or "").strip()
            if not external_event_id:
                skipped += 1
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            generation_run_id = str(
                event.get("generation_run_id")
                or payload.get("generation_run_id")
                or project["active_run_id"]
                or ""
            ).strip() or None
            if generation_run_id:
                run = conn.execute(
                    """
                    SELECT id FROM generation_runs
                    WHERE id = :run_id AND project_id = :project_id AND user_id = :user_id
                    """,
                    {"run_id": generation_run_id, "project_id": project_id, "user_id": user_id},
                ).fetchone()
                if run is None:
                    generation_run_id = None
            try:
                conn.execute(
                    """
                    INSERT INTO edit_events (
                        id, project_id, user_id, experiment_id, generation_run_id,
                        external_event_id, action_type, slide_idx,
                        entity_type, entity_id, source, before_json, after_json, payload_json, created_at
                    )
                    VALUES (
                        :id, :project_id, :user_id, :experiment_id, :generation_run_id,
                        :external_event_id, :action_type, :slide_idx,
                        :entity_type, :entity_id, :source, :before_json, :after_json, :payload_json, :created_at
                    )
                    """,
                    {
                        "id": f"evt_{uuid.uuid4().hex[:12]}",
                        "project_id": project_id,
                        "user_id": user_id,
                        "experiment_id": experiment_id,
                        "generation_run_id": generation_run_id,
                        "external_event_id": external_event_id,
                        "action_type": str(event.get("action_type") or "unknown"),
                        "slide_idx": event.get("slide_idx"),
                        "entity_type": event.get("entity_type"),
                        "entity_id": event.get("entity_id"),
                        "source": event.get("source"),
                        "before_json": json_text(event.get("before")) if event.get("before") is not None else None,
                        "after_json": json_text(event.get("after")) if event.get("after") is not None else None,
                        "payload_json": json_text(payload),
                        "created_at": str(event.get("created_at") or _now_iso()),
                    },
                )
                _save_correction_memory_from_event(
                    conn,
                    project_id=project_id,
                    user_id=user_id,
                    experiment_id=experiment_id,
                    generation_run_id=generation_run_id,
                    event={**event, "external_event_id": external_event_id},
                )
                saved += 1
            except Exception as exc:
                if _is_unique_error(exc):
                    skipped += 1
                    continue
                raise
    return {"saved": saved, "skipped": skipped}


def _save_correction_memory_from_event(
    conn: Any,
    *,
    project_id: str,
    user_id: str,
    experiment_id: Optional[str],
    generation_run_id: Optional[str],
    event: Dict[str, Any],
) -> None:
    before = event.get("before")
    after = event.get("after")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    action_type = str(event.get("action_type") or "unknown")
    if before is None and after is None and not action_type.startswith(("sentence_", "highlight_")):
        return
    source_event_id = str(event.get("external_event_id") or "").strip()
    if not source_event_id:
        return
    slide_idx = event.get("slide_idx")
    if slide_idx is None and isinstance(payload, dict):
        slide_idx = payload.get("slide_idx")
    region_ids = []
    for key in ("highlight_id", "id"):
        value = event.get(key) or payload.get(key)
        if value:
            region_ids.append(str(value))
    kg_node_ids = payload.get("kg_node_ids") if isinstance(payload.get("kg_node_ids"), list) else []
    slide_context = {
        "slide_idx": slide_idx,
        "sentence_id": event.get("entity_id") if event.get("entity_type") in {"sentence", "study_event"} else payload.get("sentence_id"),
        "highlight_id": payload.get("highlight_id") or event.get("entity_id"),
        "source": event.get("source"),
    }
    try:
        conn.execute(
            """
            INSERT INTO correction_memories (
                id, project_id, user_id, experiment_id, generation_run_id,
                source_event_id, edit_type, slide_idx,
                entity_type, entity_id, before_json, after_json, reason, slide_context_json,
                kg_node_ids_json, region_ids_json, prompt_version, created_at
            )
            VALUES (
                :id, :project_id, :user_id, :experiment_id, :generation_run_id,
                :source_event_id, :edit_type, :slide_idx,
                :entity_type, :entity_id, :before_json, :after_json, :reason, :slide_context_json,
                :kg_node_ids_json, :region_ids_json, :prompt_version, :created_at
            )
            """,
            {
                "id": f"cmem_{uuid.uuid4().hex[:12]}",
                "project_id": project_id,
                "user_id": user_id,
                "experiment_id": experiment_id,
                "generation_run_id": generation_run_id,
                "source_event_id": source_event_id,
                "edit_type": action_type,
                "slide_idx": slide_idx,
                "entity_type": event.get("entity_type"),
                "entity_id": event.get("entity_id"),
                "before_json": json_text(before) if before is not None else None,
                "after_json": json_text(after) if after is not None else None,
                "reason": payload.get("reason"),
                "slide_context_json": json_text(slide_context),
                "kg_node_ids_json": json_text(kg_node_ids),
                "region_ids_json": json_text(region_ids),
                "prompt_version": payload.get("prompt_version"),
                "created_at": str(event.get("created_at") or _now_iso()),
            },
        )
    except Exception as exc:
        if _is_unique_error(exc):
            return
        raise


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


def resolve_review_settings(*, experiment_id: Optional[str] = None) -> Dict[str, Any]:
    settings = get_review_settings()
    global_settings = settings.get("global") or {}
    effective = {
        "layout_review_mode": global_settings.get("layout_review_mode") or "off",
        "script_review_mode": global_settings.get("script_review_mode") or "off",
        "scope_type": "global",
        "scope_key": None,
        "updated_at": global_settings.get("updated_at"),
    }

    if experiment_id:
        for row in settings.get("experiments") or []:
            if row.get("experiment_id") == experiment_id:
                effective = {
                    "layout_review_mode": row.get("layout_review_mode") or effective["layout_review_mode"],
                    "script_review_mode": row.get("script_review_mode") or effective["script_review_mode"],
                    "scope_type": "experiment",
                    "scope_key": experiment_id,
                    "updated_at": row.get("updated_at"),
                }
                break

    return {
        "effective": effective,
        "global": global_settings,
        "experiment_id": experiment_id,
    }


def get_generation_conditions() -> Dict[str, Any]:
    with db_conn() as conn:
        setting = conn.execute(
            "SELECT value_json, updated_at FROM app_settings WHERE key = :key",
            {"key": GLOBAL_GENERATION_CONDITION_KEY},
        ).fetchone()
        experiment_rows = conn.execute(
            """
            SELECT id, name, generation_conditions_json, updated_at
            FROM experiments
            ORDER BY updated_at DESC, id ASC
            """
        ).fetchall()
    global_conditions = _condition_payload(
        _loads(setting["value_json"], {}) if setting else DEFAULT_GENERATION_CONDITIONS,
        source="global",
        updated_at=setting["updated_at"] if setting else None,
    )
    return {
        "global": global_conditions,
        "experiments": [
            {
                "experiment_id": row["id"],
                "name": row["name"],
                **_condition_payload(
                    _loads(row["generation_conditions_json"], {}),
                    source="experiment",
                    experiment_id=row["id"],
                    updated_at=row["updated_at"],
                ),
            }
            for row in experiment_rows
        ],
    }


def resolve_generation_conditions(*, experiment_id: Optional[str] = None) -> Dict[str, Any]:
    settings = get_generation_conditions()
    effective = settings["global"]
    if experiment_id:
        match = next(
            (row for row in settings.get("experiments") or [] if row.get("experiment_id") == experiment_id),
            None,
        )
        if match:
            effective = match
    return {
        "effective": effective,
        "global": settings["global"],
        "experiment_id": experiment_id,
    }


def upsert_generation_conditions(
    *,
    scope_type: str,
    scope_key: Optional[str],
    generation_conditions: Dict[str, Any],
) -> Dict[str, Any]:
    now = _now_iso()
    conditions = _normalize_generation_conditions(generation_conditions)
    with db_conn() as conn:
        if scope_type == "global":
            existing = conn.execute(
                "SELECT key, created_at FROM app_settings WHERE key = :key",
                {"key": GLOBAL_GENERATION_CONDITION_KEY},
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value_json, created_at, updated_at)
                    VALUES (:key, :value_json, :created_at, :updated_at)
                    """,
                    {
                        "key": GLOBAL_GENERATION_CONDITION_KEY,
                        "value_json": json_text(conditions),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            else:
                conn.execute(
                    """
                    UPDATE app_settings
                    SET value_json = :value_json, updated_at = :updated_at
                    WHERE key = :key
                    """,
                    {
                        "key": GLOBAL_GENERATION_CONDITION_KEY,
                        "value_json": json_text(conditions),
                        "updated_at": now,
                    },
                )
            return {
                "scope_type": "global",
                "scope_key": None,
                "generation_conditions": conditions,
                "updated_at": now,
            }

        clean_scope_key = str(scope_key or "").strip()
        if not clean_scope_key:
            raise ApiError(400, "INVALID_EXPERIMENT_ID", "実験IDを指定してください。")
        existing = conn.execute(
            "SELECT id FROM experiments WHERE id = :experiment_id",
            {"experiment_id": clean_scope_key},
        ).fetchone()
        if existing is None:
            raise ApiError(404, "EXPERIMENT_NOT_FOUND", "指定された実験IDが見つかりません。")
        conn.execute(
            """
            UPDATE experiments
            SET generation_conditions_json = :generation_conditions_json, updated_at = :updated_at
            WHERE id = :experiment_id
            """,
            {
                "generation_conditions_json": json_text(conditions),
                "updated_at": now,
                "experiment_id": clean_scope_key,
            },
        )
    return {
        "scope_type": "experiment",
        "scope_key": clean_scope_key,
        "generation_conditions": conditions,
        "updated_at": now,
    }


def create_generation_run(
    *,
    job_id: str,
    user_id: str,
    experiment_id: Optional[str],
    request_payload: Dict[str, Any],
    condition: Dict[str, Any],
    request_key: Optional[str] = None,
    pdf_hash: Optional[str] = None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now_iso()
    run_id = f"grun_{uuid.uuid4().hex[:12]}"
    clean_condition = _normalize_generation_conditions(condition)
    with db_conn() as conn:
        if project_id:
            owned = conn.execute(
                "SELECT id FROM projects WHERE id = :project_id AND user_id = :user_id",
                {"project_id": project_id, "user_id": user_id},
            ).fetchone()
            if owned is None:
                project_id = None
        conn.execute(
            """
            INSERT INTO generation_runs (
                id, job_id, project_id, user_id, experiment_id, request_key, pdf_hash,
                filename, mode, detail, difficulty, condition_json, prompt_strategy_version,
                status, artifact_refs_json, result_summary_json, created_at, updated_at
            )
            VALUES (
                :id, :job_id, :project_id, :user_id, :experiment_id, :request_key, :pdf_hash,
                :filename, :mode, :detail, :difficulty, :condition_json, :prompt_strategy_version,
                :status, :artifact_refs_json, :result_summary_json, :created_at, :updated_at
            )
            """,
            {
                "id": run_id,
                "job_id": job_id,
                "project_id": project_id,
                "user_id": user_id,
                "experiment_id": experiment_id,
                "request_key": request_key,
                "pdf_hash": pdf_hash,
                "filename": request_payload.get("filename"),
                "mode": request_payload.get("mode") or "hl",
                "detail": request_payload.get("detail") or "standard",
                "difficulty": request_payload.get("difficulty") or "basic",
                "condition_json": json_text(clean_condition),
                "prompt_strategy_version": clean_condition.get("prompt_strategy_version"),
                "status": "queued",
                "artifact_refs_json": json_text({}),
                "result_summary_json": json_text({}),
                "created_at": now,
                "updated_at": now,
            },
        )
    return {
        "id": run_id,
        "job_id": job_id,
        "condition": clean_condition,
        "status": "queued",
        "created_at": now,
    }


def update_generation_run_status(
    *,
    job_id: str,
    status: str,
    artifact_refs: Optional[Dict[str, Any]] = None,
    result_summary: Optional[Dict[str, Any]] = None,
) -> None:
    now = _now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE generation_runs
            SET status = :status,
                artifact_refs_json = COALESCE(:artifact_refs_json, artifact_refs_json),
                result_summary_json = COALESCE(:result_summary_json, result_summary_json),
                updated_at = :updated_at
            WHERE job_id = :job_id
            """,
            {
                "status": status,
                "artifact_refs_json": json_text(artifact_refs) if artifact_refs is not None else None,
                "result_summary_json": json_text(result_summary) if result_summary is not None else None,
                "updated_at": now,
                "job_id": job_id,
            },
        )


def get_generation_run_by_job(job_id: str) -> Optional[Dict[str, Any]]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT id, job_id, project_id, user_id, experiment_id, condition_json, prompt_strategy_version, status
            FROM generation_runs
            WHERE job_id = :job_id
            """,
            {"job_id": job_id},
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "experiment_id": row["experiment_id"],
        "condition": _normalize_generation_conditions(_loads(row["condition_json"], {})),
        "prompt_strategy_version": row["prompt_strategy_version"],
        "status": row["status"],
    }


def save_knowledge_graph_version(
    *,
    project_id: Optional[str],
    generation_run_id: Optional[str],
    job_id: Optional[str],
    user_id: Optional[str],
    experiment_id: Optional[str],
    kg_mode: str,
    graph: Dict[str, Any],
    quality_status: str = "auto_generated",
) -> Dict[str, Any]:
    now = _now_iso()
    graph_id = f"kg_{uuid.uuid4().hex[:12]}"
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    edges = graph.get("edges") if isinstance(graph.get("edges"), list) else []
    slide_refs = graph.get("slide_refs") if isinstance(graph.get("slide_refs"), list) else []
    region_refs = graph.get("region_refs") if isinstance(graph.get("region_refs"), list) else []
    sentence_refs = graph.get("sentence_refs") if isinstance(graph.get("sentence_refs"), list) else []
    with db_conn() as conn:
        if project_id and user_id:
            owned = conn.execute(
                "SELECT id FROM projects WHERE id = :project_id AND user_id = :user_id",
                {"project_id": project_id, "user_id": user_id},
            ).fetchone()
            if owned is None:
                project_id = None
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
                "id": graph_id,
                "project_id": project_id,
                "generation_run_id": generation_run_id,
                "job_id": job_id,
                "user_id": user_id,
                "experiment_id": experiment_id,
                "kg_mode": kg_mode if kg_mode in VALID_KG_MODES else "off",
                "nodes_json": json_text(nodes),
                "edges_json": json_text(edges),
                "slide_refs_json": json_text(slide_refs),
                "region_refs_json": json_text(region_refs),
                "sentence_refs_json": json_text(sentence_refs),
                "quality_status": quality_status,
                "payload_json": json_text(graph),
                "created_at": now,
            },
        )
    return {
        "id": graph_id,
        "kg_mode": kg_mode,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "created_at": now,
    }


def get_latest_knowledge_graph_for_project(project_id: str, user_id: str) -> Dict[str, Any]:
    with db_conn() as conn:
        _require_owned_project(conn, project_id, user_id)
        row = conn.execute(
            """
            SELECT id, project_id, generation_run_id, job_id, kg_mode, quality_status, payload_json, created_at
            FROM knowledge_graph_versions
            WHERE project_id = :project_id
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            {"project_id": project_id},
        ).fetchone()
    if row is None:
        raise ApiError(404, "KNOWLEDGE_GRAPH_NOT_FOUND", "このプロジェクトのナレッジグラフはまだ保存されていません。")
    payload = _loads(row["payload_json"], {})
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "generation_run_id": row["generation_run_id"],
        "job_id": row["job_id"],
        "kg_mode": row["kg_mode"],
        "quality_status": row["quality_status"],
        "created_at": row["created_at"],
        "graph": payload if isinstance(payload, dict) else {},
    }


def find_reusable_correction_memories(
    *,
    user_id: str,
    experiment_id: Optional[str],
    project_id: Optional[str],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    safe_limit = max(0, min(int(limit or 0), 20))
    if safe_limit <= 0:
        return []
    if not project_id:
        return []
    clauses = ["user_id = :user_id", "project_id = :project_id"]
    params: Dict[str, Any] = {"user_id": user_id, "project_id": project_id, "limit": safe_limit}
    if experiment_id:
        clauses.append("(experiment_id = :experiment_id OR experiment_id IS NULL)")
        params["experiment_id"] = experiment_id
    where_sql = " AND ".join(clauses)
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                id, edit_type, slide_idx, entity_type, entity_id, before_json, after_json,
                reason, slide_context_json, kg_node_ids_json, region_ids_json, prompt_version, created_at
            FROM correction_memories
            WHERE {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
            """,
            params,
        ).fetchall()
    memories: List[Dict[str, Any]] = []
    for row in rows:
        memories.append(
            {
                "id": row["id"],
                "edit_type": row["edit_type"],
                "slide_idx": row["slide_idx"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "before": _loads(row["before_json"], None),
                "after": _loads(row["after_json"], None),
                "reason": row["reason"],
                "slide_context": _loads(row["slide_context_json"], {}),
                "kg_node_ids": _loads(row["kg_node_ids_json"], []),
                "region_ids": _loads(row["region_ids_json"], []),
                "prompt_version": row["prompt_version"],
                "created_at": row["created_at"],
            }
        )
    return memories


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


def save_review_stage_snapshot(
    *,
    project_id: str,
    user_id: str,
    stage: str,
    status: str,
    snapshot: Dict[str, Any],
    generation_ref: Optional[Dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    clean_stage = str(stage or "").strip()
    if clean_stage not in {"layout", "script", "assignment"}:
        raise ApiError(400, "INVALID_REVIEW_STAGE", "review stage must be layout, script, or assignment.")
    clean_status = str(status or "confirmed").strip()
    if clean_status not in {"draft", "confirmed"}:
        raise ApiError(400, "INVALID_REVIEW_STATUS", "review status must be draft or confirmed.")
    now = _now_iso()
    snapshot_payload = {
        "stage": clean_stage,
        "status": clean_status,
        "snapshot": snapshot if isinstance(snapshot, dict) else {},
        "generation_ref": generation_ref if isinstance(generation_ref, dict) else {},
        "notes": notes,
        "saved_at": now,
    }
    with db_conn() as conn:
        project = _require_owned_project(conn, project_id, user_id)
        experiment_id = project["experiment_id"] if project else None
        conn.execute(
            """
            INSERT INTO review_stage_snapshots (
                id, project_id, user_id, experiment_id, stage, status, snapshot_json, created_at, updated_at
            )
            VALUES (
                :id, :project_id, :user_id, :experiment_id, :stage, :status, :snapshot_json, :created_at, :updated_at
            )
            """,
            {
                "id": f"rstage_{uuid.uuid4().hex[:12]}",
                "project_id": project_id,
                "user_id": user_id,
                "experiment_id": experiment_id,
                "stage": clean_stage,
                "status": clean_status,
                "snapshot_json": json_text(snapshot_payload),
                "created_at": now,
                "updated_at": now,
            },
        )
        review_states = _loads(project["review_states_json"], {})
        if not isinstance(review_states, dict):
            review_states = {}
        review_states[clean_stage] = {
            "status": clean_status,
            "saved_at": now,
        }
        conn.execute(
            """
            UPDATE projects
            SET review_states_json = :review_states_json, updated_at = :updated_at
            WHERE id = :project_id AND user_id = :user_id
            """,
            {
                "review_states_json": json_text(review_states),
                "updated_at": now,
                "project_id": project_id,
                "user_id": user_id,
            },
        )
    return {
        "ok": True,
        "project_id": project_id,
        "stage": clean_stage,
        "status": clean_status,
        "saved_at": now,
    }


def save_layout_review_records(
    *,
    project_id: str,
    user_id: str,
    records: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    saved = 0
    with db_conn() as conn:
        _require_owned_project(conn, project_id, user_id)
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
        _require_owned_project(conn, project_id, user_id)
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


def export_research_jsonl(
    *,
    actor_user_id: str,
    experiment_id: Optional[str] = None,
    project_id: Optional[str] = None,
    run_ids: Optional[List[str]] = None,
    included_only: bool = True,
    include_raw_text: bool = True,
    purpose: str = "analysis",
) -> Dict[str, Any]:
    now = _now_iso()
    export_id = f"rexport_{uuid.uuid4().hex[:12]}"
    rows = _load_correction_memory_rows_for_export(
        experiment_id=experiment_id,
        project_id=project_id,
        run_ids=run_ids or [],
        included_only=included_only,
    )
    jsonl_text = "".join(
        json.dumps(
            _research_jsonl_sample(row, include_raw_text=include_raw_text, purpose=purpose),
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
        for row in rows
    )
    stored = get_artifact_store().put_admin_export(
        io.BytesIO(jsonl_text.encode("utf-8")),
        export_id=export_id,
        original_filename=f"{export_id}.jsonl",
        media_type="application/x-ndjson",
    )
    payload = {
        "id": export_id,
        "created_at": now,
        "actor_user_id": actor_user_id,
        "experiment_id": experiment_id,
        "project_id": project_id,
        "status": "completed",
        "row_count": len(rows),
        "purpose": purpose,
        "include_raw_text": include_raw_text,
        "storage_key": stored.storage_key,
        "sha256": stored.sha256,
        "size_bytes": stored.size_bytes,
    }
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO research_export_snapshots (
                id, created_at, actor_user_id, experiment_id, status, row_count,
                options_json, output_path, payload_json
            )
            VALUES (
                :id, :created_at, :actor_user_id, :experiment_id, :status, :row_count,
                :options_json, :output_path, :payload_json
            )
            """,
            {
                "id": export_id,
                "created_at": now,
                "actor_user_id": actor_user_id,
                "experiment_id": experiment_id,
                "status": "completed",
                "row_count": len(rows),
                "options_json": json_text(
                    {
                        "project_id": project_id,
                        "run_ids": run_ids or [],
                        "included_only": included_only,
                        "include_raw_text": include_raw_text,
                        "purpose": purpose,
                    }
                ),
                "output_path": stored.storage_key,
                "payload_json": json_text(payload),
            },
        )
    return {
        "ok": True,
        "export_id": export_id,
        "row_count": len(rows),
        "download_url": f"/api/research/exports/{export_id}/content",
        "created_at": now,
    }


def get_research_export_path(export_id: str) -> Path:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT output_path
            FROM research_export_snapshots
            WHERE id = :export_id AND status = 'completed'
            """,
            {"export_id": export_id},
        ).fetchone()
    if row is None or not row["output_path"]:
        raise ApiError(404, "RESEARCH_EXPORT_NOT_FOUND", "研究exportが見つかりません。")
    path = get_artifact_store().resolve(row["output_path"])
    if not path.exists():
        raise ApiError(404, "RESEARCH_EXPORT_FILE_MISSING", "研究exportファイルが見つかりません。")
    return path


def _load_correction_memory_rows_for_export(
    *,
    experiment_id: Optional[str],
    project_id: Optional[str],
    run_ids: List[str],
    included_only: bool,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    if experiment_id:
        clauses.append("cm.experiment_id = :experiment_id")
        params["experiment_id"] = experiment_id
    if project_id:
        clauses.append("cm.project_id = :project_id")
        params["project_id"] = project_id
    if run_ids:
        placeholders = []
        for idx, run_id in enumerate(run_ids):
            key = f"run_id_{idx}"
            placeholders.append(f":{key}")
            params[key] = run_id
        clauses.append(f"cm.generation_run_id IN ({', '.join(placeholders)})")
    if included_only:
        clauses.extend(["gr.usage_context = 'research'", "gr.analysis_status = 'included'"])
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT
                cm.id,
                cm.project_id,
                cm.user_id,
                cm.experiment_id,
                cm.generation_run_id,
                cm.source_event_id,
                cm.edit_type,
                cm.slide_idx,
                cm.entity_type,
                cm.entity_id,
                cm.before_json,
                cm.after_json,
                cm.reason,
                cm.slide_context_json,
                cm.kg_node_ids_json,
                cm.region_ids_json,
                cm.prompt_version,
                cm.created_at,
                gr.condition_json,
                gr.model_json,
                gr.prompt_json
            FROM correction_memories AS cm
            LEFT JOIN generation_runs AS gr ON gr.id = cm.generation_run_id
            {where_sql}
            ORDER BY cm.created_at ASC, cm.id ASC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def _research_jsonl_sample(row: Dict[str, Any], *, include_raw_text: bool, purpose: str) -> Dict[str, Any]:
    before = _loads(row.get("before_json"), None)
    after = _loads(row.get("after_json"), None)
    if not include_raw_text:
        before = _summarize_without_text(before)
        after = _summarize_without_text(after)
    return {
        "sample_id": _anonymize_id(row.get("id")),
        "purpose": purpose,
        "participant_hash": _anonymize_id(row.get("user_id")),
        "project_hash": _anonymize_id(row.get("project_id")),
        "experiment_id": row.get("experiment_id"),
        "run_hash": _anonymize_id(row.get("generation_run_id")),
        "generation_condition": _loads(row.get("condition_json"), {}),
        "model": _loads(row.get("model_json"), {}),
        "prompt": _loads(row.get("prompt_json"), {}),
        "edit_type": row.get("edit_type"),
        "slide_idx": row.get("slide_idx"),
        "entity_type": row.get("entity_type"),
        "entity_id": row.get("entity_id"),
        "before": before,
        "after": after,
        "reason": row.get("reason"),
        "slide_context": _loads(row.get("slide_context_json"), {}),
        "kg_node_ids": _loads(row.get("kg_node_ids_json"), []),
        "region_ids": _loads(row.get("region_ids_json"), []),
        "prompt_version": row.get("prompt_version"),
        "created_at": row.get("created_at"),
    }


def _anonymize_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    salt = os.getenv("LECTURE_CRAFT_EXPORT_SALT", "lecturecraft-research-export-v1")
    return hashlib.sha256(f"{salt}:{text}".encode("utf-8")).hexdigest()[:16]


def _summarize_without_text(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if key in {"text", "before_text", "after_text"}:
                redacted[f"{key}_length"] = len(str(item or ""))
            else:
                redacted[key] = _summarize_without_text(item)
        return redacted
    if isinstance(value, list):
        return [_summarize_without_text(item) for item in value]
    if isinstance(value, str):
        return {"text_length": len(value)}
    return value


def _require_owned_project(conn: Any, project_id: str, user_id: str) -> Any:
    project = conn.execute(
        """
        SELECT id, experiment_id, active_run_id, latest_state_json, review_states_json
        FROM projects
        WHERE id = :project_id AND user_id = :user_id
        """,
        {"project_id": project_id, "user_id": user_id},
    ).fetchone()
    if project is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", f"project not found: {project_id}")
    return project
