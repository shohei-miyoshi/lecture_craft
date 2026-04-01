# experiments/scripts/02_bundle_run_outputs.py
# ============================================================
# Step2: Bundle/Move outputs into runs (FULL MOVE, NO COPY)
#
# ✅ ユーザー確定方針：
# - 生成物は卒論に貼るので「全生成物を固めて保存」したい
# - Auto_lecture の outputs から runs へ「丸ごと移動」（コピーはしない）
#
# 入力:
#   experiments/runs/<run_id>/logs/step01_generate/output_roots.jsonl
#
# 出力（固定）:
#   experiments/runs/<run_id>/generation/raw/<lecture_dir>/<cond_id>/<output_root_dirname>/...
#
# manifest:
#   experiments/runs/<run_id>/generation/manifest_step02.jsonl  (1ジョブ1行)
#   experiments/runs/<run_id>/generation/manifest_step02.json   (集約)
#
# 再実行:
# - 既に moved が完了していれば SKIP
# - --force で上書き（既存destを削除してから再移動）
# ============================================================

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def log(msg: str) -> None:
    print(f"[STEP2] {msg}", flush=True)


def fatal(msg: str, code: int = 2) -> None:
    print(f"[STEP2][FATAL] {msg}", flush=True)
    raise SystemExit(code)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        fatal(f"input jsonl not found: {path}")
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as e:
                fatal(f"invalid json at line {i} in {path}: {e}")
            if not isinstance(obj, dict):
                fatal(f"jsonl line {i} is not an object")
            rows.append(obj)
    return rows


def append_jsonl(path: Path, rec: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_dirname_from_lecture(lecture: str) -> str:
    """Windows でも安全な dir 名にする（最低限）"""
    bad = '<>:"/\\|?*'
    out = lecture
    for ch in bad:
        out = out.replace(ch, "_")
    return out


def safe_relpath(p: Path, base: Path) -> str:
    try:
        return str(p.resolve().relative_to(base.resolve())).replace("/", "\\")
    except Exception:
        return str(p)


def resolve_output_root(project_root: Path, output_root: str) -> Path:
    """
    output_root が相対なら project_root 基準で解決。
    絶対ならそのまま。
    """
    p = Path(output_root)
    if p.is_absolute():
        return p
    return (project_root / p).resolve()


def remove_dir_if_exists(p: Path) -> None:
    if not p.exists():
        return
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs-root", default="experiments/runs")
    ap.add_argument("--project-root", default=".", help="Step1で記録した output_root の相対基準")
    ap.add_argument("--force", action="store_true", help="既存移動先があっても削除して再移動する")
    args = ap.parse_args()

    run_id = args.run_id
    runs_root = Path(args.runs_root)
    project_root = Path(args.project_root).resolve()

    run_dir = runs_root / run_id
    if not run_dir.exists():
        fatal(f"run_dir not found: {run_dir}")

    # 入力：Step1のメモ
    input_jsonl = run_dir / "logs" / "step01_generate" / "output_roots.jsonl"
    rows = read_jsonl(input_jsonl)

    # 出力：manifest
    gen_root = run_dir / "generation"
    gen_raw_root = gen_root / "raw"
    manifest_jsonl = gen_root / "manifest_step02.jsonl"
    manifest_json = gen_root / "manifest_step02.json"

    log(f"run_id={run_id}")
    log(f"project_root={project_root}")
    log(f"input={input_jsonl}")
    log(f"dest_root={gen_raw_root}")
    log(f"mode=FULL_MOVE")
    log(f"rows={len(rows)}")

    started_all = now_iso()
    t_all = time.perf_counter()

    moved = 0
    skipped = 0
    failed = 0
    manifest_records: List[Dict[str, Any]] = []

    # 毎回作り直し
    if manifest_jsonl.exists():
        manifest_jsonl.unlink()

    for idx, r in enumerate(rows, start=1):
        lecture = str(r.get("lecture") or "").strip()
        cond_id = str(r.get("cond_id") or "").strip()
        output_root = str(r.get("output_root") or "").strip()

        if not lecture:
            failed += 1
            rec = {"index": idx, "status": "error", "reason": "missing lecture"}
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            continue
        if not cond_id:
            failed += 1
            rec = {"index": idx, "lecture": lecture, "status": "error", "reason": "missing cond_id"}
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            continue
        if not output_root:
            failed += 1
            rec = {"index": idx, "lecture": lecture, "cond_id": cond_id, "status": "error", "reason": "missing output_root"}
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            continue

        src_abs = resolve_output_root(project_root, output_root)
        src_name = src_abs.name  # output_root_dirname

        lecture_dir = safe_dirname_from_lecture(lecture)
        dest_parent = gen_raw_root / lecture_dir / cond_id
        dest_abs = dest_parent / src_name

        done_marker = dest_parent / ".done_step02_move"
        if done_marker.exists() and dest_abs.exists() and not args.force:
            skipped += 1
            rec = {
                "index": idx,
                "lecture": lecture,
                "cond_id": cond_id,
                "status": "skip",
                "src": safe_relpath(src_abs, project_root),
                "dest": safe_relpath(dest_abs, project_root),
                "output_root_dirname": src_name,
                "done_marker": safe_relpath(done_marker, project_root),
            }
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            log(f"({idx}/{len(rows)}) SKIP | {lecture} | {cond_id}")
            continue

        if args.force:
            remove_dir_if_exists(dest_abs)
            done_marker.unlink(missing_ok=True)

        started = now_iso()
        t0 = time.perf_counter()

        if (not src_abs.exists()) or (not src_abs.is_dir()):
            failed += 1
            rec = {
                "index": idx,
                "lecture": lecture,
                "cond_id": cond_id,
                "status": "error",
                "reason": "source output_root not found (dir)",
                "src": safe_relpath(src_abs, project_root),
                "dest": safe_relpath(dest_abs, project_root),
                "started_at": started,
            }
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            log(f"({idx}/{len(rows)}) FAIL | {lecture} | {cond_id} | src missing")
            continue

        dest_parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.move(str(src_abs), str(dest_abs))
            elapsed = time.perf_counter() - t0
            finished = now_iso()

            moved += 1
            done_marker.write_text(finished, encoding="utf-8")

            rec = {
                "index": idx,
                "lecture": lecture,
                "cond_id": cond_id,
                "status": "moved",
                "src": safe_relpath(src_abs, project_root),
                "dest": safe_relpath(dest_abs, project_root),
                "output_root_dirname": src_name,
                "started_at": started,
                "finished_at": finished,
                "elapsed_sec": round(elapsed, 3),
                "done_marker": safe_relpath(done_marker, project_root),
            }
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            log(f"({idx}/{len(rows)}) OK   | {lecture} | {cond_id} | {round(elapsed,1)}s")

        except Exception as e:
            failed += 1
            elapsed = time.perf_counter() - t0
            finished = now_iso()
            rec = {
                "index": idx,
                "lecture": lecture,
                "cond_id": cond_id,
                "status": "error",
                "reason": "move failed",
                "error": repr(e),
                "src": safe_relpath(src_abs, project_root),
                "dest": safe_relpath(dest_abs, project_root),
                "started_at": started,
                "finished_at": finished,
                "elapsed_sec": round(elapsed, 3),
            }
            append_jsonl(manifest_jsonl, rec)
            manifest_records.append(rec)
            log(f"({idx}/{len(rows)}) FAIL | {lecture} | {cond_id} | move error")

    total_elapsed = time.perf_counter() - t_all
    finished_all = now_iso()

    summary = {
        "run_id": run_id,
        "started_at": started_all,
        "finished_at": finished_all,
        "elapsed_sec_total": round(total_elapsed, 3),
        "input_jsonl": str(input_jsonl).replace("/", "\\"),
        "dest_root": str(gen_raw_root).replace("/", "\\"),
        "moved": moved,
        "skipped": skipped,
        "failed": failed,
        "records_count": len(manifest_records),
    }
    write_json(manifest_json, summary)

    log(f"DONE moved={moved} skipped={skipped} failed={failed} elapsed={round(total_elapsed,1)}s")
    log(f"wrote: {manifest_jsonl}")
    log(f"wrote: {manifest_json}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
