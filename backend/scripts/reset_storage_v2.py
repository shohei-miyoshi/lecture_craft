from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import db_conn, db_kind, get_database_url, get_sqlite_path  # noqa: E402
from app.storage import get_artifact_store  # noqa: E402


CHILD_TABLES = [
    "artifact_relations",
    "cache_entries",
    "review_stage_versions",
    "artifacts",
    "jobs",
    "correction_memories",
    "edit_events",
    "layout_review_records",
    "script_review_records",
    "review_stage_snapshots",
    "knowledge_graph_versions",
    "project_revisions",
    "project_drafts",
    "project_versions",
    "research_session_snapshots",
    "api_job_snapshots",
    "export_event_snapshots",
    "research_export_snapshots",
    "generation_runs",
    "projects",
    "experiment_participants",
    "experiments",
    "user_sessions",
]


def _table_exists(conn, table_name: str) -> bool:
    if conn.dialect == "sqlite":
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name",
            {"table_name": table_name},
        ).fetchone()
        return row is not None
    row = conn.execute(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = :table_name
        """,
        {"table_name": table_name},
    ).fetchone()
    return row is not None


def _archive_directories(timestamp: str, destination_root: Path | None = None) -> Path:
    archive_base = (
        destination_root.expanduser().resolve()
        if destination_root is not None
        else (BACKEND_ROOT / "data" / "legacy_backup").resolve()
    )
    store = get_artifact_store()
    candidates = [
        ("storage_v2", store.root),
        ("legacy_outputs", BACKEND_ROOT / "outputs"),
        ("legacy_teachingmaterial", BACKEND_ROOT / "teachingmaterial"),
    ]
    for _, source in candidates:
        try:
            archive_base.relative_to(source.resolve())
        except ValueError:
            continue
        raise RuntimeError(f"Backup destination must not be inside a directory that will be reset: {source}")
    archive_base.mkdir(parents=True, exist_ok=True)
    backup_root = archive_base / timestamp
    backup_root.mkdir(parents=True, exist_ok=False)
    archived = []
    for label, source in candidates:
        if not source.exists():
            continue
        destination = backup_root / label
        shutil.copytree(source, destination)
        archived.append({"label": label, "source": str(source), "destination": str(destination)})
    database_output = backup_root / ("database.sqlite3" if db_kind() == "sqlite" else "database.dump")
    if db_kind() == "sqlite":
        with sqlite3.connect(get_sqlite_path()) as source, sqlite3.connect(database_output) as destination:
            source.backup(destination)
    else:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(database_output), get_database_url()],
            check=True,
        )
    (backup_root / "manifest.json").write_text(
        json.dumps(
            {
                "created_at": timestamp,
                "database_kind": db_kind(),
                "database_file": database_output.name,
                "archived": archived,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return backup_root


def _clear_data_directories() -> None:
    store = get_artifact_store()
    for source in (store.root, BACKEND_ROOT / "outputs", BACKEND_ROOT / "teachingmaterial"):
        if source.exists():
            shutil.rmtree(source)
    store.ensure_ready()


def reset(*, confirm: bool, preserve_admin: bool, backup_destination: Path | None = None) -> dict:
    if not confirm:
        raise RuntimeError("--confirm is required")
    if not preserve_admin:
        raise RuntimeError("This command requires --preserve-admin")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with db_conn() as conn:
        admins = conn.execute(
            "SELECT id, username, role FROM users WHERE role = 'admin' ORDER BY created_at"
        ).fetchall()
        if not admins:
            raise RuntimeError("No administrator account exists; reset aborted")
    backup_root = _archive_directories(timestamp, backup_destination)
    with db_conn() as conn:
        for table_name in CHILD_TABLES:
            if _table_exists(conn, table_name):
                conn.execute(f"DELETE FROM {table_name}")
        conn.execute("DELETE FROM users WHERE role <> 'admin'")
    _clear_data_directories()
    return {
        "ok": True,
        "preserved_admin_count": len(admins),
        "backup_root": str(backup_root),
        "reset_at": timestamp,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset LectureCraft test data for storage v2")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--preserve-admin", action="store_true")
    parser.add_argument("--backup-destination")
    args = parser.parse_args()
    print(
        json.dumps(
            reset(
                confirm=args.confirm,
                preserve_admin=args.preserve_admin,
                backup_destination=Path(args.backup_destination) if args.backup_destination else None,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
