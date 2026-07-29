from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - optional dependency in local dev
    psycopg = None
    dict_row = None


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT / "data"
DEFAULT_SQLITE_PATH = DATA_ROOT / "lecture_craft_app.db"
POSTGRES_PREFIXES = ("postgresql://", "postgres://")
PARAM_PATTERN = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
SQLITE_JOURNAL_MODES = {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}
LOGGER = logging.getLogger(__name__)


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")


def db_kind() -> str:
    url = get_database_url()
    if url.startswith("sqlite:///"):
        return "sqlite"
    if url.startswith(POSTGRES_PREFIXES):
        return "postgres"
    raise RuntimeError(f"未対応の DATABASE_URL です: {url}")


def _resolve_sqlite_path(database_url: str) -> Path:
    raw = database_url.removeprefix("sqlite:///")
    path = Path(raw)
    if not path.is_absolute():
        path = (APP_ROOT / path).resolve()
    return path


def get_sqlite_path() -> Path:
    return _resolve_sqlite_path(get_database_url())


def _sqlite_journal_mode() -> str | None:
    raw = os.getenv("LECTURE_CRAFT_SQLITE_JOURNAL_MODE", "WAL").strip().upper()
    if raw in {"", "DEFAULT"}:
        return None
    if raw not in SQLITE_JOURNAL_MODES:
        raise RuntimeError(f"未対応の LECTURE_CRAFT_SQLITE_JOURNAL_MODE です: {raw}")
    return raw


def _apply_sqlite_journal_mode(conn: sqlite3.Connection) -> None:
    mode = _sqlite_journal_mode()
    if mode is None:
        return
    try:
        conn.execute(f"PRAGMA journal_mode = {mode}")
    except sqlite3.OperationalError as exc:
        if mode != "WAL":
            raise
        LOGGER.warning("SQLite WAL mode is unavailable; falling back to DELETE journal mode: %s", exc)
        conn.execute("PRAGMA journal_mode = DELETE")


def _adapt_query(query: str, dialect: str) -> str:
    if dialect == "postgres":
        return PARAM_PATTERN.sub(lambda m: f"%({m.group(1)})s", query)
    return query


class DBConnection:
    def __init__(self, raw: Any, dialect: str) -> None:
        self.raw = raw
        self.dialect = dialect

    def execute(self, query: str, params: Mapping[str, Any] | None = None):
        return self.raw.execute(_adapt_query(query, self.dialect), params or {})


def _connect_sqlite() -> DBConnection:
    db_path = get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_sqlite_journal_mode(conn)
    return DBConnection(conn, "sqlite")


def _connect_postgres() -> DBConnection:
    if psycopg is None:
        raise RuntimeError(
            "PostgreSQL を使うには backend に psycopg をインストールしてください。"
            "requirements_min.txt を更新したので、再度 setup を実行してください。"
        )
    conn = psycopg.connect(get_database_url(), row_factory=dict_row)
    return DBConnection(conn, "postgres")


def _connect() -> DBConnection:
    return _connect_sqlite() if db_kind() == "sqlite" else _connect_postgres()


@contextmanager
def db_conn() -> Iterator[DBConnection]:
    conn = _connect()
    try:
        yield conn
        conn.raw.commit()
    finally:
        conn.raw.close()


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _list_columns(conn: DBConnection, table_name: str) -> set[str]:
    if conn.dialect == "sqlite":
        rows = conn.raw.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table_name
        """,
        {"table_name": table_name},
    ).fetchall()
    return {str(row["column_name"]) for row in rows}


def _ensure_column(conn: DBConnection, table_name: str, column_name: str, definition_sql: str) -> None:
    if column_name in _list_columns(conn, table_name):
        return
    conn.raw.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}")


def init_db() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    statements = [
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            user_kind TEXT NOT NULL,
            username TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'user',
            email TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique
        ON users(username)
        """,
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_token TEXT NOT NULL UNIQUE,
            experiment_id TEXT,
            participant_label TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            last_seen_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS experiments (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            invite_code TEXT NOT NULL UNIQUE,
            description TEXT,
            generation_conditions_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS experiment_participants (
            id TEXT PRIMARY KEY,
            experiment_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            joined_at TEXT NOT NULL,
            UNIQUE (experiment_id, user_id),
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            experiment_id TEXT,
            name TEXT NOT NULL,
            latest_state_json TEXT NOT NULL,
            generation_refs_json TEXT NOT NULL DEFAULT '{}',
            review_states_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS project_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            saved_by_user_id TEXT NOT NULL,
            snapshot_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (saved_by_user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (project_id, version_number)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS edit_events (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            experiment_id TEXT,
            generation_run_id TEXT,
            external_event_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            slide_idx INTEGER,
            entity_type TEXT,
            entity_id TEXT,
            source TEXT,
            before_json TEXT,
            after_json TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL,
            UNIQUE (project_id, external_event_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS generation_runs (
            id TEXT PRIMARY KEY,
            job_id TEXT UNIQUE,
            project_id TEXT,
            user_id TEXT,
            experiment_id TEXT,
            request_key TEXT,
            pdf_hash TEXT,
            filename TEXT,
            mode TEXT NOT NULL,
            detail TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            condition_json TEXT NOT NULL DEFAULT '{}',
            prompt_strategy_version TEXT,
            status TEXT NOT NULL,
            artifact_refs_json TEXT NOT NULL DEFAULT '{}',
            result_summary_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_generation_runs_job_id
        ON generation_runs(job_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_generation_runs_experiment_id
        ON generation_runs(experiment_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS knowledge_graph_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            generation_run_id TEXT,
            job_id TEXT,
            user_id TEXT,
            experiment_id TEXT,
            kg_mode TEXT NOT NULL,
            nodes_json TEXT NOT NULL DEFAULT '[]',
            edges_json TEXT NOT NULL DEFAULT '[]',
            slide_refs_json TEXT NOT NULL DEFAULT '[]',
            region_refs_json TEXT NOT NULL DEFAULT '[]',
            sentence_refs_json TEXT NOT NULL DEFAULT '[]',
            quality_status TEXT NOT NULL DEFAULT 'auto_generated',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_kg_versions_project_id
        ON knowledge_graph_versions(project_id, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_kg_versions_job_id
        ON knowledge_graph_versions(job_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS review_stage_snapshots (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            experiment_id TEXT,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_review_stage_project_stage
        ON review_stage_snapshots(project_id, stage, updated_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS correction_memories (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            experiment_id TEXT,
            generation_run_id TEXT,
            source_event_id TEXT,
            edit_type TEXT NOT NULL,
            slide_idx INTEGER,
            entity_type TEXT,
            entity_id TEXT,
            before_json TEXT,
            after_json TEXT,
            reason TEXT,
            slide_context_json TEXT NOT NULL DEFAULT '{}',
            kg_node_ids_json TEXT NOT NULL DEFAULT '[]',
            region_ids_json TEXT NOT NULL DEFAULT '[]',
            prompt_version TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL,
            FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE SET NULL,
            UNIQUE (project_id, source_event_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_correction_memories_lookup
        ON correction_memories(experiment_id, edit_type, slide_idx)
        """,
        """
        CREATE TABLE IF NOT EXISTS review_settings (
            id TEXT PRIMARY KEY,
            scope_type TEXT NOT NULL,
            scope_key TEXT,
            layout_review_mode TEXT NOT NULL,
            script_review_mode TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (scope_type, scope_key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS layout_review_records (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            slide_idx INTEGER,
            highlight_id TEXT,
            review_source TEXT NOT NULL,
            decision TEXT NOT NULL,
            before_json TEXT,
            after_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS script_review_records (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            slide_idx INTEGER,
            sentence_id TEXT,
            review_step TEXT NOT NULL,
            before_text TEXT,
            after_text TEXT,
            changed_fields_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS research_session_snapshots (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            trigger TEXT NOT NULL,
            saved_at TEXT NOT NULL,
            actor_user_id TEXT,
            experiment_id TEXT,
            project_id TEXT,
            payload_json TEXT NOT NULL,
            FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_session_saved_at
        ON research_session_snapshots(saved_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_session_project_id
        ON research_session_snapshots(project_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS api_job_snapshots (
            job_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            owner_user_id TEXT,
            payload_json TEXT NOT NULL,
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_api_job_snapshots_updated_at
        ON api_job_snapshots(updated_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS export_event_snapshots (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            export_type TEXT NOT NULL,
            actor_user_id TEXT,
            experiment_id TEXT,
            payload_json TEXT NOT NULL,
            FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_export_event_created_at
        ON export_event_snapshots(created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS research_export_snapshots (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            actor_user_id TEXT,
            experiment_id TEXT,
            status TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            options_json TEXT NOT NULL DEFAULT '{}',
            output_path TEXT,
            payload_json TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_research_export_created_at
        ON research_export_snapshots(created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS project_drafts (
            project_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL DEFAULT 1,
            state_json TEXT NOT NULL DEFAULT '{}',
            updated_by_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS project_revisions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            generation_run_id TEXT,
            revision_number INTEGER NOT NULL,
            revision_kind TEXT NOT NULL,
            parent_revision_id TEXT,
            draft_version INTEGER NOT NULL,
            state_json TEXT NOT NULL DEFAULT '{}',
            created_by_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE SET NULL,
            FOREIGN KEY (parent_revision_id) REFERENCES project_revisions(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (project_id, revision_number)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_project_revisions_project
        ON project_revisions(project_id, revision_number)
        """,
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '',
            owner_user_id TEXT,
            owner_session_id TEXT,
            project_id TEXT,
            generation_run_id TEXT,
            request_key TEXT,
            request_json TEXT NOT NULL DEFAULT '{}',
            result_artifact_id TEXT,
            error_json TEXT,
            partial_result_json TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
            FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_queue
        ON jobs(status, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_jobs_run
        ON jobs(generation_run_id, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            generation_run_id TEXT,
            project_revision_id TEXT,
            job_id TEXT,
            artifact_kind TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            storage_backend TEXT NOT NULL DEFAULT 'local',
            storage_key TEXT NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            media_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_by_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            archived_at TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE SET NULL,
            FOREIGN KEY (project_revision_id) REFERENCES project_revisions(id) ON DELETE SET NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL,
            FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_artifacts_project
        ON artifacts(project_id, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_artifacts_run
        ON artifacts(generation_run_id, stage, created_at)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_artifacts_hash
        ON artifacts(sha256)
        """,
        """
        CREATE TABLE IF NOT EXISTS artifact_relations (
            id TEXT PRIMARY KEY,
            source_artifact_id TEXT NOT NULL,
            target_artifact_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            FOREIGN KEY (target_artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
            UNIQUE (source_artifact_id, target_artifact_id, relation_type)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS review_stage_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            generation_run_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            status TEXT NOT NULL,
            input_revision_id TEXT,
            output_revision_id TEXT NOT NULL,
            invalidated_reason TEXT,
            confirmed_by_user_id TEXT NOT NULL,
            confirmed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY (generation_run_id) REFERENCES generation_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (input_revision_id) REFERENCES project_revisions(id) ON DELETE SET NULL,
            FOREIGN KEY (output_revision_id) REFERENCES project_revisions(id) ON DELETE CASCADE,
            FOREIGN KEY (confirmed_by_user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE (generation_run_id, stage, version_number)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_review_stage_versions_active
        ON review_stage_versions(generation_run_id, stage, status)
        """,
        """
        CREATE TABLE IF NOT EXISTS cache_entries (
            cache_key TEXT PRIMARY KEY,
            cache_kind TEXT NOT NULL,
            storage_key TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            hit_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_accessed_at TEXT NOT NULL
        )
        """,
    ]

    with db_conn() as conn:
        for statement in statements:
            conn.raw.execute(statement)

        _ensure_column(conn, "users", "username", "TEXT")
        _ensure_column(conn, "users", "password_hash", "TEXT")
        _ensure_column(conn, "users", "role", "TEXT NOT NULL DEFAULT 'user'")
        _ensure_column(conn, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(conn, "user_sessions", "expires_at", "TEXT")
        _ensure_column(conn, "experiments", "generation_conditions_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "edit_events", "experiment_id", "TEXT")
        _ensure_column(conn, "edit_events", "generation_run_id", "TEXT")
        _ensure_column(conn, "correction_memories", "generation_run_id", "TEXT")
        conn.raw.execute(
            "CREATE INDEX IF NOT EXISTS idx_edit_events_generation_run ON edit_events(generation_run_id, created_at)"
        )
        conn.raw.execute(
            "CREATE INDEX IF NOT EXISTS idx_correction_memories_generation_run "
            "ON correction_memories(generation_run_id, created_at)"
        )
        _ensure_column(conn, "projects", "usage_context", "TEXT NOT NULL DEFAULT 'general'")
        _ensure_column(conn, "projects", "analysis_status", "TEXT NOT NULL DEFAULT 'candidate'")
        _ensure_column(conn, "projects", "current_source_artifact_id", "TEXT")
        _ensure_column(conn, "projects", "active_run_id", "TEXT")
        _ensure_column(conn, "projects", "archived_at", "TEXT")
        _ensure_column(conn, "generation_runs", "source_artifact_id", "TEXT")
        _ensure_column(conn, "generation_runs", "usage_context", "TEXT NOT NULL DEFAULT 'general'")
        _ensure_column(conn, "generation_runs", "analysis_status", "TEXT NOT NULL DEFAULT 'candidate'")
        _ensure_column(conn, "generation_runs", "reused_from_run_id", "TEXT")
        _ensure_column(conn, "generation_runs", "model_json", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "generation_runs", "prompt_json", "TEXT NOT NULL DEFAULT '{}'")
        conn.raw.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_unique ON users(username)")

        existing = conn.execute(
            "SELECT id FROM review_settings WHERE scope_type = :scope_type AND scope_key IS NULL",
            {"scope_type": "global"},
        ).fetchone()
        if existing is None:
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO review_settings (
                    id, scope_type, scope_key, layout_review_mode, script_review_mode, created_at, updated_at
                ) VALUES (:id, :scope_type, :scope_key, :layout_review_mode, :script_review_mode, :created_at, :updated_at)
                """,
                {
                    "id": "review_global_default",
                    "scope_type": "global",
                    "scope_key": None,
                    "layout_review_mode": "off",
                    "script_review_mode": "off",
                    "created_at": now,
                    "updated_at": now,
                },
            )

        condition_setting = conn.execute(
            "SELECT key FROM app_settings WHERE key = :key",
            {"key": "generation_conditions_global"},
        ).fetchone()
        if condition_setting is None:
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                """
                INSERT INTO app_settings (key, value_json, created_at, updated_at)
                VALUES (:key, :value_json, :created_at, :updated_at)
                """,
                {
                    "key": "generation_conditions_global",
                    "value_json": _json_text(
                        {
                            "kg_mode": "off",
                            "log_reuse_enabled": False,
                            "review_flow_enabled": True,
                            "prompt_strategy_version": "baseline_v1",
                        }
                    ),
                    "created_at": now,
                    "updated_at": now,
                },
            )


def json_text(value: object) -> str:
    return _json_text(value)


def assert_storage_schema_ready() -> None:
    required = {
        "alembic_version",
        "projects",
        "project_drafts",
        "project_revisions",
        "generation_runs",
        "edit_events",
        "correction_memories",
        "jobs",
        "artifacts",
        "artifact_relations",
        "review_stage_versions",
        "cache_entries",
    }
    required_columns = {
        "projects": {"usage_context", "analysis_status", "current_source_artifact_id", "active_run_id", "archived_at"},
        "generation_runs": {"source_artifact_id", "usage_context", "analysis_status", "model_json", "prompt_json"},
        "edit_events": {"generation_run_id"},
        "correction_memories": {"generation_run_id"},
        "jobs": {"generation_run_id", "result_artifact_id", "heartbeat_at", "retry_count"},
        "artifacts": {"storage_key", "sha256", "size_bytes", "artifact_kind", "status"},
    }
    with db_conn() as conn:
        if conn.dialect == "sqlite":
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            existing = {str(row["name"]) for row in rows}
        else:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                """
            ).fetchall()
            existing = {str(row["table_name"]) for row in rows}
        missing_tables = sorted(required - existing)
        missing_columns = {
            table: sorted(columns - _list_columns(conn, table))
            for table, columns in required_columns.items()
            if table in existing and columns - _list_columns(conn, table)
        }
        revision = None
        if "alembic_version" in existing:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = str(row["version_num"]) if row else None
    if missing_tables or missing_columns or revision != "20260727_02":
        details = []
        if missing_tables:
            details.append(f"missing tables: {', '.join(missing_tables)}")
        if missing_columns:
            details.append(
                "missing columns: "
                + "; ".join(f"{table}({', '.join(columns)})" for table, columns in missing_columns.items())
            )
        if revision != "20260727_02":
            details.append(f"alembic revision: {revision or 'none'}")
        raise RuntimeError(
            "LectureCraft storage schema is not migrated. "
            "Run 'alembic upgrade head' before starting the backend. "
            + " | ".join(details)
        )
