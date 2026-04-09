from __future__ import annotations

import json
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
DEFAULT_SQLITE_PATH = DATA_ROOT / "kenkyu_app.db"
POSTGRES_PREFIXES = ("postgresql://", "postgres://")
PARAM_PATTERN = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")


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
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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
            UNIQUE (project_id, external_event_id)
        )
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
    ]

    with db_conn() as conn:
        for statement in statements:
            conn.raw.execute(statement)

        _ensure_column(conn, "users", "username", "TEXT")
        _ensure_column(conn, "users", "password_hash", "TEXT")
        _ensure_column(conn, "users", "role", "TEXT NOT NULL DEFAULT 'user'")
        _ensure_column(conn, "users", "is_active", "INTEGER NOT NULL DEFAULT 1")
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


def json_text(value: object) -> str:
    return _json_text(value)
