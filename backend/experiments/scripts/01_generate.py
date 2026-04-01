# experiments/scripts/01_generate.py
# ============================================================
# Step1: Generate（動画 / 音声のみの生成をジョブとして回す）
#
# ✅ 確定仕様（あなたの引き継ぎプロンプト準拠）
# - 司令塔 Step0（run_pipeline.py）が作った run を正として処理する
# - run 内の config が唯一の真実：
#     experiments/runs/<run_id>/config/experiment_config.json
# - Step1 は teachingmaterial/ を参照してよい（生成フェーズ）
# - 生成結果の output_root は stdout から拾わない
#   -> 必ず --emit-meta で吐かせた JSON を読んで取得する
# - Step1 の成果は run/logs 配下に集約し、Step2 が入力として使える形に残す
#
# ✅ 今回の修正（(2) 仕様完全一致）
# - PDF 検出ロジックを run/config の pdf_scan に統一
# - include_glob / exclude_glob / sort を反映
# - Windows の大小文字問題による二重カウントを dedup で防止
#
# 出力（Step1 bookkeeping）
# - experiments/runs/<run_id>/logs/step01_generate/output_roots.jsonl
# - experiments/runs/<run_id>/logs/step01_generate/<lecture>/<cond_id>/emit_meta.json
# - experiments/runs/<run_id>/logs/step01_generate/<lecture>/<cond_id>/{stdout.log,stderr.log}
# - experiments/runs/<run_id>/generation/meta/<lecture>/<cond_id>/{meta.json,.done}
#
# ============================================================

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ----------------------------
# utils
# ----------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print("[WARN] " + msg, flush=True)


def fatal(msg: str, code: int = 2) -> None:
    print("[FATAL] " + msg, file=sys.stderr, flush=True)
    raise SystemExit(code)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, rec: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ----------------------------
# condition spec mapping
# ----------------------------
LEVEL_MAP = {"baseline": "L2", "intro": "L1", "advanced": "L3"}
DETAIL_MAP = {"baseline": "D2", "summary": "D1", "detail": "D3"}


def validate_condition_specs(condition_specs: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(condition_specs, dict) or not condition_specs:
        fatal("condition_specs is empty or invalid in experiment_config.json")

    for cond_id, spec in condition_specs.items():
        if not isinstance(spec, dict):
            fatal(f"condition_specs[{cond_id}] must be an object")

        t = spec.get("type")
        if t not in ("animation", "audio"):
            fatal(f"condition_specs[{cond_id}].type must be 'animation' or 'audio' but got: {t}")

        level_label = spec.get("level")
        detail_label = spec.get("detail")
        if level_label not in LEVEL_MAP:
            fatal(
                f"unknown level label: {level_label} in condition_specs[{cond_id}]. "
                f"allowed={list(LEVEL_MAP.keys())}"
            )
        if detail_label not in DETAIL_MAP:
            fatal(
                f"unknown detail label: {detail_label} in condition_specs[{cond_id}]. "
                f"allowed={list(DETAIL_MAP.keys())}"
            )

    return condition_specs  # type: ignore


# ----------------------------
# pdf scan config
# ----------------------------
@dataclass(frozen=True)
class PdfScanConfig:
    material_root: Path
    pdf_dir: Path
    include_glob: List[str]
    exclude_glob: List[str]
    sort: str  # "name_asc" / "name_desc" / "mtime_asc" / "mtime_desc"

    @staticmethod
    def from_config(cfg: Dict[str, Any], *, project_root: Path) -> "PdfScanConfig":
        ps = cfg.get("pdf_scan") or {}
        if not isinstance(ps, dict):
            fatal("pdf_scan must be an object in experiment_config.json")

        material_root = ps.get("material_root", "teachingmaterial")
        pdf_dir = ps.get("pdf_dir", "pdf")
        include_glob = ps.get("include_glob", ["*.pdf"])
        exclude_glob = ps.get("exclude_glob", [])
        sort = ps.get("sort", "name_asc")

        if isinstance(include_glob, str):
            include_glob = [include_glob]
        if isinstance(exclude_glob, str):
            exclude_glob = [exclude_glob]

        if not isinstance(include_glob, list) or not all(isinstance(x, str) for x in include_glob):
            fatal("pdf_scan.include_glob must be a list of strings")
        if not isinstance(exclude_glob, list) or not all(isinstance(x, str) for x in exclude_glob):
            fatal("pdf_scan.exclude_glob must be a list of strings")

        sort_allowed = {"name_asc", "name_desc", "mtime_asc", "mtime_desc"}
        if sort not in sort_allowed:
            fatal(f"pdf_scan.sort must be one of {sorted(sort_allowed)} but got: {sort}")

        # project_root からの相対として扱う（run_pipeline が cwd=PROJECT_ROOT で呼ぶ前提）
        material_root_p = (project_root / str(material_root)).resolve()
        pdf_root_p = (material_root_p / str(pdf_dir)).resolve()

        return PdfScanConfig(
            material_root=material_root_p,
            pdf_dir=pdf_root_p,
            include_glob=list(include_glob),
            exclude_glob=list(exclude_glob),
            sort=sort,
        )


def _dedup_paths(paths: List[Path]) -> List[Path]:
    """
    Windows で *.pdf / *.PDF 等を両方拾ったときも二重にならないようにする。
    """
    seen: set[str] = set()
    unique: List[Path] = []
    for p in paths:
        try:
            key = str(p.resolve()).casefold()
        except Exception:
            key = str(p.absolute()).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def scan_pdfs_from_pdf_scan(cfg_pdf: PdfScanConfig) -> List[Path]:
    """
    run/config の pdf_scan に完全準拠して PDF 一覧を返す。
    - include_glob で拾って exclude_glob で落とす
    - dedup（Windows 大小問題、glob重複）を必ず実施
    - sort を適用
    """
    pdf_root = cfg_pdf.pdf_dir
    if not pdf_root.exists():
        fatal(f"pdf_scan.pdf_dir not found: {pdf_root}")

    # 1) include で集める
    candidates: List[Path] = []
    for pat in cfg_pdf.include_glob:
        candidates.extend(list(pdf_root.glob(pat)))

    # 2) dedup（include_glob 重複や大小問題対策）
    candidates = _dedup_paths(candidates)

    # 3) exclude で落とす（パターン一致のものを除外）
    if cfg_pdf.exclude_glob:
        exclude_set: set[str] = set()
        for pat in cfg_pdf.exclude_glob:
            for p in pdf_root.glob(pat):
                try:
                    exclude_set.add(str(p.resolve()).casefold())
                except Exception:
                    exclude_set.add(str(p.absolute()).casefold())

        filtered: List[Path] = []
        for p in candidates:
            try:
                k = str(p.resolve()).casefold()
            except Exception:
                k = str(p.absolute()).casefold()
            if k in exclude_set:
                continue
            filtered.append(p)
        candidates = filtered

    if not candidates:
        fatal(f"No PDF found after include/exclude in: {pdf_root}")

    # 4) sort
    if cfg_pdf.sort == "name_asc":
        candidates.sort(key=lambda p: p.name.casefold())
    elif cfg_pdf.sort == "name_desc":
        candidates.sort(key=lambda p: p.name.casefold(), reverse=True)
    elif cfg_pdf.sort == "mtime_asc":
        candidates.sort(key=lambda p: p.stat().st_mtime)
    elif cfg_pdf.sort == "mtime_desc":
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return candidates


# ----------------------------
# job
# ----------------------------
@dataclass(frozen=True)
class Job:
    lecture: str  # PDFファイル名（例: パターン認識への誘い.pdf）
    cond_id: str
    gen_type: str  # animation/audio
    level_label: str
    detail_label: str
    level_axis: str  # L1/L2/L3...
    detail_axis: str  # D1/D2/D3...


# ----------------------------
# process runner
# ----------------------------
def _stream_to_file(stream, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", errors="replace", newline="") as f:
        for line in iter(stream.readline, ""):
            f.write(line)
            f.flush()
    stream.close()


def run_cmd_save_logs(cmd: List[str], stdout_path: Path, stderr_path: Path) -> int:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    t_out = threading.Thread(target=_stream_to_file, args=(proc.stdout, stdout_path), daemon=True)
    t_err = threading.Thread(target=_stream_to_file, args=(proc.stderr, stderr_path), daemon=True)
    t_out.start()
    t_err.start()

    rc = proc.wait()
    t_out.join()
    t_err.join()
    return rc


# ----------------------------
# emit-meta reader（JSONのみ）
# ----------------------------
def read_output_root_from_emit_meta(meta_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    emit_meta.json を読んで output_root を返す。
    戻り値: (output_root, output_root_abs)
    """
    if not meta_path.exists():
        return None, None
    try:
        obj = read_json(meta_path)
    except Exception:
        return None, None
    if not isinstance(obj, dict):
        return None, None

    out = obj.get("output_root")
    out_abs = obj.get("output_root_abs")

    output_root = out.strip() if isinstance(out, str) and out.strip() else None
    output_root_abs = out_abs.strip() if isinstance(out_abs, str) and out_abs.strip() else None
    return output_root, output_root_abs


# ----------------------------
# downstream command builders
# ----------------------------
def build_animation_cmd(project_root: Path, pdf_name: str, level_axis: str, detail_axis: str, run_id: str, cond_id: str, emit_meta_path: Path) -> List[str]:
    script = (project_root / "scripts" / "run_all.py")
    return [
        sys.executable,
        str(script),
        "--material", pdf_name,
        "--level", level_axis,
        "--detail", detail_axis,
        "--run-id", run_id,
        "--cond-id", cond_id,
        "--emit-meta", str(emit_meta_path),
    ]


def build_audio_cmd(project_root: Path, pdf_name: str, level_axis: str, detail_axis: str, run_id: str, cond_id: str, emit_meta_path: Path) -> List[str]:
    script = (project_root / "scripts" / "run_audio_only_lecture.py")
    return [
        sys.executable,
        str(script),
        "--material", pdf_name,
        "--level", level_axis,
        "--detail", detail_axis,
        "--run-id", run_id,
        "--cond-id", cond_id,
        "--emit-meta", str(emit_meta_path),
    ]


# ----------------------------
# run config loader（唯一の真実）
# ----------------------------
def load_run_config(run_dir: Path) -> Tuple[Path, Dict[str, Any]]:
    cfg_path = run_dir / "config" / "experiment_config.json"
    if not cfg_path.exists():
        fatal(f"run config not found (must exist): {cfg_path}")
    try:
        cfg = read_json(cfg_path)
    except Exception as e:
        fatal(f"failed to read run config: {cfg_path} ({repr(e)})")
    if not isinstance(cfg, dict):
        fatal(f"run config must be JSON object: {cfg_path}")
    return cfg_path, cfg


# ----------------------------
# main
# ----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs-root", default="experiments/runs")
    ap.add_argument("--project-root", default=".")
    ap.add_argument("--force", action="store_true")

    # 互換用（渡されても無視する：run/config が唯一の真実）
    ap.add_argument("--config", default=None)
    ap.add_argument("--pdf-dir", default=None)
    args = ap.parse_args()

    run_id = args.run_id
    project_root = Path(args.project_root).resolve()
    runs_root = Path(args.runs_root)

    run_dir = runs_root / run_id
    if not run_dir.exists():
        fatal(f"run_dir not found: {run_dir}")

    # ✅ run 内 config を読む（唯一の真実）
    cfg_path, cfg = load_run_config(run_dir)

    # condition_specs
    condition_specs = validate_condition_specs(cfg.get("condition_specs"))

    # pdf_scan（run/config に準拠）
    pdf_scan_cfg = PdfScanConfig.from_config(cfg, project_root=project_root)
    pdf_paths = scan_pdfs_from_pdf_scan(pdf_scan_cfg)

    # run outputs（Step1 bookkeeping）
    logs_step01_root = run_dir / "logs" / "step01_generate"
    meta_root = run_dir / "generation" / "meta"  # Step1 bookkeeping only
    logs_step01_root.mkdir(parents=True, exist_ok=True)
    meta_root.mkdir(parents=True, exist_ok=True)

    output_roots_jsonl = logs_step01_root / "output_roots.jsonl"

    # 条件の順序は config のキー順（Python 3.7+ で保持）
    cond_ids = list(condition_specs.keys())
    total_jobs = len(pdf_paths) * len(cond_ids)

    log(f"[Step1] run_id={run_id}")
    log(f"[Step1] pdfs={len(pdf_paths)} conditions={len(cond_ids)} jobs={total_jobs}")
    log(f"[Step1] memo_file={output_roots_jsonl}")
    log(f"[Step1] config={cfg_path}")

    # 明示的にどこを見ているかをログ（デバッグで助かる）
    log(f"[Step1] pdf_scan.material_root={pdf_scan_cfg.material_root}")
    log(f"[Step1] pdf_scan.pdf_dir={pdf_scan_cfg.pdf_dir}")
    log(f"[Step1] pdf_scan.include_glob={pdf_scan_cfg.include_glob}")
    log(f"[Step1] pdf_scan.exclude_glob={pdf_scan_cfg.exclude_glob}")
    log(f"[Step1] pdf_scan.sort={pdf_scan_cfg.sort}")

    if args.config:
        warn(f"--config was provided but ignored (run/config is the only truth). given={args.config}")
    if args.pdf_dir:
        warn(f"--pdf-dir was provided but ignored (use run/config pdf_scan). given={args.pdf_dir}")

    failed = 0
    job_index = 0

    for pdf_path in pdf_paths:
        lecture = pdf_path.name  # PDF名そのまま（Step2で正規化）

        for cond_id in cond_ids:
            job_index += 1
            spec = condition_specs[cond_id]

            gen_type = str(spec["type"])
            level_label = str(spec["level"])
            detail_label = str(spec["detail"])
            level_axis = LEVEL_MAP[level_label]
            detail_axis = DETAIL_MAP[detail_label]

            job = Job(
                lecture=lecture,
                cond_id=cond_id,
                gen_type=gen_type,
                level_label=level_label,
                detail_label=detail_label,
                level_axis=level_axis,
                detail_axis=detail_axis,
            )

            # bookkeeping paths
            job_done = meta_root / job.lecture / job.cond_id / ".done"
            job_meta = meta_root / job.lecture / job.cond_id / "meta.json"

            job_stdout = logs_step01_root / job.lecture / job.cond_id / "stdout.log"
            job_stderr = logs_step01_root / job.lecture / job.cond_id / "stderr.log"
            emit_meta_path = logs_step01_root / job.lecture / job.cond_id / "emit_meta.json"

            if job_done.exists() and not args.force:
                log(f"({job_index}/{total_jobs}) SKIP | {job.lecture} | {job.cond_id} | {job.gen_type} ({job.level_axis},{job.detail_axis})")
                continue

            started_at = now_iso()
            log(f"({job_index}/{total_jobs}) START | {job.lecture} | {job.cond_id} | {job.gen_type} ({job.level_axis},{job.detail_axis})")
            t0 = time.perf_counter()

            # downstream cmd
            if job.gen_type == "animation":
                cmd = build_animation_cmd(project_root, job.lecture, job.level_axis, job.detail_axis, run_id, job.cond_id, emit_meta_path)
            else:
                cmd = build_audio_cmd(project_root, job.lecture, job.level_axis, job.detail_axis, run_id, job.cond_id, emit_meta_path)

            rc = run_cmd_save_logs(cmd, job_stdout, job_stderr)

            elapsed = time.perf_counter() - t0
            finished_at = now_iso()

            output_root, output_root_abs = read_output_root_from_emit_meta(emit_meta_path)

            ok = (rc == 0) and (output_root is not None)
            status = "ok" if ok else "error"
            if not ok:
                failed += 1

            # Step1 meta
            write_json_atomic(
                job_meta,
                {
                    "run_id": run_id,
                    "lecture": job.lecture,
                    "cond_id": job.cond_id,
                    "type": job.gen_type,
                    "level_label": job.level_label,
                    "detail_label": job.detail_label,
                    "axes": f"{job.level_axis}{job.detail_axis}",
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "elapsed_sec": round(elapsed, 3),
                    "status": status,
                    "returncode": rc,
                    "output_root": output_root,
                    "output_root_abs": output_root_abs,
                    "emit_meta": str(emit_meta_path),
                    "stdout_log": str(job_stdout),
                    "stderr_log": str(job_stderr),
                    "note": "output_root is read ONLY from emit_meta.json.",
                },
            )

            # memo jsonl（Step2入力）
            append_jsonl(
                output_roots_jsonl,
                {
                    "run_id": run_id,
                    "lecture": job.lecture,
                    "cond_id": job.cond_id,
                    "type": job.gen_type,
                    "level_label": job.level_label,
                    "detail_label": job.detail_label,
                    "axes": f"{job.level_axis}{job.detail_axis}",
                    "status": status,
                    "returncode": rc,
                    "output_root": output_root,
                    "output_root_abs": output_root_abs,
                    "emit_meta": str(emit_meta_path),
                    "stdout_log": str(job_stdout),
                    "stderr_log": str(job_stderr),
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "elapsed_sec": round(elapsed, 3),
                },
            )

            job_done.parent.mkdir(parents=True, exist_ok=True)
            job_done.write_text(finished_at, encoding="utf-8")

            log(f"({job_index}/{total_jobs}) {'OK' if status=='ok' else 'FAIL'} | {job.lecture} | {job.cond_id} | {round(elapsed,1)}s")

    log(f"[Step1] DONE failed={failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
