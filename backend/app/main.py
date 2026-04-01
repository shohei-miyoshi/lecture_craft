from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .jobs import get_job_manager
from .models import ExportRequest, GenerateRequest
from .service import ApiError, export_media


app = FastAPI(title="Kenkyu Backend API")
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
        "service": "kenkyu-backend-api",
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
    get_job_manager()


@app.post("/api/generate")
def generate_endpoint(req: GenerateRequest):
    return JSONResponse(status_code=202, content=get_job_manager().submit_generate(req))


@app.get("/api/jobs/{job_id}")
def job_status_endpoint(job_id: str):
    return get_job_manager().get_job(job_id)


@app.post("/api/export")
def export_endpoint(req: ExportRequest):
    return export_media(req)
