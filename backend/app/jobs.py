from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Any, Dict, Optional

from .cache import (
    build_generate_cache_plan,
    decode_pdf_base64,
    get_named_lock,
    job_snapshot_path,
)
from .models import GenerateRequest
from .service import ApiError, generate_media


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _job_worker_count() -> int:
    try:
        return max(
            1,
            int(os.getenv("LECTURE_CRAFT_JOB_WORKERS", os.getenv("KENKYU_JOB_WORKERS", "1"))),
        )
    except Exception:
        return 1


class JobCancelledError(Exception):
    pass


@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    request_key: Optional[str] = None
    result_path: Optional[str] = None
    error: Optional[Dict[str, str]] = None
    cache_hit: bool = False
    deduplicated: bool = False
    cancel_requested: bool = False
    cancelled_at: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)


class JobManager:
    def __init__(self, worker_count: int = 1) -> None:
        self.worker_count = max(1, worker_count)
        self.jobs: Dict[str, JobRecord] = {}
        self._jobs_lock = threading.Lock()
        self._active_generate_jobs: Dict[str, str] = {}
        self._queue: Queue[tuple[str, Dict[str, Any]]] = Queue()
        self._started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            for idx in range(self.worker_count):
                thread = threading.Thread(
                    target=self._worker_loop,
                    args=(idx,),
                    daemon=True,
                    name=f"lecture-craft-job-worker-{idx}",
                )
                thread.start()
            self._started = True

    def submit_generate(self, req: GenerateRequest) -> Dict[str, Any]:
        req = self._ensure_request_token(req)
        try:
            pdf_bytes = decode_pdf_base64(req.pdf_base64)
        except ValueError as exc:
            raise ApiError(400, "INVALID_PDF", str(exc)) from exc

        plan = build_generate_cache_plan(req, pdf_bytes)

        with self._jobs_lock:
            existing_job_id = self._active_generate_jobs.get(plan.request_key)
            if existing_job_id:
                existing = self.jobs.get(existing_job_id)
                if existing and existing.status in {"queued", "running"}:
                    existing.deduplicated = True
                    self._persist_job(existing)
                    payload = {
                        "job_id": existing.job_id,
                        "kind": existing.kind,
                        "status": existing.status,
                        "progress": existing.progress,
                        "message": existing.message,
                        "created_at": existing.created_at,
                        "updated_at": existing.updated_at,
                        "cache_hit": existing.cache_hit,
                        "deduplicated": existing.deduplicated,
                        "payload": existing.payload,
                    }
                    return payload

            now = _now_iso()
            record = JobRecord(
                job_id=f"job_{uuid.uuid4().hex[:12]}",
                kind="generate",
                status="queued",
                progress=0,
                message="生成ジョブをキューに追加しました",
                created_at=now,
                updated_at=now,
                request_key=plan.request_key,
                payload={
                    "mode": req.mode,
                    "detail": req.detail,
                    "difficulty": req.difficulty,
                    "filename": req.filename,
                },
            )
            self.jobs[record.job_id] = record
            self._active_generate_jobs[plan.request_key] = record.job_id
            self._persist_job(record)
            payload = {
                "job_id": record.job_id,
                "kind": record.kind,
                "status": record.status,
                "progress": record.progress,
                "message": record.message,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "cache_hit": record.cache_hit,
                "deduplicated": record.deduplicated,
                "payload": record.payload,
            }
        self._queue.put((record.job_id, req.model_dump()))
        return payload

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self._jobs_lock:
            if job_id not in self.jobs:
                raise ApiError(404, "JOB_NOT_FOUND", f"job not found: {job_id}")
        return self._public_job_payload(job_id)

    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        with self._jobs_lock:
            record = self.jobs.get(job_id)
            if record is None:
                raise ApiError(404, "JOB_NOT_FOUND", f"job not found: {job_id}")
            if record.status in {"completed", "failed", "cancelled"}:
                return self._public_job_payload(job_id)
            record.cancel_requested = True
            record.message = "生成停止をリクエストしました"
            record.updated_at = _now_iso()
        self._persist_job(record)
        return self._public_job_payload(job_id)

    def _worker_loop(self, _: int) -> None:
        while True:
            job_id, req_payload = self._queue.get()
            request_key: Optional[str] = None
            try:
                self._raise_if_cancel_requested(job_id)
                req = GenerateRequest.model_validate(req_payload)
                try:
                    pdf_bytes = decode_pdf_base64(req.pdf_base64)
                except ValueError as exc:
                    raise ApiError(400, "INVALID_PDF", str(exc)) from exc

                plan = build_generate_cache_plan(req, pdf_bytes)
                request_key = plan.request_key
                self._update_job(
                    job_id,
                    status="running",
                    progress=5,
                    message="生成ジョブを開始しました",
                    request_key=request_key,
                )
                self._raise_if_cancel_requested(job_id)

                result = generate_media(
                    req,
                    progress_callback=lambda progress, message: self._report_progress(job_id, progress, message),
                )
                self._raise_if_cancel_requested(job_id)

                self._update_job(
                    job_id,
                    status="completed",
                    progress=100,
                    message="生成が完了しました",
                    result_path=str(plan.response_cache_path),
                    cache_hit=bool(result.get("generation_ref", {}).get("cache_hit", False)),
                )
            except JobCancelledError:
                self._mark_cancelled(job_id)
            except ApiError as exc:
                self._update_job(
                    job_id,
                    status="failed",
                    progress=100,
                    message=exc.message,
                    error={"code": exc.code, "message": exc.message},
                )
            except Exception as exc:
                self._update_job(
                    job_id,
                    status="failed",
                    progress=100,
                    message="生成中に予期しないエラーが発生しました",
                    error={"code": "GENERATION_FAILED", "message": str(exc)},
                )
            finally:
                if request_key:
                    with self._jobs_lock:
                        if self._active_generate_jobs.get(request_key) == job_id:
                            self._active_generate_jobs.pop(request_key, None)
                self._queue.task_done()

    def _create_job(
        self,
        *,
        kind: str,
        status: str,
        progress: int,
        message: str,
        request_key: Optional[str] = None,
        result_path: Optional[str] = None,
        error: Optional[Dict[str, str]] = None,
        cache_hit: bool = False,
        payload: Optional[Dict[str, Any]] = None,
    ) -> JobRecord:
        now = _now_iso()
        record = JobRecord(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            kind=kind,
            status=status,
            progress=progress,
            message=message,
            created_at=now,
            updated_at=now,
            request_key=request_key,
            result_path=result_path,
            error=error,
            cache_hit=cache_hit,
            payload=dict(payload or {}),
        )
        with self._jobs_lock:
            self.jobs[record.job_id] = record
        self._persist_job(record)
        return record

    def _update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        request_key: Optional[str] = None,
        result_path: Optional[str] = None,
        error: Optional[Dict[str, str]] = None,
        cache_hit: Optional[bool] = None,
    ) -> None:
        with self._jobs_lock:
            record = self.jobs[job_id]
            if record.status == "cancelled" and status not in {None, "cancelled"}:
                return
            if status is not None:
                record.status = status
            if progress is not None:
                record.progress = int(progress)
            if message is not None:
                record.message = message
            if request_key is not None:
                record.request_key = request_key
            if result_path is not None:
                record.result_path = result_path
            if error is not None:
                record.error = error
            if cache_hit is not None:
                record.cache_hit = cache_hit
            record.updated_at = _now_iso()
        self._persist_job(record)

    def _public_job_payload(self, job_id: str) -> Dict[str, Any]:
        with self._jobs_lock:
            record = self.jobs[job_id]
            payload: Dict[str, Any] = {
                "job_id": record.job_id,
                "kind": record.kind,
                "status": record.status,
                "progress": record.progress,
                "message": record.message,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "cache_hit": record.cache_hit,
                "deduplicated": record.deduplicated,
                "cancel_requested": record.cancel_requested,
                "cancelled_at": record.cancelled_at,
                "payload": record.payload,
            }
            result_path = record.result_path
            error = record.error

        if error:
            payload["error"] = error
        if record.status == "completed" and result_path:
            payload["result"] = self._load_job_result(job_id, result_path)
        return payload

    def _load_job_result(self, job_id: str, result_path: str) -> Dict[str, Any]:
        lock = get_named_lock(f"result:{result_path}")
        with lock:
            data = json.loads(Path(result_path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            generation_ref = data.get("generation_ref")
            if isinstance(generation_ref, dict):
                data = {**data, "generation_ref": {**generation_ref, "job_id": job_id}}
        return data

    def _persist_job(self, record: JobRecord) -> None:
        path = job_snapshot_path(record.job_id)
        path.write_text(
            json.dumps(
                {
                    "job_id": record.job_id,
                    "kind": record.kind,
                    "status": record.status,
                    "progress": record.progress,
                    "message": record.message,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "request_key": record.request_key,
                    "result_path": record.result_path,
                    "error": record.error,
                    "cache_hit": record.cache_hit,
                    "deduplicated": record.deduplicated,
                    "cancel_requested": record.cancel_requested,
                    "cancelled_at": record.cancelled_at,
                    "payload": record.payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._jobs_lock:
            record = self.jobs[job_id]
            return bool(record.cancel_requested or record.status == "cancelled")

    def _raise_if_cancel_requested(self, job_id: str) -> None:
        if self._is_cancel_requested(job_id):
            raise JobCancelledError(job_id)

    def _report_progress(self, job_id: str, progress: int, message: str) -> None:
        self._raise_if_cancel_requested(job_id)
        self._update_job(
            job_id,
            status="running",
            progress=progress,
            message=message,
        )
        self._raise_if_cancel_requested(job_id)

    def _mark_cancelled(self, job_id: str) -> None:
        with self._jobs_lock:
            record = self.jobs[job_id]
            record.status = "cancelled"
            record.cancel_requested = True
            record.cancelled_at = _now_iso()
            record.message = "生成を停止しました"
            record.updated_at = record.cancelled_at
        self._persist_job(record)

    def _ensure_request_token(self, req: GenerateRequest) -> GenerateRequest:
        if req.request_token:
            return req
        return req.model_copy(update={"request_token": f"jobreq_{uuid.uuid4().hex}"})


_JOB_MANAGER: Optional[JobManager] = None
_JOB_MANAGER_LOCK = threading.Lock()


def get_job_manager() -> JobManager:
    global _JOB_MANAGER
    with _JOB_MANAGER_LOCK:
        if _JOB_MANAGER is None:
            _JOB_MANAGER = JobManager(worker_count=_job_worker_count())
            _JOB_MANAGER.start()
        return _JOB_MANAGER
