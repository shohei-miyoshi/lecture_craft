from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import db_conn  # noqa: E402
from app.storage import get_artifact_store  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_integrity(*, verify_hashes: bool) -> dict:
    store = get_artifact_store()
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, storage_key, sha256, size_bytes, status
            FROM artifacts
            ORDER BY created_at
            """
        ).fetchall()
        export_rows = conn.execute(
            """
            SELECT id, output_path
            FROM research_export_snapshots
            WHERE status = 'completed' AND output_path IS NOT NULL
            """
        ).fetchall()
    missing = []
    size_mismatch = []
    hash_mismatch = []
    registered_keys = set()
    for row in rows:
        registered_keys.add(str(row["storage_key"]))
        path = store.resolve(row["storage_key"])
        if not path.exists():
            missing.append(row["id"])
            continue
        actual_size = path.stat().st_size
        if actual_size != int(row["size_bytes"] or 0):
            size_mismatch.append({"artifact_id": row["id"], "expected": row["size_bytes"], "actual": actual_size})
        if verify_hashes:
            actual_hash = sha256_file(path)
            if actual_hash != row["sha256"]:
                hash_mismatch.append({"artifact_id": row["id"], "expected": row["sha256"], "actual": actual_hash})
    missing_exports = []
    for row in export_rows:
        registered_keys.add(str(row["output_path"]))
        if not store.resolve(row["output_path"]).exists():
            missing_exports.append(row["id"])
    orphan_files = []
    for path in store.iter_files():
        key = str(path.resolve().relative_to(store.root))
        if key not in registered_keys:
            orphan_files.append(key)
    return {
        "ok": not missing and not missing_exports and not size_mismatch and not hash_mismatch,
        "artifact_count": len(rows),
        "missing_artifact_ids": missing,
        "missing_research_export_ids": missing_exports,
        "size_mismatches": size_mismatch,
        "hash_mismatches": hash_mismatch,
        "orphan_files": orphan_files,
        "storage": store.disk_status(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check LectureCraft DB/artifact consistency")
    parser.add_argument("--verify-hashes", action="store_true")
    args = parser.parse_args()
    result = check_integrity(verify_hashes=args.verify_hashes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
