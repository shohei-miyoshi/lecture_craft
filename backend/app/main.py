from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .admin import build_admin_overview
from .db import init_db
from .jobs import get_job_manager
from .kg_preview_service import (
    get_kg_preview_result,
    list_kg_preview_results,
    list_kg_variants,
    render_kg_preview,
    render_kg_preview_compare,
)
from .models import (
    AuthCredentialsRequest,
    ExperimentJoinRequest,
    ExportRequest,
    GenerateRequest,
    KgPreviewCompareRequest,
    KgPreviewRequest,
    LayoutReviewRequest,
    ProjectEventsRequest,
    ProjectPatchRequest,
    ProjectUpsertRequest,
    ResearchSessionRequest,
    ReviewSettingsPatchRequest,
    ScriptCompareGenerateRequest,
    ScriptReviewRequest,
    SourcePdfUploadRequest,
    WorkspaceDraftRequest,
)
from .script_compare_service import (
    get_script_compare_result,
    list_script_compare_results,
    render_script_compare,
)
from .persistence import (
    create_guest_session,
    delete_workspace_draft_for_user,
    delete_project_for_user,
    get_project_for_user,
    get_project_review_state,
    get_review_settings,
    get_session_context,
    get_workspace_draft_for_user,
    join_experiment,
    login_user,
    list_projects_for_user,
    logout_session,
    register_user,
    save_layout_review_records,
    save_project_events,
    save_project_for_user,
    save_script_review_records,
    save_workspace_draft_for_user,
    upsert_review_settings,
)
from .cache import decode_pdf_base64
from .service import (
    ApiError,
    export_media,
    export_preview_audio_source,
    fetch_source_pdf,
    render_preview_audio,
    save_research_session,
    store_source_pdf,
)


app = FastAPI(title="LectureCraft Backend API")
PROJECT_ROOT = Path(__file__).resolve().parents[1]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.on_event("startup")
def startup_event() -> None:
    init_db()
    get_job_manager()


def _require_session(x_kenkyu_session: str | None) -> dict:
    return get_session_context(x_kenkyu_session or "")


def _require_admin(x_kenkyu_session: str | None) -> dict:
    session = _require_session(x_kenkyu_session)
    if session["user"].get("role") != "admin":
        raise ApiError(403, "ADMIN_REQUIRED", "この操作は管理者のみ実行できます。")
    return session


@app.post("/api/auth/register")
def auth_register_endpoint(req: AuthCredentialsRequest):
    return register_user(req.username, req.password)


@app.post("/api/auth/login")
def auth_login_endpoint(req: AuthCredentialsRequest):
    return login_user(req.username, req.password)


@app.post("/api/auth/logout")
def auth_logout_endpoint(x_kenkyu_session: str | None = Header(default=None)):
    return logout_session(x_kenkyu_session or "")


@app.get("/api/auth/me")
def auth_me_endpoint(x_kenkyu_session: str | None = Header(default=None)):
    return _require_session(x_kenkyu_session)


@app.post("/api/auth/guest")
def guest_session_endpoint():
    return create_guest_session()


@app.post("/api/experiments/join")
def experiment_join_endpoint(req: ExperimentJoinRequest, x_kenkyu_session: str | None = Header(default=None)):
    _require_session(x_kenkyu_session)
    return join_experiment(session_token=x_kenkyu_session or "", invite_code=req.invite_code)


@app.get("/api/projects")
def projects_list_endpoint(x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return {"projects": list_projects_for_user(session["user"]["id"])}


@app.post("/api/projects")
def project_create_endpoint(req: ProjectUpsertRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    project_id = req.client_project_id or f"project_{uuid.uuid4().hex[:12]}"
    return save_project_for_user(
        user_id=session["user"]["id"],
        experiment_id=session.get("experiment_id"),
        project_id=project_id,
        name=req.name,
        data=req.data,
    )


@app.get("/api/projects/{project_id}")
def project_get_endpoint(project_id: str, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return get_project_for_user(project_id, session["user"]["id"])


@app.patch("/api/projects/{project_id}")
def project_patch_endpoint(project_id: str, req: ProjectPatchRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    current = get_project_for_user(project_id, session["user"]["id"])
    next_name = req.name or current["name"]
    next_data = req.data if req.data is not None else current["data"]
    return save_project_for_user(
        user_id=session["user"]["id"],
        experiment_id=session.get("experiment_id"),
        project_id=project_id,
        name=next_name,
        data=next_data,
    )


@app.delete("/api/projects/{project_id}")
def project_delete_endpoint(project_id: str, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    delete_project_for_user(project_id, session["user"]["id"])
    return {"ok": True, "project_id": project_id}


@app.get("/api/workspace")
def workspace_get_endpoint(x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return {"draft": get_workspace_draft_for_user(session["user"]["id"])}


@app.put("/api/workspace")
def workspace_put_endpoint(req: WorkspaceDraftRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return save_workspace_draft_for_user(
        user_id=session["user"]["id"],
        session_id=session["session_id"],
        workspace_id=req.workspace_id,
        revision=req.revision,
        data=req.data,
    )


@app.delete("/api/workspace")
def workspace_delete_endpoint(
    x_kenkyu_session: str | None = Header(default=None),
    x_workspace_id: str | None = Header(default=None),
    x_workspace_revision: str | None = Header(default=None),
):
    session = _require_session(x_kenkyu_session)
    try:
        revision = int(x_workspace_revision) if x_workspace_revision is not None else None
    except Exception:
        revision = None
    return delete_workspace_draft_for_user(
        session["user"]["id"],
        session_id=session["session_id"],
        workspace_id=x_workspace_id,
        revision=revision,
    )


@app.post("/api/source-pdfs")
def source_pdf_upload_endpoint(req: SourcePdfUploadRequest, x_kenkyu_session: str | None = Header(default=None)):
    _require_session(x_kenkyu_session)
    try:
        pdf_bytes = decode_pdf_base64(req.pdf_base64)
    except ValueError as exc:
        raise ApiError(400, "INVALID_PDF", str(exc)) from exc
    return {"ok": True, "pdf_ref": store_source_pdf(req.filename, pdf_bytes)}


@app.get("/api/source-pdfs/{material_name}")
def source_pdf_get_endpoint(material_name: str, filename: str | None = None, x_kenkyu_session: str | None = Header(default=None)):
    _require_session(x_kenkyu_session)
    return fetch_source_pdf(material_name, filename=filename)


@app.post("/api/projects/{project_id}/events")
def project_events_endpoint(project_id: str, req: ProjectEventsRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return save_project_events(
        project_id=project_id,
        user_id=session["user"]["id"],
        events=[row.model_dump() for row in req.events],
    )


@app.get("/api/admin/review-settings")
def review_settings_get_endpoint(x_kenkyu_session: str | None = Header(default=None)):
    _require_admin(x_kenkyu_session)
    return get_review_settings()


@app.patch("/api/admin/review-settings")
def review_settings_patch_endpoint(req: ReviewSettingsPatchRequest, x_kenkyu_session: str | None = Header(default=None)):
    _require_admin(x_kenkyu_session)
    return upsert_review_settings(
        scope_type=req.scope_type,
        scope_key=req.scope_key,
        layout_review_mode=req.layout_review_mode,
        script_review_mode=req.script_review_mode,
    )


@app.post("/api/projects/{project_id}/layout-review")
def layout_review_endpoint(project_id: str, req: LayoutReviewRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return save_layout_review_records(
        project_id=project_id,
        user_id=session["user"]["id"],
        records=[row.model_dump() for row in req.records],
    )


@app.post("/api/projects/{project_id}/script-review")
def script_review_endpoint(project_id: str, req: ScriptReviewRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return save_script_review_records(
        project_id=project_id,
        user_id=session["user"]["id"],
        records=[row.model_dump() for row in req.records],
    )


@app.get("/api/projects/{project_id}/review-state")
def review_state_endpoint(project_id: str, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    return get_project_review_state(project_id, session["user"]["id"])


@app.post("/api/generate")
def generate_endpoint(req: GenerateRequest):
    return JSONResponse(status_code=202, content=get_job_manager().submit_generate(req))


@app.post("/api/kg-preview")
def kg_preview_endpoint(req: KgPreviewRequest):
    return render_kg_preview(req)


@app.get("/api/kg-preview/variants")
def kg_preview_variants_endpoint():
    return list_kg_variants()


@app.post("/api/kg-preview/compare")
def kg_preview_compare_endpoint(req: KgPreviewCompareRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    if req.project_id:
        get_project_for_user(req.project_id, session["user"]["id"])
    return render_kg_preview_compare(req, owner_user_id=session["user"]["id"])


@app.post("/api/script-compare/generate")
def script_compare_generate_endpoint(req: ScriptCompareGenerateRequest, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    project = get_project_for_user(req.project_id, session["user"]["id"])
    return render_script_compare(
        project_id=req.project_id,
        project_data=project.get("data") or {},
        kg_result_id=req.kg_result_id,
        mode=req.mode,
        detail=req.detail,
        difficulty=req.difficulty,
        owner_user_id=session["user"]["id"],
    )


@app.get("/api/script-compare/results")
def script_compare_results_endpoint(
    project_id: str,
    limit: int = 24,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session(x_kenkyu_session)
    get_project_for_user(project_id, session["user"]["id"])
    return list_script_compare_results(
        user_id=session["user"]["id"],
        project_id=project_id,
        limit=limit,
    )


@app.get("/api/script-compare/results/{compare_id}")
def script_compare_result_endpoint(
    compare_id: str,
    project_id: str,
    x_kenkyu_session: str | None = Header(default=None),
):
    session = _require_session(x_kenkyu_session)
    get_project_for_user(project_id, session["user"]["id"])
    return get_script_compare_result(
        compare_id,
        user_id=session["user"]["id"],
        project_id=project_id,
    )


@app.get("/api/kg-preview/results")
def kg_preview_results_endpoint(
    x_kenkyu_session: str | None = Header(default=None),
    project_id: str | None = None,
    filename: str | None = None,
    material_fingerprint: str | None = None,
    variant_id: str | None = None,
    limit: int = 24,
):
    session = _require_session(x_kenkyu_session)
    if project_id:
        get_project_for_user(project_id, session["user"]["id"])
    return list_kg_preview_results(
        user_id=session["user"]["id"],
        project_id=project_id,
        filename=filename,
        material_fingerprint=material_fingerprint,
        variant_id=variant_id,
        limit=limit,
    )


@app.get("/api/kg-preview/results/{result_id}")
def kg_preview_result_endpoint(result_id: str, project_id: str | None = None, x_kenkyu_session: str | None = Header(default=None)):
    session = _require_session(x_kenkyu_session)
    if project_id:
        get_project_for_user(project_id, session["user"]["id"])
    return get_kg_preview_result(result_id, user_id=session["user"]["id"], project_id=project_id)


@app.get("/api/jobs/{job_id}")
def job_status_endpoint(job_id: str):
    return get_job_manager().get_job(job_id)


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel_endpoint(job_id: str):
    return JSONResponse(status_code=202, content=get_job_manager().cancel_job(job_id))


@app.get("/api/admin/overview")
def admin_overview_endpoint(limit: int = 12, x_kenkyu_session: str | None = Header(default=None)):
    _require_admin(x_kenkyu_session)
    return build_admin_overview(limit=max(1, min(limit, 50)))


@app.post("/api/research/session")
def research_session_endpoint(req: ResearchSessionRequest):
    return save_research_session(req)


@app.post("/api/export")
def export_endpoint(req: ExportRequest):
    return export_media(req)


@app.post("/api/preview-audio/render")
def preview_audio_render_endpoint(req: ExportRequest):
    return render_preview_audio(req)


@app.get("/api/preview-audio/source")
def preview_audio_source_endpoint(output_root_name: str, material_name: str):
    return export_preview_audio_source(output_root_name=output_root_name, material_name=material_name)
