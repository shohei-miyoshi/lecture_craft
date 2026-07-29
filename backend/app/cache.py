from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .models import GenerateRequest
from .storage import get_artifact_store


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
    material_root: Path
    generation_run_id: Optional[str] = None
    cache_enabled: bool = True


def sha256_hexdigest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_generate_cache_plan(req: GenerateRequest, pdf_bytes: bytes) -> GenerateCachePlan:
    pdf_hash = sha256_hexdigest(pdf_bytes)
    if not req.generation_run_id or not req.generation_job_id:
        raise ValueError("generation_run_id and generation_job_id are required")
    store = get_artifact_store()
    work_root = store.work_dir(req.generation_job_id)
    material_root = work_root / "material"
    output_dir = work_root / "pipeline"
    request_key = sha256_hexdigest(
        json.dumps(
            {
                "v": PIPELINE_VERSION,
                "run_id": req.generation_run_id,
                "pdf_hash": pdf_hash,
                "mode": req.mode,
                "detail": req.detail,
                "difficulty": req.difficulty,
                "generation_conditions": req.generation_conditions or {},
            },
            sort_keys=True,
        ).encode("utf-8")
    )[:24]
    return GenerateCachePlan(
        pdf_hash=pdf_hash,
        request_key=request_key,
        material_name=f"{req.generation_run_id}.pdf",
        output_root_name=str(output_dir),
        response_cache_path=output_dir / "api_response.json",
        audio_shared_cache_dir=work_root / "audio_shared",
        material_root=material_root,
        generation_run_id=req.generation_run_id,
        cache_enabled=False,
    )


def load_cached_generate_response(plan: GenerateCachePlan) -> Optional[Dict[str, Any]]:
    if not plan.cache_enabled:
        return None
    if not plan.response_cache_path.exists():
        return None
    try:
        data = json.loads(plan.response_cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_cached_generate_response(plan: GenerateCachePlan, response: Dict[str, Any]) -> None:
    if not plan.cache_enabled:
        return
    plan.response_cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = plan.response_cache_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(plan.response_cache_path)


def get_named_lock(name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _NAMED_LOCKS.get(name)
        if lock is None:
            lock = threading.Lock()
            _NAMED_LOCKS[name] = lock
        return lock
