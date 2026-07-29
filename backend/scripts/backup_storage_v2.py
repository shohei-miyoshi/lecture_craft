from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import db_kind, get_database_url, get_sqlite_path  # noqa: E402
from app.storage import get_artifact_store  # noqa: E402


def backup(destination_root: Path) -> dict:
    destination_root = destination_root.expanduser().resolve()
    if not destination_root.exists() or not destination_root.is_dir():
        raise RuntimeError("バックアップ先ディレクトリが存在しません。先に別ストレージをmountしてください。")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    generation_dir = destination_root / timestamp
    generation_dir.mkdir(mode=0o700)
    database_output = generation_dir / ("database.sqlite3" if db_kind() == "sqlite" else "database.dump")
    if db_kind() == "sqlite":
        with sqlite3.connect(get_sqlite_path()) as source, sqlite3.connect(database_output) as destination:
            source.backup(destination)
    else:
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(database_output), get_database_url()],
            check=True,
        )
    artifact_archive = generation_dir / "artifacts.tar.gz"
    store = get_artifact_store()
    with tarfile.open(artifact_archive, "w:gz") as archive:
        if store.artifact_root.exists():
            archive.add(store.artifact_root, arcname="artifacts")
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "database_kind": db_kind(),
        "database_file": database_output.name,
        "artifact_archive": artifact_archive.name,
        "storage_status": store.disk_status(),
    }
    (generation_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "backup_directory": str(generation_dir), **manifest}


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up LectureCraft DB and persistent artifacts")
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    print(json.dumps(backup(Path(args.destination)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
