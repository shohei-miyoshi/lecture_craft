# -*- coding: utf-8 -*-
"""
experiments/scripts/run_pipeline.py
============================================================
Step0: 実験パイプライン司令塔（scripts配下版）

- 新規 run_id を作成し、run 内に config をコピーしてから Step1〜9 を実行
- .done_xx による途中再開に対応
- 重要: Step1〜9 は "run 内 config" を正として参照する（今回確定仕様）
- 重要: Step3/Step5 は manifest_step02.jsonl の dest を唯一の真実として参照する
============================================================
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# Paths（このファイルは experiments/scripts/ 配下）
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # auto_lecture/
EXPERIMENT_ROOT = PROJECT_ROOT / "experiments"
RUNS_ROOT = EXPERIMENT_ROOT / "runs"
RUNS_ROOT.mkdir(parents=True, exist_ok=True)

# 元 config の置き場所（運用中）
DEFAULT_CONFIG_PATH = EXPERIMENT_ROOT / "config" / "experiment_config.json"

# import 安全（Step1〜9 が auto_lecture を import する環境でも落とさない）
SRC_ROOT = PROJECT_ROOT / "src"


def now_ts() -> str:
    return time.strftime("%Y-%m-%d_%H%M%S", time.localtime())


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def die(msg: str, code: int = 1) -> None:
    print(f"[PIPELINE][FATAL] {msg}", flush=True)
    sys.exit(code)


def build_step_env() -> Dict[str, str]:
    """
    Step scripts は subprocess で別プロセス実行されるので、
    auto_lecture import が必ず通るように PYTHONPATH を付ける。
    """
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    src = str(SRC_ROOT)
    pp = env.get("PYTHONPATH", "")
    if pp:
        if src not in pp.split(os.pathsep):
            env["PYTHONPATH"] = src + os.pathsep + pp
    else:
        env["PYTHONPATH"] = src

    return env


def sanitize_name(s: str) -> str:
    bad = '\\/:*?"<>|'
    for ch in bad:
        s = s.replace(ch, "_")
    return s.strip()


def load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        die(f"experiment_config.json not found: {config_path}")
    return json.loads(config_path.read_text(encoding="utf-8"))


def detect_pdf_files(cfg: Dict[str, Any]) -> List[Path]:
    scan = cfg.get("pdf_scan", {})
    material_root = scan.get("material_root", "teachingmaterial")
    pdf_dir = scan.get("pdf_dir", "pdf")
    include_glob = scan.get("include_glob", ["*.pdf"])
    exclude_glob = scan.get("exclude_glob", [])
    sort_mode = scan.get("sort", "name_asc")

    pdf_root = PROJECT_ROOT / material_root / pdf_dir
    if not pdf_root.exists():
        die(f"pdf_root not found: {pdf_root}")

    files: List[Path] = []
    for pat in include_glob:
        files.extend(list(pdf_root.glob(pat)))

    excl: set[Path] = set()
    for pat in exclude_glob:
        excl.update(set(pdf_root.glob(pat)))
    files = [p for p in files if p not in excl]

    if sort_mode == "name_asc":
        files = sorted(files, key=lambda p: p.name)
    elif sort_mode == "mtime_asc":
        files = sorted(files, key=lambda p: p.stat().st_mtime)
    elif sort_mode == "mtime_desc":
        files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    else:
        files = sorted(files, key=lambda p: p.name)

    return files


def count_conditions(cfg: Dict[str, Any]) -> int:
    cond_specs = cfg.get("condition_specs", {})
    if isinstance(cond_specs, dict):
        return len(cond_specs.keys())
    return 0


def build_run_id(cfg: Dict[str, Any], pdf_count: int, cond_count: int) -> str:
    """
    <experiment_id>_<Npdf>pdf_<Nconds>conds_<timestamp>
    """
    experiment_id = str(cfg.get("experiment_id", "exp")).strip() or "exp"
    experiment_id = sanitize_name(experiment_id)
    return f"{experiment_id}_{pdf_count}pdf_{cond_count}conds_{now_ts()}"


# ============================================================
# Step definition
# ============================================================
@dataclass
class Step:
    step_id: str
    script_rel: str
    description: str
    extra_args: List[str]


@dataclass
class StepResult:
    step_id: str
    returncode: int
    started_at: str
    ended_at: str
    elapsed_sec: float
    stdout_log: str
    stderr_log: str
    cmd: List[str]


def run_step(step: Step, run_dir: Path, env: Dict[str, str]) -> StepResult:
    script_path = PROJECT_ROOT / step.script_rel
    if not script_path.exists():
        die(f"script not found: {script_path}")

    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = logs_dir / f"{step.step_id}.stdout.log"
    stderr_log = logs_dir / f"{step.step_id}.stderr.log"

    started = now_iso()
    t0 = time.time()

    cmd = [sys.executable, str(script_path), "--run-id", run_dir.name, *step.extra_args]

    with stdout_log.open("w", encoding="utf-8") as out_f, stderr_log.open("w", encoding="utf-8") as err_f:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),  # 重要: CWD固定（dest相対などの事故防止）
            env=env,
            stdout=out_f,
            stderr=err_f,
            text=True,
        )

    ended = now_iso()
    return StepResult(
        step_id=step.step_id,
        returncode=int(proc.returncode),
        started_at=started,
        ended_at=ended,
        elapsed_sec=round(time.time() - t0, 3),
        stdout_log=str(stdout_log),
        stderr_log=str(stderr_log),
        cmd=[str(x) for x in cmd],
    )


def ensure_run_skeleton(run_dir: Path) -> None:
    for d in ["config", "generation", "extracted", "analysis", "review", "logs", "reports"]:
        (run_dir / d).mkdir(parents=True, exist_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default="", help="既存 run_id で再開する")
    ap.add_argument("--force", action="store_true", help="done を無視して最初から（全Step再実行）")
    ap.add_argument("--config", default="", help="元 experiment_config.json のパス（新規作成時のみ）")

    # 追加：運用で必須になるやつ
    ap.add_argument("--allow-partial", action="store_true", help="Step3/4/5 等の partial 許容を有効にする")
    ap.add_argument("--gpt-sleep", type=float, default=0.0, help="Step5 の呼び出し間スリープ秒")
    ap.add_argument("--gpt-model", default="", help="Step5: このモデルだけ実行（空ならconfig準拠）")
    ap.add_argument("--gpt-aspect", default="", help="Step5: この観点IDだけ実行（空なら全観点）")
    args = ap.parse_args()

    env = build_step_env()

    # --------------------------------------------------------
    # run_dir 決定
    # --------------------------------------------------------
    if args.run_id:
        run_dir = RUNS_ROOT / args.run_id
        if not run_dir.exists():
            die(f"specified run_id not found: {args.run_id}")

        ensure_run_skeleton(run_dir)

        # ✅ 確定仕様: resume時は run 内 config を正とする
        run_config_path = run_dir / "config" / "experiment_config.json"
        if not run_config_path.exists():
            die(f"run config not found (cannot resume): {run_config_path}")

        cfg = load_config(run_config_path)

        print(f"[PIPELINE] resume run_id = {run_dir.name}", flush=True)
        print(f"[PIPELINE] using run config = {run_config_path}", flush=True)

    else:
        # 新規作成：外側 config を読み、run 内へコピーする
        config_path = Path(args.config) if args.config else DEFAULT_CONFIG_PATH
        cfg = load_config(config_path)

        pdf_files = detect_pdf_files(cfg)
        pdf_count = len(pdf_files)
        cond_count = count_conditions(cfg)

        run_id = build_run_id(cfg, pdf_count, cond_count)
        run_dir = RUNS_ROOT / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        ensure_run_skeleton(run_dir)

        # run 内 config を正として保存
        (run_dir / "config" / "experiment_config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 実行時に検出したPDF一覧も保存（名前と実態のズレ防止）
        (run_dir / "reports" / "detected_pdfs.txt").write_text(
            "\n".join([p.name for p in pdf_files]) + "\n",
            encoding="utf-8",
        )

        print(f"[PIPELINE] new run_id = {run_dir.name}", flush=True)
        print(f"[PIPELINE] detected pdfs = {pdf_count}, conditions = {cond_count}", flush=True)
        print(f"[PIPELINE] copied config from = {config_path}", flush=True)

    # --------------------------------------------------------
    # Step extra args（必要なものだけ渡す）
    # --------------------------------------------------------
    allow_partial_args = ["--allow-partial"] if args.allow_partial else []

    step5_args: List[str] = []
    if args.gpt_sleep and args.gpt_sleep > 0:
        step5_args += ["--sleep", str(args.gpt_sleep)]
    if args.gpt_model:
        step5_args += ["--model", args.gpt_model]
    if args.gpt_aspect:
        step5_args += ["--aspect", args.gpt_aspect]
    # Step5 側にも partial を渡す
    step5_args += allow_partial_args

    # --------------------------------------------------------
    # Steps
    # --------------------------------------------------------
    steps: List[Step] = [
        Step("01_generate", "experiments/scripts/01_generate.py", "Step1 Generate", []),
        Step("02_bundle", "experiments/scripts/02_bundle_run_outputs.py", "Step2 Bundle", []),
        Step("03_extract", "experiments/scripts/03_extract.py", "Step3 Extract", allow_partial_args),
        Step("04_metrics_basic", "experiments/scripts/04_metrics_basic.py", "Step4 Metrics basic", allow_partial_args),
        Step("05_metrics_gpt", "experiments/scripts/05_metrics_gpt_counts.py", "Step5 Metrics GPT", step5_args),
        Step("06_pair_goal_judge", "experiments/scripts/06_pair_goal_judgements.py", "Step6 Pairwise judge", allow_partial_args),
        # Step("07_review_pack", "experiments/scripts/07_pack_animation_review.py", "Step7 Review pack", allow_partial_args),
        # Step("08_pair_goal_summary", "experiments/scripts/08_summarize_pair_goal_judgements.py", "Step8 Summarize", allow_partial_args),
        # Step("09_pair_goal_plots", "experiments/scripts/09_plot_pair_goal_judgements.py", "Step9 Plot", allow_partial_args),
    ]

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for step in steps:
        done = run_dir / f".done_{step.step_id}"

        if done.exists() and not args.force:
            print(f"[PIPELINE] skip {step.step_id} (done)", flush=True)
            continue

        print(f"[PIPELINE] run {step.step_id}: {step.description}", flush=True)
        r = run_step(step, run_dir, env)
        results.append(asdict(r))

        if r.returncode != 0:
            failures.append(asdict(r))
            print(f"[PIPELINE][ERROR] failed: {step.step_id}", flush=True)
            break

        done.write_text(now_iso(), encoding="utf-8")

    summary = {
        "run_id": run_dir.name,
        "ended_at": now_iso(),
        "all_ok": len(failures) == 0,
        "steps": results,
        "failures": failures,
    }
    (run_dir / "reports" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if failures:
        die("pipeline failed. See runs/<run_id>/logs and reports/summary.json")

    (run_dir / "DONE.txt").write_text("OK\n", encoding="utf-8")
    print(f"[PIPELINE] COMPLETED: {run_dir.name}", flush=True)


if __name__ == "__main__":
    main()
