from __future__ import annotations

import base64
import json
import logging
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
from typing import Any, Dict, Optional

from .cache import (
    build_generate_cache_plan,
)
from .db import db_conn, json_text
from .models import (
    ExportRequest,
    FinalRenderStartRequest,
    GenerateRequest,
    PreviewAudioRequest,
    ReviewAssignmentRequest,
    ReviewAssignmentStartRequest,
)
from .service import (
    ApiError,
    build_audio_preview,
    create_final_render_preview,
    generate_media,
    generate_review_assignment,
    preview_audio_request_key,
)
from .storage import get_artifact_store
from .storage_persistence import (
    apply_review_assignment_result,
    apply_generated_result,
    assert_generation_run_current,
    attach_job_to_run,
    assert_final_render_context_current,
    assert_review_assignment_context_current,
    create_final_render_input_revision,
    generation_run_input,
    get_final_render_context,
    get_review_assignment_context,
    publish_final_render_result,
    publish_failed_job_workspace,
    publish_generation_workspace,
    publish_review_assignment_workspace,
    confirm_review_stage,
)

LOGGER = logging.getLogger(__name__)


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


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(str(os.getenv(name, str(default))).strip()))
    except Exception:
        return max(minimum, default)


def _strip_binary_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_binary_payload(item)
            for key, item in value.items()
            if str(key).lower() not in {"pdf_base64", "image_base64", "upload_base64", "data_url"}
        }
    if isinstance(value, list):
        return [_strip_binary_payload(item) for item in value]
    return value


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
    partial_result: Optional[Dict[str, Any]] = None
    cancel_requested: bool = False
    cancelled_at: Optional[str] = None
    owner_user_id: Optional[str] = None
    owner_session_id: Optional[str] = None
    dedup_key: Optional[str] = None
    project_id: Optional[str] = None
    generation_run_id: Optional[str] = None
    result_artifact_id: Optional[str] = None
    retry_count: int = 0
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[str] = None
    request_payload: Dict[str, Any] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)


class JobManager:
    def __init__(self, worker_count: int = 1) -> None:
        self.worker_count = max(1, worker_count)
        self.worker_instance_id = f"worker_{uuid.uuid4().hex}"
        self.jobs: Dict[str, JobRecord] = {}
        self._jobs_lock = threading.Lock()
        self._queue: Queue[tuple[str, str, Dict[str, Any]]] = Queue()
        self._started = False
        self._start_lock = threading.Lock()

    def _active_job_count(self, *, owner_user_id: str, kind: str) -> int:
        return sum(
            1
            for job in self.jobs.values()
            if job.owner_user_id == owner_user_id and job.kind == kind and job.status in {"queued", "running"}
        )

    def _enforce_user_job_limit(self, *, owner_user_id: str, kind: str, limit_env: str, default_limit: int) -> None:
        limit = _int_env(limit_env, default_limit, minimum=0)
        if limit <= 0:
            return
        if self._active_job_count(owner_user_id=owner_user_id, kind=kind) >= limit:
            raise ApiError(
                429,
                "TOO_MANY_ACTIVE_JOBS",
                "同時に実行できる生成処理の上限に達しています。完了を待ってから再度実行してください。",
            )

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._restore_pending_project_runs()
            for idx in range(self.worker_count):
                thread = threading.Thread(
                    target=self._worker_loop,
                    args=(idx,),
                    daemon=True,
                    name=f"lecture-craft-job-worker-{idx}",
                )
                thread.start()
            self._started = True

    def submit_project_run(
        self,
        *,
        run_id: str,
        project_id: str,
        source_artifact_id: str,
        owner_user_id: str,
        owner_session_id: str,
        experiment_id: Optional[str],
        mode: str,
        detail: str,
        difficulty: str,
        layout_review_enabled: bool,
        script_review_enabled: bool,
        generation_conditions: Dict[str, Any],
        correction_memories: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        self._enforce_user_job_limit(
            owner_user_id=owner_user_id,
            kind="generate",
            limit_env="LECTURE_CRAFT_ACTIVE_GENERATE_JOB_LIMIT",
            default_limit=2,
        )
        now = _now_iso()
        request_payload = {
            "run_id": run_id,
            "project_id": project_id,
            "source_artifact_id": source_artifact_id,
            "experiment_id": experiment_id,
            "mode": mode,
            "detail": detail,
            "difficulty": difficulty,
            "layout_review_enabled": layout_review_enabled,
            "script_review_enabled": script_review_enabled,
            "generation_conditions": generation_conditions,
            "correction_memories": correction_memories,
        }
        record = JobRecord(
            job_id=f"job_{uuid.uuid4().hex}",
            kind="project_run",
            status="queued",
            progress=0,
            message="生成runをキューに追加しました",
            created_at=now,
            updated_at=now,
            owner_user_id=owner_user_id,
            owner_session_id=owner_session_id,
            project_id=project_id,
            generation_run_id=run_id,
            request_payload=request_payload,
            payload={
                "project_id": project_id,
                "run_id": run_id,
                "mode": mode,
                "detail": detail,
                "difficulty": difficulty,
                "experiment_id": experiment_id,
            },
        )
        with self._jobs_lock:
            self.jobs[record.job_id] = record
            try:
                self._persist_job(record, strict=True)
            except Exception as exc:
                self.jobs.pop(record.job_id, None)
                raise ApiError(503, "JOB_PERSISTENCE_FAILED", "ジョブをDBへ保存できなかったため，生成を開始しませんでした。") from exc
        try:
            attach_job_to_run(run_id, record.job_id)
        except Exception as exc:
            record.status = "failed"
            record.progress = 100
            record.message = "生成runとjobを関連付けられませんでした"
            record.error = {"code": "RUN_JOB_LINK_FAILED", "message": str(exc)}
            self._persist_job(record, strict=True)
            raise ApiError(503, "RUN_JOB_LINK_FAILED", "生成runとjobを関連付けられなかったため，生成を開始しませんでした。") from exc
        self._queue.put((record.job_id, "project_run", request_payload))
        return self._public_job_payload(record.job_id)

    def submit_final_render(
        self,
        req: FinalRenderStartRequest,
        *,
        owner_user_id: str,
        owner_session_id: str,
    ) -> Dict[str, Any]:
        input_revision_id = None
        if req.type == "video":
            revision = create_final_render_input_revision(
                project_id=req.project_id,
                user_id=owner_user_id,
                run_id=req.run_id,
                draft_version=req.draft_version,
            )
            input_revision_id = revision["id"]
        context = get_final_render_context(
            project_id=req.project_id,
            user_id=owner_user_id,
            run_id=req.run_id,
            render_type=req.type,
            input_revision_id=input_revision_id,
        )
        queued_payload = {
            **req.model_dump(),
            "input_revision_id": context["input_revision_id"],
        }
        now = _now_iso()
        record = JobRecord(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            kind="final_render",
            status="queued",
            progress=0,
            message="本番確認プレビューをキューに追加しました",
            created_at=now,
            updated_at=now,
            owner_user_id=owner_user_id,
            owner_session_id=owner_session_id,
            project_id=req.project_id,
            generation_run_id=req.run_id,
            request_payload=queued_payload,
            payload={
                "type": req.type,
                "mode": context["mode"],
                "project_id": req.project_id,
                "run_id": req.run_id,
                "input_revision_id": context["input_revision_id"],
                "slide_count": len(context["state"].get("slides") or []),
                "sentence_count": len(context["state"].get("sentences") or []),
                "highlight_count": len(context["state"].get("highlights") or []),
            },
        )
        with self._jobs_lock:
            self._enforce_user_job_limit(
                owner_user_id=owner_user_id,
                kind="final_render",
                limit_env="LECTURE_CRAFT_ACTIVE_FINAL_RENDER_JOB_LIMIT",
                default_limit=1,
            )
            self.jobs[record.job_id] = record
            try:
                self._persist_job(record, strict=True)
            except Exception as exc:
                self.jobs.pop(record.job_id, None)
                raise ApiError(503, "JOB_PERSISTENCE_FAILED", "ジョブをDBへ保存できなかったため，生成を開始しませんでした。") from exc
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
        self._queue.put((record.job_id, "final_render", queued_payload))
        return payload

    def submit_preview_audio(
        self,
        req: PreviewAudioRequest,
        *,
        owner_user_id: str,
        owner_session_id: str,
    ) -> Dict[str, Any]:
        if not req.project_id or not req.run_id:
            raise ApiError(
                400,
                "PREVIEW_PROJECT_CONTEXT_INVALID",
                "音声プレビューにはproject_idとrun_idが必要です。",
            )
        request_key = preview_audio_request_key(req)
        existing_job_id: Optional[str] = None
        with self._jobs_lock:
            existing = next(
                (
                    record
                    for record in reversed(list(self.jobs.values()))
                    if record.kind == "preview_audio"
                    and record.owner_user_id == owner_user_id
                    and record.project_id == req.project_id
                    and record.generation_run_id == req.run_id
                    and record.request_key == request_key
                    and record.status in {"queued", "running", "completed"}
                ),
                None,
            )
            if existing is None:
                try:
                    with db_conn() as conn:
                        row = conn.execute(
                            """
                            SELECT id FROM jobs
                            WHERE kind = 'preview_audio'
                              AND owner_user_id = :owner_user_id
                              AND project_id = :project_id
                              AND generation_run_id = :run_id
                              AND request_key = :request_key
                              AND status IN ('queued', 'running', 'completed')
                              AND (
                                status != 'completed'
                                OR EXISTS (
                                  SELECT 1 FROM artifacts
                                  WHERE artifacts.id = jobs.result_artifact_id
                                    AND artifacts.status = 'active'
                                )
                              )
                            ORDER BY created_at DESC LIMIT 1
                            """,
                            {
                                "owner_user_id": owner_user_id,
                                "project_id": req.project_id,
                                "run_id": req.run_id,
                                "request_key": request_key,
                            },
                        ).fetchone()
                    if row is not None:
                        existing = self._restore_job_from_snapshot(str(row["id"]))
                except Exception:
                    LOGGER.exception("Failed to search for a reusable preview audio job")
            if existing is not None and existing.status == "completed":
                with db_conn() as conn:
                    active_result = conn.execute(
                        """
                        SELECT id FROM artifacts
                        WHERE id = :artifact_id AND status = 'active'
                        """,
                        {"artifact_id": existing.result_artifact_id},
                    ).fetchone()
                if active_result is None:
                    existing = None
            if existing is not None:
                existing.deduplicated = True
                existing_job_id = existing.job_id

            if existing_job_id is None:
                self._enforce_user_job_limit(
                    owner_user_id=owner_user_id,
                    kind="preview_audio",
                    limit_env="LECTURE_CRAFT_ACTIVE_PREVIEW_AUDIO_JOB_LIMIT",
                    default_limit=2,
                )
                now = _now_iso()
                record = JobRecord(
                    job_id=f"job_{uuid.uuid4().hex[:12]}",
                    kind="preview_audio",
                    status="queued",
                    progress=0,
                    message="音声プレビューをキューに追加しました",
                    created_at=now,
                    updated_at=now,
                    request_key=request_key,
                    owner_user_id=owner_user_id,
                    owner_session_id=owner_session_id,
                    project_id=req.project_id,
                    generation_run_id=req.run_id,
                    request_payload=req.model_dump(),
                    payload={
                        "project_id": req.project_id,
                        "run_id": req.run_id,
                        "scope": req.scope,
                        "sentence_count": len(req.sentences),
                    },
                )
                self.jobs[record.job_id] = record
                try:
                    self._persist_job(record, strict=True)
                except Exception as exc:
                    self.jobs.pop(record.job_id, None)
                    raise ApiError(
                        503,
                        "JOB_PERSISTENCE_FAILED",
                        "ジョブをDBへ保存できなかったため，音声生成を開始しませんでした。",
                    ) from exc
        if existing_job_id is not None:
            return self._public_job_payload(existing_job_id)
        self._queue.put((record.job_id, "preview_audio", record.request_payload))
        return self._public_job_payload(record.job_id)

    def submit_review_assignment(
        self,
        req: ReviewAssignmentStartRequest,
        *,
        owner_user_id: str,
        owner_session_id: str,
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not project_id:
            raise ApiError(400, "PROJECT_REQUIRED", "対応付け生成にはプロジェクトIDが必要です。")
        context = get_review_assignment_context(
            project_id=project_id,
            user_id=owner_user_id,
            run_id=req.run_id,
        )
        now = _now_iso()
        record = JobRecord(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            kind="review_assignment",
            status="queued",
            progress=0,
            message="対応付け生成をキューに追加しました",
            created_at=now,
            updated_at=now,
            owner_user_id=owner_user_id,
            owner_session_id=owner_session_id,
            project_id=project_id,
            generation_run_id=req.run_id,
            request_payload={"project_id": project_id, "run_id": req.run_id},
            payload={
                "project_id": project_id,
                "run_id": req.run_id,
                "slide_count": len(context["slide_artifacts"]),
                "sentence_count": len(context["sentences"]),
                "highlight_count": len(context["highlights"]),
                "layout_revision_id": context["layout_revision_id"],
                "script_revision_id": context["script_revision_id"],
            },
        )
        with self._jobs_lock:
            self._enforce_user_job_limit(
                owner_user_id=owner_user_id,
                kind="review_assignment",
                limit_env="LECTURE_CRAFT_ACTIVE_REVIEW_ASSIGNMENT_JOB_LIMIT",
                default_limit=2,
            )
            self.jobs[record.job_id] = record
            try:
                self._persist_job(record, strict=True)
            except Exception as exc:
                self.jobs.pop(record.job_id, None)
                raise ApiError(503, "JOB_PERSISTENCE_FAILED", "ジョブをDBへ保存できなかったため，生成を開始しませんでした。") from exc
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
        self._queue.put((record.job_id, "review_assignment", record.request_payload))
        return payload

    def get_job(
        self,
        job_id: str,
        *,
        requester_user_id: str,
        requester_session_id: str,
        requester_role: str,
    ) -> Dict[str, Any]:
        with self._jobs_lock:
            record = self.jobs.get(job_id)
            if record is None:
                record = self._restore_job_from_snapshot(job_id)
            if record is None:
                raise ApiError(404, "JOB_NOT_FOUND", f"job not found: {job_id}")
            self._assert_job_access(
                record,
                requester_user_id=requester_user_id,
                requester_session_id=requester_session_id,
                requester_role=requester_role,
            )
        return self._public_job_payload(job_id)

    def cancel_job(
        self,
        job_id: str,
        *,
        requester_user_id: str,
        requester_session_id: str,
        requester_role: str,
    ) -> Dict[str, Any]:
        with self._jobs_lock:
            record = self.jobs.get(job_id)
            if record is None:
                record = self._restore_job_from_snapshot(job_id)
            if record is None:
                raise ApiError(404, "JOB_NOT_FOUND", f"job not found: {job_id}")
            self._assert_job_access(
                record,
                requester_user_id=requester_user_id,
                requester_session_id=requester_session_id,
                requester_role=requester_role,
            )
            if record.status in {"completed", "failed", "cancelled"}:
                return self._public_job_payload(job_id)
            record.cancel_requested = True
            record.message = "生成停止をリクエストしました"
            record.updated_at = _now_iso()
        self._persist_job(record)
        return self._public_job_payload(job_id)

    def _worker_loop(self, _: int) -> None:
        while True:
            job_id, kind, req_payload = self._queue.get()
            try:
                if not self._claim_job(job_id):
                    continue
                self._raise_if_cancel_requested(job_id)
                if kind == "final_render":
                    self._run_final_render_job(job_id, req_payload)
                elif kind == "preview_audio":
                    self._run_preview_audio_job(job_id, req_payload)
                elif kind == "review_assignment":
                    self._run_review_assignment_job(job_id, req_payload)
                elif kind == "project_run":
                    self._run_project_run_job(job_id, req_payload)
                else:
                    raise ApiError(400, "UNSUPPORTED_JOB_KIND", f"未対応のジョブ種別です: {kind}")
            except JobCancelledError:
                self._mark_cancelled(job_id)
            except ApiError as exc:
                self._finalize_failed_workspace(job_id, exc.message)
                self._update_job(
                    job_id,
                    status="failed",
                    progress=100,
                    message=exc.message,
                    error={"code": exc.code, "message": exc.message},
                )
            except Exception as exc:
                self._finalize_failed_workspace(job_id, str(exc))
                self._update_job(
                    job_id,
                    status="failed",
                    progress=100,
                    message="生成中に予期しないエラーが発生しました",
                    error={"code": "GENERATION_FAILED", "message": str(exc)},
                )
            finally:
                self._queue.task_done()

    def _claim_job(self, job_id: str) -> bool:
        now = _now_iso()
        lease_expires_at = (
            datetime.now() + timedelta(seconds=_int_env("LECTURE_CRAFT_JOB_LEASE_SECONDS", 7200, minimum=300))
        ).isoformat(timespec="seconds")
        with db_conn() as conn:
            result = conn.execute(
                """
                UPDATE jobs
                SET status = 'running', lease_owner = :lease_owner,
                    lease_expires_at = :lease_expires_at, heartbeat_at = :heartbeat_at,
                    started_at = COALESCE(started_at, :started_at), updated_at = :updated_at
                WHERE id = :job_id AND status = 'queued'
                  AND (
                    lease_owner IS NULL OR lease_owner = :lease_owner
                    OR lease_expires_at IS NULL OR lease_expires_at < :now
                  )
                """,
                {
                    "job_id": job_id,
                    "lease_owner": self.worker_instance_id,
                    "lease_expires_at": lease_expires_at,
                    "heartbeat_at": now,
                    "started_at": now,
                    "updated_at": now,
                    "now": now,
                },
            )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            return False
        with self._jobs_lock:
            record = self.jobs.get(job_id)
            if record is not None:
                record.status = "running"
                record.lease_owner = self.worker_instance_id
                record.lease_expires_at = lease_expires_at
                record.updated_at = now
        return True

    def _finalize_failed_workspace(self, job_id: str, error: str) -> None:
        with self._jobs_lock:
            record = self.jobs.get(job_id)
        if record is None or not record.project_id:
            return
        try:
            publish_failed_job_workspace(
                project_id=record.project_id,
                run_id=record.generation_run_id,
                user_id=record.owner_user_id,
                job_id=job_id,
                error=error,
            )
        except Exception:
            LOGGER.exception("Failed to publish debug artifacts for job %s", job_id)
        finally:
            shutil.rmtree(get_artifact_store().work_dir(job_id), ignore_errors=True)

    def _run_project_run_job(self, job_id: str, req_payload: Dict[str, Any]) -> Optional[str]:
        run_id = str(req_payload.get("run_id") or "")
        project_id = str(req_payload.get("project_id") or "")
        source = generation_run_input(run_id)
        if source["project_id"] != project_id:
            raise ApiError(409, "RUN_PROJECT_MISMATCH", "生成runとプロジェクトが一致しません。")
        pdf_bytes = Path(source["source_path"]).read_bytes()
        req = GenerateRequest(
            filename=source["filename"],
            detail=req_payload.get("detail") or source["detail"],
            difficulty=req_payload.get("difficulty") or source["difficulty"],
            mode=req_payload.get("mode") or source["mode"],
            request_token=f"run:{run_id}",
            client_project_id=project_id,
            interactive_review_enabled=True,
            layout_review_enabled=bool(req_payload.get("layout_review_enabled")),
            script_review_enabled=bool(req_payload.get("script_review_enabled")),
            generation_conditions=req_payload.get("generation_conditions") or source["conditions"],
            generation_run_id=run_id,
            generation_job_id=job_id,
            correction_memories=req_payload.get("correction_memories") or [],
        )
        plan = build_generate_cache_plan(req, pdf_bytes)
        self._update_job(
            job_id,
            status="running",
            progress=5,
            message="生成runを開始しました",
            request_key=plan.request_key,
        )
        self._raise_if_cancel_requested(job_id)
        result = generate_media(
            req,
            pdf_bytes=pdf_bytes,
            progress_callback=lambda progress, message: self._report_progress(job_id, progress, message),
            partial_callback=lambda stage, partial: self._report_partial_result(job_id, stage, partial),
        )
        self._raise_if_cancel_requested(job_id)
        assert_generation_run_current(
            run_id=run_id,
            project_id=project_id,
            user_id=source["user_id"],
        )
        published = publish_generation_workspace(
            run_id=run_id,
            job_id=job_id,
            project_id=project_id,
            user_id=source["user_id"],
            workspace=get_artifact_store().work_dir(job_id),
            result=result,
        )
        committed = apply_generated_result(
            project_id=project_id,
            user_id=source["user_id"],
            run_id=run_id,
            result=published["result"],
        )
        stages = ()
        if req.mode == "hl" and not req.layout_review_enabled and not req.script_review_enabled:
            stages = ("layout", "script", "assignment")
        elif req.mode != "hl" and not req.script_review_enabled:
            stages = ("script",)
        if stages:
            for stage in stages:
                confirm_review_stage(
                    project_id=project_id,
                    user_id=source["user_id"],
                    run_id=run_id,
                    stage=stage,
                    draft_version=committed["draft_version"],
                )
        final_result = {
            **published["result"],
            "draft_version": committed["draft_version"],
            "generation_revision_id": committed["revision"]["id"],
        }
        result_artifact_id = published["result_artifact"]["id"]
        self._update_job(
            job_id,
            status="completed",
            progress=100,
            message="生成runが完了しました",
            result_path=f"artifact:{result_artifact_id}",
            cache_hit=False,
        )
        with self._jobs_lock:
            record = self.jobs[job_id]
            record.result_artifact_id = result_artifact_id
            record.partial_result = None
            record.payload = {
                **record.payload,
                "draft_version": committed["draft_version"],
                "generation_revision_id": committed["revision"]["id"],
            }
            record.updated_at = _now_iso()
        self._persist_job(record)
        shutil.rmtree(get_artifact_store().work_dir(job_id), ignore_errors=True)
        return plan.request_key

    def _run_final_render_job(self, job_id: str, req_payload: Dict[str, Any]) -> None:
        start_req = FinalRenderStartRequest.model_validate(req_payload)
        input_revision_id = str(req_payload.get("input_revision_id") or "") or None
        with self._jobs_lock:
            record = self.jobs[job_id]
            owner_user_id = str(record.owner_user_id or "")
        context = get_final_render_context(
            project_id=start_req.project_id,
            user_id=owner_user_id,
            run_id=start_req.run_id,
            render_type=start_req.type,
            input_revision_id=input_revision_id,
        )
        state = context["state"]
        slides = []
        for idx, slide in enumerate(state.get("slides") or []):
            artifact = context["slide_artifacts"][idx]
            slides.append({
                **slide,
                "image_base64": base64.b64encode(Path(artifact["path"]).read_bytes()).decode("ascii"),
            })
        highlights = []
        for highlight in state.get("highlights") or []:
            sentence_ids = highlight.get("sentence_ids") or ([highlight.get("sid")] if highlight.get("sid") else [])
            for sentence_id in sentence_ids:
                highlights.append({**highlight, "sid": sentence_id})
        req = ExportRequest(
            type=start_req.type,
            mode=context["mode"],
            slides=slides,
            sentences=state.get("sentences") or [],
            highlights=highlights,
            generation_ref={
                "run_id": context["run_id"],
                "input_revision_id": context["input_revision_id"],
            },
            settings={
                "detail": context["detail"],
                "difficulty": context["difficulty"],
            },
        )
        workspace = get_artifact_store().work_dir(job_id)
        self._update_job(
            job_id,
            status="running",
            progress=8,
            message="本番確認プレビューを生成しています",
        )
        self._raise_if_cancel_requested(job_id)
        result = create_final_render_preview(req, job_id=job_id, workspace=workspace)
        self._raise_if_cancel_requested(job_id)
        assert_final_render_context_current(context)
        published = publish_final_render_result(
            context=context,
            job_id=job_id,
            media_path=Path(result["media_path"]),
            render_type=start_req.type,
        )
        result_artifact_id = published["result_artifact"]["id"]
        self._update_job(
            job_id,
            status="completed",
            progress=100,
            message="本番確認プレビューが完了しました",
            result_path=f"artifact:{result_artifact_id}",
        )
        with self._jobs_lock:
            record = self.jobs[job_id]
            record.result_artifact_id = result_artifact_id
            record.payload = {
                **record.payload,
                "media_artifact_id": published["media_artifact"]["id"],
                "render_revision_id": published["revision"]["id"],
            }
            record.updated_at = _now_iso()
        self._persist_job(record)
        shutil.rmtree(workspace, ignore_errors=True)

    def _run_preview_audio_job(self, job_id: str, req_payload: Dict[str, Any]) -> None:
        req = PreviewAudioRequest.model_validate(req_payload)
        with self._jobs_lock:
            record = self.jobs[job_id]
            owner_user_id = str(record.owner_user_id or "")
            owner_session_id = record.owner_session_id
        self._update_job(
            job_id,
            status="running",
            progress=10,
            message="確認済み台本の音声を準備しています",
        )
        self._raise_if_cancel_requested(job_id)
        result = build_audio_preview(
            req,
            owner_user_id=owner_user_id,
            owner_session_id=owner_session_id,
            job_id=job_id,
        )
        self._raise_if_cancel_requested(job_id)
        result_artifact_id = str(result.get("audio_manifest_artifact_id") or "")
        if not result_artifact_id:
            raise ApiError(500, "PREVIEW_AUDIO_MANIFEST_MISSING", "音声プレビューの保存結果が不完全です。")
        with self._jobs_lock:
            record = self.jobs[job_id]
            record.result_artifact_id = result_artifact_id
            record.payload = {
                **record.payload,
                "audio_artifact_id": result.get("audio_artifact_id"),
                "sentence_cache_hits": result.get("sentence_cache_hits", 0),
            }
            record.updated_at = _now_iso()
        self._update_job(
            job_id,
            status="completed",
            progress=100,
            message="音声付きプレビューを準備しました",
            result_path=f"artifact:{result_artifact_id}",
            cache_hit=bool(result.get("cache_hit")),
        )

    def _run_review_assignment_job(self, job_id: str, req_payload: Dict[str, Any]) -> None:
        project_id = str(req_payload.get("project_id") or "")
        run_id = str(req_payload.get("run_id") or "")
        with self._jobs_lock:
            record = self.jobs[job_id]
            owner_user_id = str(record.owner_user_id or "")
        context = get_review_assignment_context(
            project_id=project_id,
            user_id=owner_user_id,
            run_id=run_id,
        )
        assert_review_assignment_context_current(context)
        workspace = get_artifact_store().work_dir(job_id)
        material_name = f"{run_id}.pdf"
        material_root = workspace / "material"
        slide_root = material_root / "img" / material_name
        slide_root.mkdir(parents=True, exist_ok=True)
        for idx, artifact in enumerate(context["slide_artifacts"], start=1):
            source_path = Path(artifact["path"])
            suffix = source_path.suffix.lower() if source_path.suffix else ".png"
            shutil.copy2(source_path, slide_root / f"slide_{idx:03d}{suffix}")
        req = ReviewAssignmentRequest(
            slides=context["slides"],
            sentences=context["sentences"],
            highlights=context["highlights"],
            generation_ref={
                "run_id": run_id,
                "material_name": material_name,
                "layout_revision_id": context["layout_revision_id"],
                "script_revision_id": context["script_revision_id"],
            },
            settings={
                "detail": context["detail"],
                "difficulty": context["difficulty"],
            },
        )
        self._update_job(
            job_id,
            status="running",
            progress=10,
            message="確認済みの領域と台本で対応付けを生成しています",
        )
        self._raise_if_cancel_requested(job_id)
        result = generate_review_assignment(req, workspace=workspace)
        self._raise_if_cancel_requested(job_id)
        assert_review_assignment_context_current(context)
        published = publish_review_assignment_workspace(
            context=context,
            job_id=job_id,
            workspace=workspace,
            result=result,
        )
        committed = apply_review_assignment_result(
            context=context,
            result=published["result"],
            result_artifact_id=published["result_artifact"]["id"],
        )
        result_artifact_id = published["result_artifact"]["id"]
        self._update_job(
            job_id,
            status="completed",
            progress=100,
            message="対応付け生成が完了しました",
            result_path=f"artifact:{result_artifact_id}",
        )
        with self._jobs_lock:
            record = self.jobs[job_id]
            record.result_artifact_id = result_artifact_id
            record.payload = {
                **record.payload,
                "draft_version": committed["draft_version"],
                "revision_id": committed["revision"]["id"],
            }
            record.updated_at = _now_iso()
        self._persist_job(record)
        shutil.rmtree(workspace, ignore_errors=True)

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
        if status is not None:
            self._sync_generation_run_status(job_id, status)

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
            partial_result = record.partial_result
            result_path = record.result_path
            error = record.error
            record_payload = dict(record.payload)

        if error:
            payload["error"] = error
        if partial_result:
            payload["partial_result"] = partial_result
        if record.status == "completed" and result_path:
            try:
                result = self._load_job_result(job_id, result_path)
                if record_payload.get("draft_version") is not None:
                    result = {**result, "draft_version": record_payload["draft_version"]}
                if record_payload.get("generation_revision_id"):
                    result = {
                        **result,
                        "generation_revision_id": record_payload["generation_revision_id"],
                    }
                if record_payload.get("revision_id"):
                    result = {**result, "revision_id": record_payload["revision_id"]}
                payload["result"] = result
            except Exception as exc:
                payload["status"] = "failed"
                payload["message"] = "生成結果ファイルを読み込めませんでした"
                payload["error"] = {"code": "JOB_RESULT_MISSING", "message": str(exc)}
        return payload

    def _restore_job_from_snapshot(self, job_id: str) -> Optional[JobRecord]:
        payload = self._load_job_snapshot_payload(job_id)
        if not isinstance(payload, dict):
            return None
        status = str(payload.get("status") or "failed")
        message = str(payload.get("message") or "")
        progress = int(payload.get("progress") or 0)
        error = payload.get("error") if isinstance(payload.get("error"), dict) else None
        record = JobRecord(
            job_id=str(payload.get("job_id") or job_id),
            kind=str(payload.get("kind") or "generate"),
            status=status,
            progress=progress,
            message=message,
            created_at=str(payload.get("created_at") or _now_iso()),
            updated_at=str(payload.get("updated_at") or _now_iso()),
            request_key=payload.get("request_key"),
            result_path=payload.get("result_path"),
            error=error,
            cache_hit=bool(payload.get("cache_hit")),
            deduplicated=bool(payload.get("deduplicated")),
            partial_result=payload.get("partial_result") if isinstance(payload.get("partial_result"), dict) else None,
            cancel_requested=bool(payload.get("cancel_requested")),
            cancelled_at=payload.get("cancelled_at"),
            owner_user_id=payload.get("owner_user_id"),
            owner_session_id=payload.get("owner_session_id"),
            dedup_key=payload.get("dedup_key"),
            project_id=payload.get("project_id"),
            generation_run_id=payload.get("generation_run_id"),
            result_artifact_id=payload.get("result_artifact_id"),
            retry_count=int(payload.get("retry_count") or 0),
            lease_owner=payload.get("lease_owner"),
            lease_expires_at=payload.get("lease_expires_at"),
            request_payload=payload.get("request_payload") if isinstance(payload.get("request_payload"), dict) else {},
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        )
        self.jobs[record.job_id] = record
        return record

    def _load_job_snapshot_payload(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            with db_conn() as conn:
                row = conn.execute(
                    """
                    SELECT *
                    FROM jobs
                    WHERE id = :job_id
                    LIMIT 1
                    """,
                    {"job_id": job_id},
                ).fetchone()
            if row is None:
                return None
            return {
                "job_id": row["id"],
                "kind": row["kind"],
                "status": row["status"],
                "progress": row["progress"],
                "message": row["message"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "request_key": row["request_key"],
                "result_path": f"artifact:{row['result_artifact_id']}" if row["result_artifact_id"] else None,
                "result_artifact_id": row["result_artifact_id"],
                "error": json.loads(row["error_json"]) if row["error_json"] else None,
                "partial_result": json.loads(row["partial_result_json"]) if row["partial_result_json"] else None,
                "cancel_requested": bool(row["cancel_requested"]),
                "retry_count": int(row["retry_count"] or 0),
                "lease_owner": row["lease_owner"],
                "lease_expires_at": row["lease_expires_at"],
                "owner_user_id": row["owner_user_id"],
                "owner_session_id": row["owner_session_id"],
                "project_id": row["project_id"],
                "generation_run_id": row["generation_run_id"],
                "request_payload": json.loads(row["request_json"] or "{}"),
                "payload": json.loads(row["request_json"] or "{}"),
            }
        except Exception:
            return None

    def _load_job_result(self, job_id: str, result_path: str) -> Dict[str, Any]:
        if not str(result_path).startswith("artifact:"):
            raise FileNotFoundError("legacy job result paths are no longer supported")
        artifact_id = str(result_path).split(":", 1)[1]
        with db_conn() as conn:
            row = conn.execute(
                "SELECT storage_key FROM artifacts WHERE id = :artifact_id",
                {"artifact_id": artifact_id},
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"artifact not found: {artifact_id}")
        data = json.loads(get_artifact_store().resolve(row["storage_key"]).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            generation_ref = data.get("generation_ref")
            if isinstance(generation_ref, dict):
                data = {**data, "generation_ref": {**generation_ref, "job_id": job_id}}
            return data
        raise ValueError("artifact result is not an object")

    def _persist_job(self, record: JobRecord, *, strict: bool = False) -> None:
        payload = self._job_snapshot_payload(record)
        self._persist_job_snapshot_db(payload, strict=strict)

    def _job_snapshot_payload(self, record: JobRecord) -> Dict[str, Any]:
        return {
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
            "partial_result": record.partial_result,
            "cancel_requested": record.cancel_requested,
            "cancelled_at": record.cancelled_at,
            "owner_user_id": record.owner_user_id,
            "owner_session_id": record.owner_session_id,
            "dedup_key": record.dedup_key,
            "project_id": record.project_id,
            "generation_run_id": record.generation_run_id,
            "result_artifact_id": record.result_artifact_id,
            "retry_count": record.retry_count,
            "lease_owner": record.lease_owner,
            "lease_expires_at": record.lease_expires_at,
            "request_payload": record.request_payload,
            "payload": record.payload,
        }

    def _persist_job_snapshot_db(self, payload: Dict[str, Any], *, strict: bool = False) -> None:
        try:
            with db_conn() as conn:
                owner_user_id = payload.get("owner_user_id")
                if owner_user_id:
                    user_row = conn.execute(
                        "SELECT id FROM users WHERE id = :user_id",
                        {"user_id": owner_user_id},
                    ).fetchone()
                    if user_row is None:
                        owner_user_id = None
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, kind, status, progress, message, owner_user_id, owner_session_id,
                        project_id, generation_run_id, request_key, request_json,
                        result_artifact_id, error_json, partial_result_json,
                        cancel_requested, retry_count, lease_owner, lease_expires_at,
                        created_at, updated_at,
                        started_at, finished_at, heartbeat_at
                    )
                    VALUES (
                        :job_id, :kind, :status, :progress, :message, :owner_user_id, :owner_session_id,
                        :project_id, :generation_run_id, :request_key, :request_json,
                        :result_artifact_id, :error_json, :partial_result_json,
                        :cancel_requested, :retry_count, :lease_owner, :lease_expires_at,
                        :created_at, :updated_at,
                        :started_at, :finished_at, :heartbeat_at
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        kind = excluded.kind,
                        status = excluded.status,
                        progress = excluded.progress,
                        message = excluded.message,
                        owner_user_id = excluded.owner_user_id,
                        owner_session_id = excluded.owner_session_id,
                        project_id = excluded.project_id,
                        generation_run_id = excluded.generation_run_id,
                        request_key = excluded.request_key,
                        request_json = excluded.request_json,
                        result_artifact_id = excluded.result_artifact_id,
                        error_json = excluded.error_json,
                        partial_result_json = excluded.partial_result_json,
                        cancel_requested = excluded.cancel_requested,
                        retry_count = excluded.retry_count,
                        lease_owner = excluded.lease_owner,
                        lease_expires_at = excluded.lease_expires_at,
                        updated_at = excluded.updated_at,
                        heartbeat_at = excluded.heartbeat_at,
                        started_at = COALESCE(jobs.started_at, excluded.started_at),
                        finished_at = excluded.finished_at
                    """,
                    {
                        "job_id": payload.get("job_id"),
                        "kind": payload.get("kind") or "unknown",
                        "status": payload.get("status") or "unknown",
                        "progress": int(payload.get("progress") or 0),
                        "message": payload.get("message") or "",
                        "created_at": payload.get("created_at") or _now_iso(),
                        "updated_at": payload.get("updated_at") or _now_iso(),
                        "owner_user_id": owner_user_id,
                        "owner_session_id": payload.get("owner_session_id"),
                        "project_id": payload.get("project_id"),
                        "generation_run_id": payload.get("generation_run_id"),
                        "request_key": payload.get("request_key"),
                        "request_json": json_text(
                            _strip_binary_payload(payload.get("request_payload") or payload.get("payload") or {})
                        ),
                        "result_artifact_id": payload.get("result_artifact_id"),
                        "error_json": json_text(payload["error"]) if payload.get("error") else None,
                        "partial_result_json": (
                            json_text(_strip_binary_payload(payload["partial_result"]))
                            if payload.get("partial_result")
                            else None
                        ),
                        "cancel_requested": int(bool(payload.get("cancel_requested"))),
                        "retry_count": int(payload.get("retry_count") or 0),
                        "lease_owner": (
                            (payload.get("lease_owner") or self.worker_instance_id)
                            if payload.get("status") == "running"
                            else payload.get("lease_owner") if payload.get("status") == "queued"
                            else None
                        ),
                        "lease_expires_at": (
                            (
                                datetime.now()
                                + timedelta(seconds=_int_env("LECTURE_CRAFT_JOB_LEASE_SECONDS", 7200, minimum=300))
                            ).isoformat(timespec="seconds")
                            if payload.get("status") == "running"
                            and (payload.get("lease_owner") in {None, self.worker_instance_id})
                            else payload.get("lease_expires_at") if payload.get("status") == "running"
                            else payload.get("lease_expires_at") if payload.get("status") == "queued"
                            else None
                        ),
                        "started_at": payload.get("updated_at") if payload.get("status") == "running" else None,
                        "finished_at": payload.get("updated_at") if payload.get("status") in {"completed", "failed", "cancelled"} else None,
                        "heartbeat_at": payload.get("updated_at") if payload.get("status") == "running" else None,
                    },
                )
        except Exception:
            LOGGER.exception("Failed to persist job %s", payload.get("job_id"))
            if strict:
                raise

    def _restore_pending_project_runs(self) -> None:
        now = _now_iso()
        try:
            with db_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE kind IN ('project_run', 'review_assignment', 'preview_audio', 'final_render')
                      AND (
                        (
                          status = 'queued'
                          AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at < :now)
                        )
                        OR (
                          status = 'running'
                          AND (lease_expires_at IS NULL OR lease_expires_at < :now)
                        )
                      )
                    ORDER BY created_at
                    """,
                    {"now": now},
                ).fetchall()
        except Exception:
            return
        max_retries = _int_env("LECTURE_CRAFT_JOB_MAX_RETRIES", 2, minimum=0)
        for row in rows:
            lease_expires_at = (
                datetime.now() + timedelta(seconds=_int_env("LECTURE_CRAFT_JOB_LEASE_SECONDS", 7200, minimum=300))
            ).isoformat(timespec="seconds")
            with db_conn() as conn:
                claimed = conn.execute(
                    """
                    UPDATE jobs
                    SET status = 'queued', lease_owner = :lease_owner,
                        lease_expires_at = :lease_expires_at, updated_at = :updated_at
                    WHERE id = :job_id
                      AND (
                        (
                          status = 'queued'
                          AND (lease_owner IS NULL OR lease_expires_at IS NULL OR lease_expires_at < :now)
                        )
                        OR (
                          status = 'running'
                          AND (lease_expires_at IS NULL OR lease_expires_at < :now)
                        )
                      )
                    """,
                    {
                        "job_id": row["id"],
                        "lease_owner": self.worker_instance_id,
                        "lease_expires_at": lease_expires_at,
                        "updated_at": now,
                        "now": now,
                    },
                )
            if int(getattr(claimed, "rowcount", 0) or 0) != 1:
                continue
            request_payload = json.loads(row["request_json"] or "{}")
            retry_count = int(row["retry_count"] or 0) + (1 if row["status"] == "running" else 0)
            if row["status"] == "running" and row["project_id"]:
                try:
                    publish_failed_job_workspace(
                        project_id=row["project_id"],
                        run_id=row["generation_run_id"],
                        user_id=row["owner_user_id"],
                        job_id=row["id"],
                        error="Backend restarted while this job was running; retrying from a clean workspace.",
                    )
                except Exception:
                    LOGGER.exception("Failed to preserve interrupted workspace for job %s", row["id"])
            shutil.rmtree(get_artifact_store().work_dir(row["id"]), ignore_errors=True)
            record = JobRecord(
                job_id=row["id"],
                kind=row["kind"],
                status="queued",
                progress=0,
                message="バックエンド再起動後にjobを再開します",
                created_at=row["created_at"],
                updated_at=_now_iso(),
                request_key=row["request_key"],
                error=None,
                cancel_requested=bool(row["cancel_requested"]),
                owner_user_id=row["owner_user_id"],
                owner_session_id=row["owner_session_id"],
                project_id=row["project_id"],
                generation_run_id=row["generation_run_id"],
                result_artifact_id=row["result_artifact_id"],
                retry_count=retry_count,
                lease_owner=self.worker_instance_id,
                lease_expires_at=lease_expires_at,
                request_payload=request_payload,
                payload=dict(request_payload),
            )
            self.jobs[record.job_id] = record
            if record.cancel_requested:
                self._mark_cancelled(record.job_id)
                continue
            if retry_count > max_retries:
                record.status = "failed"
                record.progress = 100
                record.message = "バックエンド再起動後の再試行上限を超えました"
                record.error = {
                    "code": "JOB_RETRY_EXHAUSTED",
                    "message": "自動再試行上限を超えました。管理者が状態を確認してください。",
                }
                record.updated_at = _now_iso()
                self._persist_job(record)
                continue
            self._persist_job(record)
            self._queue.put((record.job_id, record.kind, request_payload))

    def _job_snapshot_payload_for_db(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_payload = dict(payload)
        partial = db_payload.get("partial_result")
        if isinstance(partial, dict):
            data = partial.get("data") if isinstance(partial.get("data"), dict) else {}
            db_payload["partial_result"] = {
                "stage": partial.get("stage"),
                "ready_at": partial.get("ready_at"),
                "data_summary": {
                    "slide_count": len(data.get("slides") or []),
                    "sentence_count": len(data.get("sentences") or []),
                    "highlight_count": len(data.get("highlights") or []),
                    "mode": data.get("mode"),
                    "partial_stage": data.get("partial_stage"),
                },
            }
        return db_payload

    def _sync_generation_run_status(self, job_id: str, status: str) -> None:
        try:
            with db_conn() as conn:
                conn.execute(
                    """
                    UPDATE generation_runs
                    SET status = :status, updated_at = :updated_at
                    WHERE job_id = :job_id
                    """,
                    {
                        "status": status,
                        "updated_at": _now_iso(),
                        "job_id": job_id,
                    },
                )
        except Exception:
            pass

    def _is_cancel_requested(self, job_id: str) -> bool:
        with self._jobs_lock:
            record = self.jobs[job_id]
            if record.cancel_requested or record.status == "cancelled":
                return True
        try:
            with db_conn() as conn:
                row = conn.execute(
                    "SELECT cancel_requested, status FROM jobs WHERE id = :job_id",
                    {"job_id": job_id},
                ).fetchone()
        except Exception:
            return False
        cancelled = bool(row and (row["cancel_requested"] or row["status"] == "cancelled"))
        if cancelled:
            with self._jobs_lock:
                record = self.jobs.get(job_id)
                if record is not None:
                    record.cancel_requested = True
        return cancelled

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

    def _report_partial_result(self, job_id: str, stage: str, partial: Dict[str, Any]) -> None:
        self._raise_if_cancel_requested(job_id)
        with self._jobs_lock:
            record = self.jobs[job_id]
            record.partial_result = {
                "stage": stage,
                "ready_at": _now_iso(),
                "data": partial,
            }
            record.updated_at = _now_iso()
        self._persist_job(record)
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
        shutil.rmtree(get_artifact_store().work_dir(job_id), ignore_errors=True)

    def _assert_job_access(
        self,
        record: JobRecord,
        *,
        requester_user_id: str,
        requester_session_id: str,
        requester_role: str,
    ) -> None:
        if requester_role == "admin":
            return
        if record.owner_user_id and record.owner_user_id == requester_user_id:
            return
        if record.owner_session_id and record.owner_session_id == requester_session_id:
            return
        raise ApiError(403, "JOB_FORBIDDEN", "この生成ジョブにアクセスする権限がありません。")


_JOB_MANAGER: Optional[JobManager] = None
_JOB_MANAGER_LOCK = threading.Lock()


def get_job_manager() -> JobManager:
    global _JOB_MANAGER
    with _JOB_MANAGER_LOCK:
        if _JOB_MANAGER is None:
            _JOB_MANAGER = JobManager(worker_count=_job_worker_count())
            _JOB_MANAGER.start()
        return _JOB_MANAGER
