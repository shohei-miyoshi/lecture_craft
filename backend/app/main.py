from __future__ import annotations

import base64
import hmac
import importlib.util
import json
import os
import shutil
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Header, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .admin import build_admin_overview
from .db import assert_storage_schema_ready, db_kind, init_db
from .jobs import get_job_manager
from .models import (
    AuthCredentialsRequest,
    ExperimentConditionPatchRequest,
    ExperimentJoinRequest,
    FinalRenderStartRequest,
    LayoutReviewRequest,
    PreviewAudioRequest,
    GenerationRunCreateRequest,
    ProjectCreateV2Request,
    ProjectDraftPutRequest,
    ProjectEventsRequest,
    ProjectRevisionRequest,
    ResearchJsonlExportRequest,
    ResearchSessionRequest,
    ReviewAssignmentStartRequest,
    ReviewStageConfirmRequest,
    ReviewSettingsPatchRequest,
    RunAnalysisStatusRequest,
    ScriptReviewRequest,
)
from .persistence import (
    build_csrf_token,
    create_guest_session,
    ensure_bootstrap_admin,
    export_research_jsonl,
    find_reusable_correction_memories,
    guest_sessions_enabled,
    get_generation_conditions,
    get_latest_knowledge_graph_for_project,
    list_project_preferences,
    get_project_pdf_artifact,
    get_project_slide_image_artifact,
    get_research_export_path,
    get_review_settings,
    resolve_generation_conditions,
    resolve_review_settings,
    get_session_context,
    join_experiment,
    login_user,
    public_session_payload,
    logout_session,
    register_user,
    save_layout_review_records,
    save_project_events,
    save_script_review_records,
    upsert_generation_conditions,
    upsert_review_settings,
)
from .service import ApiError, get_audio_preview_media_path, save_research_session
from .storage_persistence import (
    archive_project_v2,
    checkpoint_project,
    confirm_review_stage,
    create_generation_run_v2,
    create_project_v2,
    get_artifact_for_request,
    get_generation_run_v2,
    get_project_v2,
    list_admin_artifacts,
    list_admin_runs,
    list_projects_v2,
    mark_generation_run_submission_failed,
    save_project_draft,
    save_source_pdf,
    update_run_analysis_status,
)

LOCAL_COOKIE_HOSTS = {"localhost", "127.0.0.1", "::1"}
CSRF_HEADER_NAME = "X-LectureCraft-CSRF"
GATEWAY_SECRET_HEADER_NAME = "X-LectureCraft-Gateway-Secret"

_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_production() -> bool:
    return str(os.getenv("LECTURE_CRAFT_ENV") or os.getenv("APP_ENV") or "").strip().lower() in {
        "prod",
        "production",
    }


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(str(os.getenv(name, str(default))).strip()))
    except Exception:
        return max(minimum, default)


def _env_default_bool(name: str, *, production_default: bool, dev_default: bool) -> bool:
    return _truthy_env(name, production_default if _is_production() else dev_default)


def _cors_origins() -> list[str]:
    raw = os.getenv("LECTURE_CRAFT_CORS_ORIGINS", "").strip()
    if raw:
        if raw == "*":
            if _is_production():
                raise RuntimeError("LECTURE_CRAFT_CORS_ORIGINS='*' is not allowed in production.")
            return ["*"]
        return [value.strip() for value in raw.split(",") if value.strip()]
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:4175",
        "http://127.0.0.1:4175",
    ]


app = FastAPI(title="LectureCraft Backend API")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MCP_GATEWAY_NAMES = "lecture_craft_prod,lecture_craft,lecture_craft_dev,lecture_craft_exp"


def _max_request_bytes() -> int:
    return _int_env("LECTURE_CRAFT_MAX_REQUEST_BYTES", 90 * 1024 * 1024, minimum=1024 * 1024)


def _request_scheme(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-proto")
    if forwarded:
        return forwarded.split(",", 1)[0].strip().lower()
    return str(request.url.scheme or "").lower()


def _client_fingerprint(request: Request) -> str:
    if _truthy_env("LECTURE_CRAFT_TRUST_PROXY_HEADERS", default=True):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _rate_limit_or_raise(*, bucket: str, limit: int, window_seconds: int, message: str) -> None:
    if limit <= 0 or window_seconds <= 0:
        return
    now = time.monotonic()
    cutoff = now - window_seconds
    with _RATE_LIMIT_LOCK:
        values = _RATE_LIMIT_BUCKETS[bucket]
        while values and values[0] < cutoff:
            values.popleft()
        if len(values) >= limit:
            raise ApiError(429, "RATE_LIMITED", message)
        values.append(now)


def _rate_limit_request(
    request: Request,
    *,
    name: str,
    subject: str,
    limit_env: str,
    window_env: str,
    default_limit: int,
    default_window_seconds: int,
    message: str,
) -> None:
    limit = _int_env(limit_env, default_limit, minimum=0)
    window = _int_env(window_env, default_window_seconds, minimum=1)
    _rate_limit_or_raise(bucket=f"{name}:{subject}", limit=limit, window_seconds=window, message=message)


def _require_gateway_secret_if_configured(request: Request) -> None:
    expected = str(os.getenv("LECTURE_CRAFT_GATEWAY_SECRET") or "").strip()
    if not expected:
        return
    received = str(request.headers.get(GATEWAY_SECRET_HEADER_NAME) or "").strip()
    if not received or not hmac.compare_digest(received, expected):
        raise ApiError(403, "INVALID_GATEWAY_SECRET", "API gateway の認証に失敗しました。")


def _session_cookie_name() -> str:
    return str(os.getenv("LECTURE_CRAFT_SESSION_COOKIE_NAME") or "lecture_craft_session").strip() or "lecture_craft_session"


def _session_cookie_domain() -> str | None:
    value = str(os.getenv("LECTURE_CRAFT_SESSION_COOKIE_DOMAIN") or "").strip()
    return value or None


def _session_cookie_secure(request: Request | None = None) -> bool:
    raw = os.getenv("LECTURE_CRAFT_SESSION_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    host = str(request.url.hostname if request is not None and request.url else "").strip().lower()
    if host in LOCAL_COOKIE_HOSTS:
        return False
    return True


def _session_cookie_samesite() -> str:
    raw = str(os.getenv("LECTURE_CRAFT_SESSION_COOKIE_SAMESITE") or "lax").strip().lower()
    if raw not in {"lax", "strict", "none"}:
        return "lax"
    return raw


def _session_cookie_max_age() -> int:
    raw = str(os.getenv("LECTURE_CRAFT_SESSION_TTL_HOURS") or "24").strip()
    try:
        return max(3600, int(raw) * 3600)
    except Exception:
        return 24 * 3600


def _header_session_fallback_enabled() -> bool:
    return _env_default_bool(
        "LECTURE_CRAFT_ENABLE_HEADER_SESSION_AUTH",
        production_default=False,
        dev_default=True,
    )


def _public_registration_enabled() -> bool:
    return _env_default_bool(
        "LECTURE_CRAFT_ENABLE_PUBLIC_REGISTRATION",
        production_default=False,
        dev_default=True,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def production_safety_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _max_request_bytes():
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "REQUEST_TOO_LARGE",
                            "message": "リクエストが大きすぎます。PDFサイズを小さくしてください。",
                        }
                    },
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "INVALID_CONTENT_LENGTH", "message": "Content-Length が不正です。"}},
            )

    if request.url.path.startswith("/qu/mcp/"):
        try:
            _require_gateway_secret_if_configured(request)
        except ApiError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code, "message": exc.message}},
            )

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        os.getenv(
            "LECTURE_CRAFT_CONTENT_SECURITY_POLICY",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        ),
    )
    if _request_scheme(request) == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.get("/api/health")
def health_endpoint():
    has_moviepy = importlib.util.find_spec("moviepy") is not None
    has_detectron2 = importlib.util.find_spec("detectron2") is not None
    has_imageio_ffmpeg = importlib.util.find_spec("imageio_ffmpeg") is not None
    ffmpeg_path = shutil.which("ffmpeg")
    model_path = PROJECT_ROOT / "models" / "model_final.pth"

    return {
        "ok": True,
        "service": "lecture-craft-backend-api",
        "capabilities": {
            "audio_ready": ffmpeg_path is not None,
            "video_ready": all(
                [
                    has_moviepy,
                    has_detectron2,
                    has_imageio_ffmpeg,
                    ffmpeg_path is not None,
                    model_path.exists(),
                ]
            ),
            "moviepy": has_moviepy,
            "detectron2": has_detectron2,
            "imageio_ffmpeg": has_imageio_ffmpeg,
            "ffmpeg": ffmpeg_path is not None,
            "layout_model": model_path.exists(),
        },
    }


def _mcp_gateway_names() -> set[str]:
    raw = os.getenv("LECTURE_CRAFT_MCP_GATEWAY_NAMES", DEFAULT_MCP_GATEWAY_NAMES)
    return {part.strip() for part in raw.split(",") if part.strip()}


def _asgi_header_pairs(headers: dict) -> list[tuple[bytes, bytes]]:
    pairs: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        name = str(key).strip().lower()
        if not name or name in {"host", "content-length"}:
            continue
        pairs.append((name.encode("latin-1"), str(value).encode("latin-1")))
    return pairs


def _split_target_path(path: str) -> tuple[str, bytes]:
    parsed = urlsplit(str(path or ""))
    target_path = parsed.path or ""
    query_string = parsed.query.encode("utf-8")
    return target_path, query_string


def _merge_gateway_headers(request: Request, headers: dict) -> dict:
    blocked_client_headers = {
        "authorization",
        "cookie",
        "host",
        "content-length",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-kenkyu-session",
        GATEWAY_SECRET_HEADER_NAME.lower(),
    }
    merged = {
        str(key): str(value)
        for key, value in (headers or {}).items()
        if str(key).strip().lower() not in blocked_client_headers
    }
    for header_name in ("cookie", "x-kenkyu-session"):
        incoming = request.headers.get(header_name)
        if incoming:
            merged[header_name] = incoming
    return merged


async def _dispatch_internal_api(
    request: Request,
    *,
    method: str,
    path: str,
    query_string: bytes,
    headers: dict,
    body: bytes,
) -> Response:
    response_start: dict = {}
    response_chunks: list[bytes] = []
    body_sent = False

    async def receive() -> dict:
        nonlocal body_sent
        if body_sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        body_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            response_start.update(message)
        elif message["type"] == "http.response.body":
            response_chunks.append(message.get("body", b""))

    scope = dict(request.scope)
    scope.update(
        {
            "method": method,
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query_string,
            "headers": _asgi_header_pairs(headers),
        }
    )
    await app(scope, receive, send)

    response = Response(
        content=b"".join(response_chunks),
        status_code=int(response_start.get("status", 500)),
    )
    raw_headers = [
        (key, value)
        for key, value in response_start.get("headers", [])
        if key.lower() not in {b"content-length"}
    ]
    if raw_headers:
        response.raw_headers = raw_headers
    return response


@app.get("/qu/mcp/{endpoint_name}")
def mcp_gateway_info_endpoint(endpoint_name: str):
    if endpoint_name not in _mcp_gateway_names():
        raise ApiError(404, "MCP_GATEWAY_NOT_FOUND", f"unknown LectureCraft MCP gateway: {endpoint_name}")
    return {
        "ok": True,
        "service": "lecture-craft-backend-api",
        "gateway": endpoint_name,
        "usage": {
            "method": "POST",
            "body": {"method": "GET", "path": "/api/health"},
        },
    }


@app.post("/qu/mcp/{endpoint_name}")
async def mcp_gateway_endpoint(endpoint_name: str, request: Request):
    if endpoint_name not in _mcp_gateway_names():
        raise ApiError(404, "MCP_GATEWAY_NOT_FOUND", f"unknown LectureCraft MCP gateway: {endpoint_name}")
    try:
        payload = await request.json()
    except Exception as exc:
        raise ApiError(400, "INVALID_MCP_GATEWAY_PAYLOAD", "MCP gateway payload must be JSON.") from exc
    if not isinstance(payload, dict):
        raise ApiError(400, "INVALID_MCP_GATEWAY_PAYLOAD", "MCP gateway payload must be an object.")

    method = str(payload.get("method") or "GET").upper()
    target_path, query_string = _split_target_path(str(payload.get("path") or ""))
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise ApiError(400, "INVALID_MCP_GATEWAY_METHOD", f"unsupported method: {method}")
    if not target_path.startswith("/api/"):
        raise ApiError(400, "INVALID_MCP_GATEWAY_PATH", "MCP gateway path must start with /api/.")

    headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
    headers = _merge_gateway_headers(request, headers)
    body_base64 = payload.get("body_base64")
    if body_base64 is not None:
        try:
            body = base64.b64decode(str(body_base64), validate=True)
        except Exception as exc:
            raise ApiError(400, "INVALID_MCP_GATEWAY_BODY", "MCP gateway body_base64 is invalid.") from exc
    else:
        body_value = payload.get("body")
        if body_value is None:
            body = b""
        elif isinstance(body_value, str):
            body = body_value.encode("utf-8")
        else:
            body = json.dumps(body_value, ensure_ascii=False).encode("utf-8")

    return await _dispatch_internal_api(
        request,
        method=method,
        path=target_path,
        query_string=query_string,
        headers=headers,
        body=body,
    )


@app.on_event("startup")
def startup_event() -> None:
    if _is_production():
        if db_kind() != "postgres":
            raise RuntimeError("Production requires PostgreSQL. Set DATABASE_URL before starting LectureCraft.")
        assert_storage_schema_ready()
    else:
        init_db()
    ensure_bootstrap_admin()
    get_job_manager()


def _extract_session_token(request: Request, x_kenkyu_session: str | None) -> str:
    header_token = str(x_kenkyu_session or "").strip()
    if header_token:
        if not _header_session_fallback_enabled():
            raise ApiError(400, "HEADER_SESSION_AUTH_DISABLED", "本番環境では Cookie 認証を使用してください。")
        return header_token
    return str(request.cookies.get(_session_cookie_name()) or "").strip()


def _require_session(request: Request, x_kenkyu_session: str | None) -> dict:
    return get_session_context(_extract_session_token(request, x_kenkyu_session))


def _require_admin(request: Request, x_kenkyu_session: str | None) -> dict:
    session = _require_session(request, x_kenkyu_session)
    if session["user"].get("role") != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "この操作は管理者のみ実行できます。")
    return session


def _require_csrf(request: Request, session: dict) -> None:
    expected = build_csrf_token(session.get("session_token"))
    received = str(request.headers.get(CSRF_HEADER_NAME, "")).strip()
    if not expected or not received:
        raise ApiError(403, "CSRF_REQUIRED", "安全のため、ページを再読み込みしてから再度実行してください。")
    if not hmac.compare_digest(received, expected):
        raise ApiError(403, "INVALID_CSRF", "CSRF 検証に失敗しました。再ログインしてください。")


def _require_session_for_write(request: Request, x_kenkyu_session: str | None) -> dict:
    session = _require_session(request, x_kenkyu_session)
    _require_csrf(request, session)
    return session


def _set_session_cookie(request: Request, response: Response, session_token: str | None) -> None:
    token = str(session_token or "").strip()
    if not token:
        return
    response.set_cookie(
        key=_session_cookie_name(),
        value=token,
        httponly=True,
        secure=_session_cookie_secure(request),
        samesite=_session_cookie_samesite(),
        max_age=_session_cookie_max_age(),
        path="/",
        domain=_session_cookie_domain(),
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_session_cookie_name(),
        path="/",
        domain=_session_cookie_domain(),
    )


@app.post("/api/auth/register")
def auth_register_endpoint(request: Request, req: AuthCredentialsRequest, response: Response):
    if not _public_registration_enabled():
        raise ApiError(403, "PUBLIC_REGISTRATION_DISABLED", "新規登録は現在無効です。管理者にアカウント発行を依頼してください。")
    _rate_limit_request(
        request,
        name="register",
        subject=_client_fingerprint(request),
        limit_env="LECTURE_CRAFT_REGISTER_RATE_LIMIT",
        window_env="LECTURE_CRAFT_REGISTER_RATE_WINDOW_SECONDS",
        default_limit=5,
        default_window_seconds=3600,
        message="新規登録の試行回数が多すぎます。時間を置いて再度試してください。",
    )
    payload = register_user(req.username, req.password)
    _set_session_cookie(request, response, payload.get("session_token"))
    return public_session_payload(payload)


@app.post("/api/auth/login")
def auth_login_endpoint(request: Request, req: AuthCredentialsRequest, response: Response):
    username_key = str(req.username or "").strip().lower()[:80]
    _rate_limit_request(
        request,
        name="login_ip",
        subject=_client_fingerprint(request),
        limit_env="LECTURE_CRAFT_LOGIN_IP_RATE_LIMIT",
        window_env="LECTURE_CRAFT_LOGIN_RATE_WINDOW_SECONDS",
        default_limit=60,
        default_window_seconds=600,
        message="ログイン試行が多すぎます。時間を置いて再度試してください。",
    )
    _rate_limit_request(
        request,
        name="login_user",
        subject=f"{_client_fingerprint(request)}:{username_key}",
        limit_env="LECTURE_CRAFT_LOGIN_USER_RATE_LIMIT",
        window_env="LECTURE_CRAFT_LOGIN_RATE_WINDOW_SECONDS",
        default_limit=10,
        default_window_seconds=600,
        message="ログイン試行が多すぎます。時間を置いて再度試してください。",
    )
    payload = login_user(req.username, req.password)
    _set_session_cookie(request, response, payload.get("session_token"))
    return public_session_payload(payload)


@app.post("/api/auth/logout")
def auth_logout_endpoint(request: Request, response: Response, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    payload = logout_session(session.get("session_token") or "")
    _clear_session_cookie(response)
    return payload


@app.get("/api/auth/me")
def auth_me_endpoint(request: Request, x_kenkyu_session: str | None = Header(default=None)):
    return public_session_payload(_require_session(request, x_kenkyu_session))


@app.post("/api/auth/guest")
def guest_session_endpoint(request: Request, response: Response):
    if not guest_sessions_enabled():
        raise ApiError(404, "GUEST_SESSION_DISABLED", "ゲスト利用は現在無効です。")
    payload = create_guest_session()
    _set_session_cookie(request, response, payload.get("session_token"))
    return public_session_payload(payload)


@app.post("/api/experiments/join")
def experiment_join_endpoint(request: Request, req: ExperimentJoinRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return join_experiment(session_token=session.get("session_token") or "", invite_code=req.invite_code)


@app.get("/api/experiments/current-condition")
def current_experiment_condition_endpoint(request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    return resolve_generation_conditions(experiment_id=session.get("experiment_id"))


@app.get("/api/projects")
def projects_list_endpoint(request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    return {"projects": list_projects_v2(session["user"]["id"])}


@app.post("/api/projects")
def project_create_endpoint(request: Request, req: ProjectCreateV2Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return create_project_v2(
        user_id=session["user"]["id"],
        experiment_id=session.get("experiment_id"),
        name=req.name,
        usage_context=req.usage_context,
    )


@app.get("/api/projects/{project_id}")
def project_get_endpoint(project_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    return get_project_v2(project_id, session["user"]["id"])


@app.get("/api/projects/{project_id}/pdf")
def legacy_project_pdf_endpoint(project_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    artifact = get_project_pdf_artifact(project_id, session["user"]["id"])
    return FileResponse(
        artifact["path"],
        media_type=artifact["media_type"],
        filename=artifact["filename"],
    )


@app.get("/api/projects/{project_id}/slides/{slide_idx}/image")
def legacy_project_slide_image_endpoint(
    project_id: str,
    slide_idx: int,
    request: Request,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session(request, x_kenkyu_session)
    artifact = get_project_slide_image_artifact(project_id, session["user"]["id"], slide_idx)
    return FileResponse(
        artifact["path"],
        media_type=artifact["media_type"],
        filename=artifact["filename"],
    )


@app.put("/api/projects/{project_id}/source-pdf")
def project_source_pdf_endpoint(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session_for_write(request, x_kenkyu_session)
    return save_source_pdf(
        project_id=project_id,
        user_id=session["user"]["id"],
        stream=file.file,
        filename=file.filename or "slides.pdf",
        media_type=file.content_type or "application/pdf",
    )


@app.put("/api/projects/{project_id}/draft")
def project_draft_endpoint(
    project_id: str,
    request: Request,
    req: ProjectDraftPutRequest,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session_for_write(request, x_kenkyu_session)
    return save_project_draft(
        project_id=project_id,
        user_id=session["user"]["id"],
        base_version=req.base_version,
        state=req.data,
        name=req.name,
    )


@app.post("/api/projects/{project_id}/revisions")
def project_revision_endpoint(
    project_id: str,
    request: Request,
    req: ProjectRevisionRequest,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session_for_write(request, x_kenkyu_session)
    return checkpoint_project(
        project_id=project_id,
        user_id=session["user"]["id"],
        revision_kind=req.revision_kind,
    )


@app.delete("/api/projects/{project_id}")
def project_delete_endpoint(project_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    archive_project_v2(project_id, session["user"]["id"])
    return {"ok": True, "project_id": project_id, "archived": True}


@app.post("/api/projects/{project_id}/events")
def project_events_endpoint(project_id: str, request: Request, req: ProjectEventsRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return save_project_events(
        project_id=project_id,
        user_id=session["user"]["id"],
        events=[row.model_dump() for row in req.events],
    )


@app.get("/api/projects/{project_id}/preferences")
def project_preferences_endpoint(
    project_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session(request, x_kenkyu_session)
    return list_project_preferences(
        project_id=project_id,
        user_id=session["user"]["id"],
        limit=limit,
    )


@app.post("/api/projects/{project_id}/runs")
def project_run_create_endpoint(
    project_id: str,
    request: Request,
    req: GenerationRunCreateRequest,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session_for_write(request, x_kenkyu_session)
    _rate_limit_request(
        request,
        name="generate",
        subject=session["user"]["id"],
        limit_env="LECTURE_CRAFT_GENERATE_RATE_LIMIT",
        window_env="LECTURE_CRAFT_GENERATE_RATE_WINDOW_SECONDS",
        default_limit=20,
        default_window_seconds=3600,
        message="生成回数が多すぎます。時間を置いて再度試してください。",
    )
    condition_payload = resolve_generation_conditions(experiment_id=session.get("experiment_id"))
    conditions = condition_payload.get("effective") if isinstance(condition_payload.get("effective"), dict) else {}
    review_flow_enabled = conditions.get("review_flow_enabled") is not False
    layout_review_enabled = review_flow_enabled and req.mode == "hl" and req.layout_review_enabled
    script_review_enabled = review_flow_enabled and req.script_review_enabled
    project_context = get_project_v2(project_id, user_id=session["user"]["id"])
    correction_memories = (
        find_reusable_correction_memories(
            user_id=session["user"]["id"],
            experiment_id=session.get("experiment_id"),
            project_id=project_id,
            limit=8,
            query_context_text=(
                f"mode={req.mode}\n"
                f"difficulty={req.difficulty}\n"
                f"detail={req.detail}\n"
                f"usage_context={req.usage_context}\n"
                f"project_name={project_context.get('name') or ''}"
            ),
            query_context={
                "mode": req.mode,
                "difficulty": req.difficulty,
                "detail": req.detail,
                "usage_context": req.usage_context,
            },
        )
        if conditions.get("log_reuse_enabled")
        else []
    )
    run = create_generation_run_v2(
        project_id=project_id,
        user_id=session["user"]["id"],
        experiment_id=session.get("experiment_id"),
        source_artifact_id=req.source_artifact_id,
        mode=req.mode,
        detail=req.detail,
        difficulty=req.difficulty,
        conditions=conditions,
        usage_context=req.usage_context,
    )
    try:
        submitted = get_job_manager().submit_project_run(
            run_id=run["id"],
            project_id=project_id,
            source_artifact_id=req.source_artifact_id,
            owner_user_id=session["user"]["id"],
            owner_session_id=session["session_id"],
            experiment_id=session.get("experiment_id"),
            mode=req.mode,
            detail=req.detail,
            difficulty=req.difficulty,
            layout_review_enabled=layout_review_enabled,
            script_review_enabled=script_review_enabled,
            generation_conditions=conditions,
            correction_memories=correction_memories,
        )
    except Exception as exc:
        mark_generation_run_submission_failed(run["id"], str(exc))
        raise
    submitted["generation_run"] = get_generation_run_v2(run["id"], user_id=session["user"]["id"])
    submitted["experiment_condition"] = conditions
    submitted["correction_memory_count"] = len(correction_memories)
    submitted["preference_memory_count"] = sum(
        1 for row in correction_memories if row.get("preference_text")
    )
    return JSONResponse(status_code=202, content=submitted)


@app.get("/api/runs/{run_id}")
def generation_run_get_endpoint(
    run_id: str,
    request: Request,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session(request, x_kenkyu_session)
    return get_generation_run_v2(
        run_id,
        user_id=session["user"]["id"],
        admin=session["user"].get("role") == "admin",
    )


@app.get("/api/artifacts/{artifact_id}/content")
def artifact_content_endpoint(
    artifact_id: str,
    request: Request,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session(request, x_kenkyu_session)
    artifact = get_artifact_for_request(
        artifact_id,
        requester_user_id=session["user"]["id"],
        requester_role=session["user"].get("role") or "user",
    )
    return FileResponse(
        artifact["path"],
        media_type=artifact["media_type"],
        filename=artifact["filename"],
    )


@app.get("/api/admin/review-settings")
def review_settings_get_endpoint(request: Request, x_kenkyu_session: str | None = Header(default=None)):
    _require_admin(request, x_kenkyu_session)
    return get_review_settings()


@app.get("/api/admin/experiment-conditions")
def experiment_conditions_get_endpoint(request: Request, x_kenkyu_session: str | None = Header(default=None)):
    _require_admin(request, x_kenkyu_session)
    return get_generation_conditions()


@app.get("/api/admin/artifacts")
def admin_artifacts_endpoint(
    request: Request,
    project_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    experiment_id: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    x_kenkyu_session: str | None = Header(default=None),
):
    _require_admin(request, x_kenkyu_session)
    return list_admin_artifacts(
        project_id=project_id,
        run_id=run_id,
        user_id=user_id,
        experiment_id=experiment_id,
        kind=kind,
        status=status,
        limit=limit,
    )


@app.get("/api/admin/runs")
def admin_runs_endpoint(
    request: Request,
    project_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    experiment_id: str | None = Query(default=None),
    usage_context: str | None = Query(default=None),
    analysis_status: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    x_kenkyu_session: str | None = Header(default=None),
):
    _require_admin(request, x_kenkyu_session)
    return list_admin_runs(
        project_id=project_id,
        user_id=user_id,
        experiment_id=experiment_id,
        usage_context=usage_context,
        analysis_status=analysis_status,
        status=status,
        limit=limit,
    )


@app.patch("/api/admin/runs/{run_id}/analysis-status")
def admin_run_analysis_status_endpoint(
    run_id: str,
    request: Request,
    req: RunAnalysisStatusRequest,
    x_kenkyu_session: str | None = Header(default=None),
):
    _require_csrf(request, _require_admin(request, x_kenkyu_session))
    return update_run_analysis_status(run_id, req.analysis_status)


@app.get("/api/review-settings/current")
def current_review_settings_endpoint(request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    return resolve_review_settings(experiment_id=session.get("experiment_id"))


@app.patch("/api/admin/review-settings")
def review_settings_patch_endpoint(request: Request, req: ReviewSettingsPatchRequest, x_kenkyu_session: str | None = Header(default=None)):
    _require_csrf(request, _require_admin(request, x_kenkyu_session))
    return upsert_review_settings(
        scope_type=req.scope_type,
        scope_key=req.scope_key,
        layout_review_mode=req.layout_review_mode,
        script_review_mode=req.script_review_mode,
    )


@app.patch("/api/admin/experiment-conditions")
def experiment_conditions_patch_endpoint(request: Request, req: ExperimentConditionPatchRequest, x_kenkyu_session: str | None = Header(default=None)):
    _require_csrf(request, _require_admin(request, x_kenkyu_session))
    return upsert_generation_conditions(
        scope_type=req.scope_type,
        scope_key=req.scope_key,
        generation_conditions=req.generation_conditions.model_dump(),
    )


@app.post("/api/projects/{project_id}/layout-review")
def layout_review_endpoint(project_id: str, request: Request, req: LayoutReviewRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return save_layout_review_records(
        project_id=project_id,
        user_id=session["user"]["id"],
        records=[row.model_dump() for row in req.records],
    )


@app.post("/api/projects/{project_id}/script-review")
def script_review_endpoint(project_id: str, request: Request, req: ScriptReviewRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return save_script_review_records(
        project_id=project_id,
        user_id=session["user"]["id"],
        records=[row.model_dump() for row in req.records],
    )


@app.post("/api/projects/{project_id}/review-assignment")
def review_assignment_endpoint(project_id: str, request: Request, req: ReviewAssignmentStartRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    _rate_limit_request(
        request,
        name="review_assignment",
        subject=session["user"]["id"],
        limit_env="LECTURE_CRAFT_REVIEW_ASSIGNMENT_RATE_LIMIT",
        window_env="LECTURE_CRAFT_REVIEW_ASSIGNMENT_RATE_WINDOW_SECONDS",
        default_limit=60,
        default_window_seconds=3600,
        message="対応付け生成の回数が多すぎます。時間を置いて再度試してください。",
    )
    return JSONResponse(
        status_code=202,
        content=get_job_manager().submit_review_assignment(
            req,
            owner_user_id=session["user"]["id"],
            owner_session_id=session["session_id"],
            project_id=project_id,
        ),
    )


@app.post("/api/projects/{project_id}/review-stages/{stage}")
def review_stage_snapshot_endpoint(
    project_id: str,
    stage: str,
    request: Request,
    req: ReviewStageConfirmRequest,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session_for_write(request, x_kenkyu_session)
    return confirm_review_stage(
        project_id=project_id,
        user_id=session["user"]["id"],
        run_id=req.run_id,
        stage=stage,
        draft_version=req.draft_version,
    )


@app.get("/api/projects/{project_id}/knowledge-graphs/latest")
def latest_knowledge_graph_endpoint(project_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    return get_latest_knowledge_graph_for_project(project_id, session["user"]["id"])


@app.post("/api/preview/audio")
def preview_audio_endpoint(request: Request, req: PreviewAudioRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    _rate_limit_request(
        request,
        name="preview_audio",
        subject=session["user"]["id"],
        limit_env="LECTURE_CRAFT_PREVIEW_AUDIO_RATE_LIMIT",
        window_env="LECTURE_CRAFT_PREVIEW_AUDIO_RATE_WINDOW_SECONDS",
        default_limit=120,
        default_window_seconds=3600,
        message="音声プレビュー生成の回数が多すぎます。時間を置いて再度試してください。",
    )
    return JSONResponse(
        status_code=202,
        content=get_job_manager().submit_preview_audio(
            req,
            owner_user_id=session["user"]["id"],
            owner_session_id=session["session_id"],
        ),
    )


@app.get("/api/preview/audio/{preview_id}/media")
def preview_audio_media_endpoint(preview_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    path = get_audio_preview_media_path(
        preview_id,
        requester_user_id=session["user"]["id"],
        requester_session_id=session["session_id"],
    )
    return FileResponse(path, media_type="audio/mpeg", filename="lecture_preview.mp3")


@app.post("/api/preview/final-render")
def preview_final_render_endpoint(request: Request, req: FinalRenderStartRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    _rate_limit_request(
        request,
        name="final_render",
        subject=session["user"]["id"],
        limit_env="LECTURE_CRAFT_FINAL_RENDER_RATE_LIMIT",
        window_env="LECTURE_CRAFT_FINAL_RENDER_RATE_WINDOW_SECONDS",
        default_limit=10,
        default_window_seconds=3600,
        message="本番確認プレビューの回数が多すぎます。時間を置いて再度試してください。",
    )
    return JSONResponse(
        status_code=202,
        content=get_job_manager().submit_final_render(
            req,
            owner_user_id=session["user"]["id"],
            owner_session_id=session["session_id"],
        ),
    )


@app.get("/api/jobs/{job_id}")
def job_status_endpoint(job_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(request, x_kenkyu_session)
    return get_job_manager().get_job(
        job_id,
        requester_user_id=session["user"]["id"],
        requester_session_id=session["session_id"],
        requester_role=session["user"].get("role") or "user",
    )


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel_endpoint(job_id: str, request: Request, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return JSONResponse(
        status_code=202,
        content=get_job_manager().cancel_job(
            job_id,
            requester_user_id=session["user"]["id"],
            requester_session_id=session["session_id"],
            requester_role=session["user"].get("role") or "user",
        ),
    )


@app.get("/api/admin/overview")
def admin_overview_endpoint(request: Request, limit: int = 12, x_kenkyu_session: str | None = Header(default=None)):
    _require_admin(request, x_kenkyu_session)
    return build_admin_overview(limit=max(1, min(limit, 50)))


@app.post("/api/research/session")
def research_session_endpoint(request: Request, req: ResearchSessionRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    return save_research_session(req, session_context=session)


@app.post("/api/research/export-jsonl")
def research_jsonl_export_endpoint(request: Request, req: ResearchJsonlExportRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session_for_write(request, x_kenkyu_session)
    if session["user"].get("role") != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "この操作は管理者のみ実行できます。")
    return export_research_jsonl(
        actor_user_id=session["user"]["id"],
        experiment_id=req.experiment_id,
        project_id=req.project_id,
        run_ids=req.run_ids,
        included_only=req.included_only,
        include_raw_text=req.include_raw_text,
        purpose=req.purpose,
    )


@app.get("/api/research/exports/{export_id}/content")
def research_jsonl_export_content_endpoint(
    export_id: str,
    request: Request,
    x_kenkyu_session: str | None = Header(default=None),
):
    _require_admin(request, x_kenkyu_session)
    return FileResponse(
        get_research_export_path(export_id),
        media_type="application/x-ndjson",
        filename=f"{export_id}.jsonl",
    )
