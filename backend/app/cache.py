from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .models import GenerateRequest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "outputs"
API_CACHE_ROOT = OUTPUT_ROOT / "api_cache"
API_JOB_ROOT = OUTPUT_ROOT / "api_jobs"
AUDIO_SHARED_CACHE_ROOT = OUTPUT_ROOT / "shared_audio"
PIPELINE_VERSION = "20260401_async_jobs_v1"

_LOCKS_GUARD = threading.Lock()
_NAMED_LOCKS: Dict[str, threading.Lock] = {}


@dataclass(frozen=True)
class GenerateCachePlan:
    pdf_hash: str
    request_key: str
    material_name: str
    output_root_name: str
    response_cache_path: Path
    audio_shared_cache_dir: Path


def decode_pdf_base64(pdf_b64: str) -> bytes:
    try:
        return base64.b64decode(pdf_b64)
    except Exception as exc:
        raise ValueError("pdf_base64 could not be decoded") from exc


def sha256_hexdigest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_generate_cache_plan(req: GenerateRequest, pdf_bytes: bytes) -> GenerateCachePlan:
    pdf_hash = sha256_hexdigest(pdf_bytes)
    safe_stem = _safe_stem(Path(req.filename).stem or "lecture")
    material_name = f"{safe_stem}_{pdf_hash[:16]}.pdf"

    fingerprint = {
        "v": PIPELINE_VERSION,
        "pdf_hash": pdf_hash,
        "mode": req.mode,
        "detail": req.detail,
        "difficulty": req.difficulty,
    }
    request_key = sha256_hexdigest(json.dumps(fingerprint, sort_keys=True).encode("utf-8"))[:24]

    output_root_name = (
        f"api_cache/generate/{req.mode}/"
        f"{Path(material_name).stem}_{req.detail}_{req.difficulty}_{request_key[:8]}"
    )
    response_cache_path = OUTPUT_ROOT / output_root_name / "api_response.json"
    audio_shared_cache_dir = AUDIO_SHARED_CACHE_ROOT / Path(material_name).stem

    return GenerateCachePlan(
        pdf_hash=pdf_hash,
        request_key=request_key,
        material_name=material_name,
        output_root_name=output_root_name,
        response_cache_path=response_cache_path,
        audio_shared_cache_dir=audio_shared_cache_dir,
    )


def load_cached_generate_response(plan: GenerateCachePlan) -> Optional[Dict[str, Any]]:
    if not plan.response_cache_path.exists():
        return None
    try:
        data = json.loads(plan.response_cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_cached_generate_response(plan: GenerateCachePlan, response: Dict[str, Any]) -> None:
    plan.response_cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = plan.response_cache_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(plan.response_cache_path)


def job_snapshot_path(job_id: str) -> Path:
    API_JOB_ROOT.mkdir(parents=True, exist_ok=True)
    return API_JOB_ROOT / f"{job_id}.json"


def get_named_lock(name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _NAMED_LOCKS.get(name)
        if lock is None:
            lock = threading.Lock()
            _NAMED_LOCKS[name] = lock
        return lock


def _safe_stem(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z._ぁ-んァ-ヶ一-龠-]+", "_", text).strip("_") or "lecture"
