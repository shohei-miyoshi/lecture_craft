from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Optional


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STORAGE_ROOT = BACKEND_ROOT / "data" / "storage_v2"
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
CHUNK_SIZE = 1024 * 1024


def storage_root() -> Path:
    configured = str(os.getenv("LECTURE_CRAFT_STORAGE_ROOT") or "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_STORAGE_ROOT.resolve()


def _safe_id(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not SAFE_ID_PATTERN.fullmatch(text):
        raise ValueError(f"invalid {label}")
    return text


def _safe_extension(filename: str, media_type: Optional[str] = None) -> str:
    suffix = Path(str(filename or "")).suffix.lower()
    if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
        return suffix
    guessed = mimetypes.guess_extension(str(media_type or "").split(";", 1)[0].strip())
    return guessed if guessed and re.fullmatch(r"\.[a-z0-9]{1,10}", guessed) else ".bin"


@dataclass(frozen=True)
class StoredFile:
    artifact_id: str
    storage_key: str
    sha256: str
    size_bytes: int
    media_type: str
    original_filename: str
    path: Path


class ArtifactStore:
    """Single filesystem boundary for persistent artifacts, caches, and job workspaces."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = (root or storage_root()).resolve()
        self.artifact_root = self.root / "artifacts"
        self.cache_root = self.root / "cache"
        self.work_root = self.root / "work"

    def ensure_ready(self) -> None:
        for path in (self.artifact_root, self.cache_root, self.work_root):
            path.mkdir(parents=True, exist_ok=True)

    def work_dir(self, job_id: str) -> Path:
        job_key = _safe_id(job_id, "job_id")
        path = self.work_root / job_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def artifact_directory(self, project_id: str, run_id: Optional[str], stage: str) -> Path:
        project_key = _safe_id(project_id, "project_id")
        clean_stage = "/".join(_safe_id(part, "stage") for part in str(stage or "").split("/") if part)
        if not clean_stage:
            raise ValueError("invalid stage")
        if run_id:
            return self.artifact_root / "projects" / project_key / "runs" / _safe_id(run_id, "run_id") / clean_stage
        return self.artifact_root / "projects" / project_key / clean_stage

    def put_stream(
        self,
        stream: BinaryIO,
        *,
        project_id: str,
        run_id: Optional[str],
        stage: str,
        original_filename: str,
        media_type: Optional[str] = None,
        artifact_id: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> StoredFile:
        self.ensure_ready()
        artifact_key = _safe_id(artifact_id or f"artifact_{uuid.uuid4().hex}", "artifact_id")
        resolved_media_type = str(media_type or mimetypes.guess_type(original_filename)[0] or "application/octet-stream")
        extension = _safe_extension(original_filename, resolved_media_type)
        destination_dir = self.artifact_directory(project_id, run_id, stage)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{artifact_key}{extension}"
        staging_dir = self.work_root / "_staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging = staging_dir / f"{artifact_key}.{uuid.uuid4().hex}.tmp"

        digest = hashlib.sha256()
        size = 0
        try:
            with staging.open("wb") as output:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise ValueError("file is too large")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(staging, destination)
        finally:
            staging.unlink(missing_ok=True)

        return StoredFile(
            artifact_id=artifact_key,
            storage_key=str(destination.relative_to(self.root)),
            sha256=digest.hexdigest(),
            size_bytes=size,
            media_type=resolved_media_type,
            original_filename=Path(original_filename or f"{artifact_key}{extension}").name,
            path=destination,
        )

    def put_file(
        self,
        source: Path,
        *,
        project_id: str,
        run_id: Optional[str],
        stage: str,
        original_filename: Optional[str] = None,
        media_type: Optional[str] = None,
        artifact_id: Optional[str] = None,
    ) -> StoredFile:
        source_path = Path(source)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(source_path)
        with source_path.open("rb") as stream:
            return self.put_stream(
                stream,
                project_id=project_id,
                run_id=run_id,
                stage=stage,
                original_filename=original_filename or source_path.name,
                media_type=media_type,
                artifact_id=artifact_id,
            )

    def put_admin_export(
        self,
        stream: BinaryIO,
        *,
        export_id: str,
        original_filename: str,
        media_type: str,
    ) -> StoredFile:
        self.ensure_ready()
        export_key = _safe_id(export_id, "export_id")
        extension = _safe_extension(original_filename, media_type)
        destination_dir = self.artifact_root / "admin" / "research_exports"
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"{export_key}{extension}"
        staging = self.work_root / "_staging" / f"{export_key}.{uuid.uuid4().hex}.tmp"
        staging.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with staging.open("wb") as output:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    size += len(chunk)
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.replace(staging, destination)
        finally:
            staging.unlink(missing_ok=True)
        return StoredFile(
            artifact_id=export_key,
            storage_key=str(destination.relative_to(self.root)),
            sha256=digest.hexdigest(),
            size_bytes=size,
            media_type=media_type,
            original_filename=Path(original_filename).name,
            path=destination,
        )

    def resolve(self, storage_key: str) -> Path:
        key = Path(str(storage_key or ""))
        if key.is_absolute() or ".." in key.parts:
            raise ValueError("invalid storage_key")
        path = (self.root / key).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("invalid storage_key") from exc
        return path

    def tts_cache_path(self, cache_key: str) -> Path:
        key = _safe_id(cache_key, "cache_key")
        path = self.cache_root / "tts" / key[:2] / f"{key}.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def disk_status(self) -> dict:
        self.ensure_ready()
        usage = shutil.disk_usage(self.root)
        used_ratio = usage.used / usage.total if usage.total else 0.0
        warning_ratio = _ratio_env("LECTURE_CRAFT_STORAGE_WARNING_RATIO", 0.80)
        stop_ratio = _ratio_env("LECTURE_CRAFT_STORAGE_STOP_RATIO", 0.90)
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "used_ratio": round(used_ratio, 6),
            "warning": used_ratio >= warning_ratio,
            "generation_blocked": used_ratio >= stop_ratio,
            "warning_ratio": warning_ratio,
            "stop_ratio": stop_ratio,
        }

    def iter_files(self) -> Iterator[Path]:
        self.ensure_ready()
        yield from (path for path in self.artifact_root.rglob("*") if path.is_file())


def _ratio_env(name: str, default: float) -> float:
    try:
        return min(0.99, max(0.01, float(os.getenv(name, str(default)))))
    except Exception:
        return default


_STORE: Optional[ArtifactStore] = None


def get_artifact_store() -> ArtifactStore:
    global _STORE
    if _STORE is None or _STORE.root != storage_root():
        _STORE = ArtifactStore()
    return _STORE
