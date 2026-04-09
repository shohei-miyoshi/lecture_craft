from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


APP_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = APP_ROOT / "data"
DEFAULT_SQLITE_PATH = DATA_ROOT / "kenkyu_app.db"


def get_database_url() -> str:
    return os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")


def _resolve_sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise RuntimeError(
            "現在の開発版では sqlite を正本として使います。"
            "本番の PostgreSQL 切り替えは接続層をこの backend 側で差し替えます。"
        )
    raw = database_url.removeprefix("sqlite:///")
    path = Path(raw)
    if not path.is_absolute():
        path = (APP_ROOT / path).resolve()
    return path


def get_sqlite_path() -> Path:
    return _resolve_sqlite_path(get_database_url())


def _connect() -> sqlite3.Connection:
    db_path = get_sqlite_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def init_db() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with db_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                user_kind TEXT NOT NULL,
                email TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

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
            );

            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                invite_code TEXT NOT NULL UNIQUE,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experiment_participants (
                id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                UNIQUE (experiment_id, user_id),
                FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

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
            );

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
            );

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
            );

            CREATE TABLE IF NOT EXISTS review_settings (
                id TEXT PRIMARY KEY,
                scope_type TEXT NOT NULL,
                scope_key TEXT,
                layout_review_mode TEXT NOT NULL,
                script_review_mode TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (scope_type, scope_key)
            );

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
            );

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
            );
            """
        )

        existing = conn.execute(
            "SELECT id FROM review_settings WHERE scope_type = ? AND scope_key IS NULL",
            ("global",),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO review_settings (
                    id, scope_type, scope_key, layout_review_mode, script_review_mode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("review_global_default", "global", None, "off", "off"),
            )


def json_text(value: object) -> str:
    return _json_text(value)
