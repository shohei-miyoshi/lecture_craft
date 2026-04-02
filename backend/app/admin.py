from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from .cache import API_EVENT_ROOT, API_JOB_ROOT, RESEARCH_SESSION_ROOT


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_RUNS_ROOT = PROJECT_ROOT / "experiments" / "runs"


def build_admin_overview(limit: int = 12) -> Dict[str, Any]:
    jobs = _load_job_snapshots()
    exports = _load_export_events()
    research_sessions = _load_research_sessions()
    experiments = _load_experiment_runs(limit=limit)

    now = datetime.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    jobs_24h = [job for job in jobs if _parse_dt(job.get("created_at")) >= last_24h]
    jobs_7d = [job for job in jobs if _parse_dt(job.get("created_at")) >= last_7d]
    jobs_30d = [job for job in jobs if _parse_dt(job.get("created_at")) >= last_30d]

    export_7d = [event for event in exports if _parse_dt(event.get("created_at")) >= last_7d]

    mode_counter = Counter(
        str((job.get("payload") or {}).get("mode") or "unknown")
        for job in jobs
    )
    status_counter = Counter(str(job.get("status") or "unknown") for job in jobs)
    export_counter = Counter(str(event.get("export_type") or "unknown") for event in exports)
    research_trigger_counter = Counter(str(session.get("trigger") or "unknown") for session in research_sessions)

    completed_jobs = [job for job in jobs if job.get("status") == "completed"]
    failed_jobs = [job for job in jobs if job.get("status") == "failed"]

    research_summary_totals = {
        "highlights_modified": sum(_research_summary_value(session, "highlights_modified") for session in research_sessions),
        "highlights_accepted": sum(_research_summary_value(session, "highlights_accepted") for session in research_sessions),
        "highlights_removed": sum(_research_summary_value(session, "highlights_removed") for session in research_sessions),
        "highlights_added": sum(_research_summary_value(session, "highlights_added") for session in research_sessions),
        "sentences_modified": sum(_research_summary_value(session, "sentences_modified") for session in research_sessions),
        "sentences_text_modified": sum(_research_summary_value(session, "sentences_text_modified") for session in research_sessions),
        "sentences_timing_modified": sum(_research_summary_value(session, "sentences_timing_modified") for session in research_sessions),
        "sentences_removed": sum(_research_summary_value(session, "sentences_removed") for session in research_sessions),
        "sentences_added": sum(_research_summary_value(session, "sentences_added") for session in research_sessions),
    }

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "usage": {
            "jobs_total": len(jobs),
            "jobs_last_24h": len(jobs_24h),
            "jobs_last_7d": len(jobs_7d),
            "jobs_last_30d": len(jobs_30d),
            "completed_jobs": len(completed_jobs),
            "failed_jobs": len(failed_jobs),
            "cache_hits": sum(1 for job in jobs if job.get("cache_hit")),
            "deduplicated_jobs": sum(1 for job in jobs if job.get("deduplicated")),
            "exports_total": len(exports),
            "exports_last_7d": len(export_7d),
            "research_sessions_total": len(research_sessions),
        },
        "breakdowns": {
            "jobs_by_mode": _counter_payload(mode_counter),
            "jobs_by_status": _counter_payload(status_counter),
            "exports_by_type": _counter_payload(export_counter),
            "research_by_trigger": _counter_payload(research_trigger_counter),
        },
        "recent_jobs": jobs[:limit],
        "recent_exports": exports[:limit],
        "research": {
            "total_sessions": len(research_sessions),
            "summary_totals": research_summary_totals,
            "recent_sessions": research_sessions[:limit],
        },
        "experiments": {
            "total_runs": len(experiments),
            "completed_runs": sum(1 for run in experiments if run.get("completed")),
            "failed_runs": sum(1 for run in experiments if run.get("has_failures")),
            "recent_runs": experiments[:limit],
        },
    }


def _load_job_snapshots() -> List[Dict[str, Any]]:
    if not API_JOB_ROOT.exists():
        return []
    jobs: List[Dict[str, Any]] = []
    for path in sorted(API_JOB_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _load_json(path)
        if isinstance(data, dict):
            data["snapshot_path"] = str(path)
            jobs.append(data)
    return jobs


def _load_export_events() -> List[Dict[str, Any]]:
    if not API_EVENT_ROOT.exists():
        return []
    events: List[Dict[str, Any]] = []
    for path in sorted(API_EVENT_ROOT.glob("export_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _load_json(path)
        if isinstance(data, dict):
            data["snapshot_path"] = str(path)
            events.append(data)
    return events


def _load_research_sessions() -> List[Dict[str, Any]]:
    if not RESEARCH_SESSION_ROOT.exists():
        return []
    sessions: List[Dict[str, Any]] = []
    for path in sorted(RESEARCH_SESSION_ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = _load_json(path)
        if isinstance(data, dict):
            data["snapshot_path"] = str(path)
            sessions.append(data)
    return sessions


def _load_experiment_runs(limit: int) -> List[Dict[str, Any]]:
    if not EXPERIMENT_RUNS_ROOT.exists():
        return []
    runs: List[Dict[str, Any]] = []
    for run_dir in sorted(
        [path for path in EXPERIMENT_RUNS_ROOT.iterdir() if path.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        summary_path = run_dir / "reports" / "summary.json"
        summary = _load_json(summary_path) if summary_path.exists() else {}
        failures = summary.get("failures") if isinstance(summary, dict) else []
        runs.append(
            {
                "run_id": run_dir.name,
                "updated_at": datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(timespec="seconds"),
                "completed": (run_dir / "DONE.txt").exists(),
                "all_ok": bool(summary.get("all_ok")) if isinstance(summary, dict) else False,
                "has_failures": bool(failures),
                "step_count": len(summary.get("steps") or []) if isinstance(summary, dict) else 0,
                "failure_count": len(failures) if isinstance(failures, list) else 0,
                "summary_path": str(summary_path) if summary_path.exists() else None,
            }
        )
    return runs


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _counter_payload(counter: Counter) -> List[Dict[str, Any]]:
    return [{"label": label, "count": count} for label, count in counter.most_common()]


def _research_summary_value(session: Dict[str, Any], key: str) -> int:
    research = session.get("research")
    summary = research.get("summary") if isinstance(research, dict) else None
    value = summary.get(key) if isinstance(summary, dict) else 0
    try:
        return int(value or 0)
    except Exception:
        return 0


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            pass
    return datetime.fromtimestamp(0)
