from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from .cache import API_EVENT_ROOT, API_JOB_ROOT, RESEARCH_SESSION_ROOT


def build_admin_overview(limit: int = 12) -> Dict[str, Any]:
    jobs = _load_job_snapshots()
    exports = _load_export_events()
    research_sessions = _load_research_sessions()

    now = datetime.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    jobs_24h = [job for job in jobs if _parse_dt(job.get("created_at")) >= last_24h]
    jobs_7d = [job for job in jobs if _parse_dt(job.get("created_at")) >= last_7d]
    jobs_30d = [job for job in jobs if _parse_dt(job.get("created_at")) >= last_30d]
    export_7d = [event for event in exports if _parse_dt(event.get("created_at")) >= last_7d]

    mode_counter = Counter(str((job.get("payload") or {}).get("mode") or "unknown") for job in jobs)
    status_counter = Counter(str(job.get("status") or "unknown") for job in jobs)
    export_counter = Counter(str(event.get("export_type") or "unknown") for event in exports)
    export_status_counter = Counter(str(event.get("status") or "unknown") for event in exports)
    research_trigger_counter = Counter(str(session.get("trigger") or "unknown") for session in research_sessions)
    research_mode_counter = Counter(str(session.get("mode") or "unknown") for session in research_sessions)

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

    research_analytics = _collect_research_analytics(research_sessions)

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
            "unique_materials": len(research_analytics["unique_materials"]),
            "unique_generation_keys": len(research_analytics["unique_generation_keys"]),
            "operation_logs_total": research_analytics["operation_logs_total"],
            "study_events_total": research_analytics["study_events_total"],
        },
        "breakdowns": {
            "jobs_by_mode": _counter_payload(mode_counter),
            "jobs_by_status": _counter_payload(status_counter),
            "exports_by_type": _counter_payload(export_counter),
            "exports_by_status": _counter_payload(export_status_counter),
            "research_by_trigger": _counter_payload(research_trigger_counter),
            "research_by_mode": _counter_payload(research_mode_counter),
            "operation_types": _counter_payload(research_analytics["operation_type_counter"]),
            "study_event_types": _counter_payload(research_analytics["study_event_counter"]),
            "sentence_change_fields": _counter_payload(research_analytics["sentence_field_counter"]),
            "highlight_change_fields": _counter_payload(research_analytics["highlight_field_counter"]),
        },
        "activity": {
            "last_14_days": _build_daily_activity(jobs, exports, research_sessions, days=14),
        },
        "recent_jobs": jobs[:limit],
        "recent_exports": exports[:limit],
        "research": {
            "total_sessions": len(research_sessions),
            "summary_totals": research_summary_totals,
            "recent_sessions": research_analytics["recent_sessions"][:limit],
            "analytics": {
                "avg_operation_logs_per_session": research_analytics["avg_operation_logs_per_session"],
                "avg_study_events_per_session": research_analytics["avg_study_events_per_session"],
                "avg_active_minutes_per_session": research_analytics["avg_active_minutes_per_session"],
                "sessions_with_sentence_edits": research_analytics["sessions_with_sentence_edits"],
                "sessions_with_highlight_edits": research_analytics["sessions_with_highlight_edits"],
                "sessions_with_exports": research_analytics["sessions_with_exports"],
                "top_slide_activity": research_analytics["top_slide_activity"],
            },
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


def _get_operation_logs(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = session.get("operation_logs")
    return rows if isinstance(rows, list) else []


def _get_study_events(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    research = session.get("research")
    rows = research.get("events") if isinstance(research, dict) else []
    return rows if isinstance(rows, list) else []


def _get_feedback_bucket(session: Dict[str, Any], key: str) -> Dict[str, Any]:
    research = session.get("research")
    feedback = research.get("feedback") if isinstance(research, dict) else None
    bucket = feedback.get(key) if isinstance(feedback, dict) else None
    return bucket if isinstance(bucket, dict) else {}


def _collect_research_analytics(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    operation_type_counter: Counter = Counter()
    study_event_counter: Counter = Counter()
    sentence_field_counter: Counter = Counter()
    highlight_field_counter: Counter = Counter()
    slide_activity_counter: Counter = Counter()

    unique_materials = set()
    unique_generation_keys = set()
    operation_logs_total = 0
    study_events_total = 0
    session_minutes_total = 0.0
    sessions_with_sentence_edits = 0
    sessions_with_highlight_edits = 0
    sessions_with_exports = 0

    enriched_sessions: List[Dict[str, Any]] = []

    for session in sessions:
        operation_logs = _get_operation_logs(session)
        study_events = _get_study_events(session)
        sentence_feedback = _get_feedback_bucket(session, "sentences")
        highlight_feedback = _get_feedback_bucket(session, "highlights")
        summary = (session.get("research") or {}).get("summary") if isinstance(session.get("research"), dict) else {}

        operation_logs_total += len(operation_logs)
        study_events_total += len(study_events)

        for row in operation_logs:
            meta = row.get("meta") if isinstance(row, dict) else None
            operation_type_counter[str((meta or {}).get("type") or "unknown")] += 1
            _count_slide_activity(slide_activity_counter, (meta or {}).get("slide_idx"))

        for row in study_events:
            study_event_counter[str(row.get("kind") or "unknown")] += 1
            payload = row.get("payload") if isinstance(row, dict) else None
            _count_slide_activity(slide_activity_counter, (payload or {}).get("slide_idx"))

        sentence_modified = sentence_feedback.get("modified") if isinstance(sentence_feedback, dict) else []
        highlight_modified = highlight_feedback.get("modified") if isinstance(highlight_feedback, dict) else []
        for row in sentence_modified if isinstance(sentence_modified, list) else []:
            for field in row.get("changed_fields") or []:
                sentence_field_counter[str(field)] += 1
            before = row.get("before") if isinstance(row, dict) else None
            after = row.get("after") if isinstance(row, dict) else None
            _count_slide_activity(slide_activity_counter, (before or {}).get("slide_idx"))
            _count_slide_activity(slide_activity_counter, (after or {}).get("slide_idx"))
        for row in highlight_modified if isinstance(highlight_modified, list) else []:
            for field in row.get("changed_fields") or []:
                highlight_field_counter[str(field)] += 1
            before = row.get("before") if isinstance(row, dict) else None
            after = row.get("after") if isinstance(row, dict) else None
            _count_slide_activity(slide_activity_counter, (before or {}).get("slide_idx"))
            _count_slide_activity(slide_activity_counter, (after or {}).get("slide_idx"))

        if _research_summary_int(summary, "sentences_modified") or _research_summary_int(summary, "sentences_added") or _research_summary_int(summary, "sentences_removed"):
            sessions_with_sentence_edits += 1
        if _research_summary_int(summary, "highlights_modified") or _research_summary_int(summary, "highlights_added") or _research_summary_int(summary, "highlights_removed"):
            sessions_with_highlight_edits += 1

        research = session.get("research")
        export_info = research.get("export") if isinstance(research, dict) else None
        if isinstance(export_info, dict):
            sessions_with_exports += 1

        generation_ref = session.get("generation_ref")
        if isinstance(generation_ref, dict):
            cache_key = generation_ref.get("cache_key")
            material_name = generation_ref.get("material_name")
            if cache_key:
                unique_generation_keys.add(str(cache_key))
            if material_name:
                unique_materials.add(str(material_name))

        active_minutes = _estimate_session_minutes(session)
        session_minutes_total += active_minutes

        enriched_sessions.append(
            {
                **session,
                "metrics": {
                    "operation_log_count": len(operation_logs),
                    "study_event_count": len(study_events),
                    "active_minutes": round(active_minutes, 1),
                    "sentence_edit_count": (
                        _research_summary_int(summary, "sentences_modified")
                        + _research_summary_int(summary, "sentences_added")
                        + _research_summary_int(summary, "sentences_removed")
                    ),
                    "highlight_edit_count": (
                        _research_summary_int(summary, "highlights_modified")
                        + _research_summary_int(summary, "highlights_added")
                        + _research_summary_int(summary, "highlights_removed")
                    ),
                    "export_type": export_info.get("type") if isinstance(export_info, dict) else None,
                },
            }
        )

    session_count = max(1, len(sessions))
    top_slide_activity = [
        {"label": f"スライド{index + 1}", "count": count, "slide_idx": index}
        for index, count in slide_activity_counter.most_common(8)
    ]

    return {
        "operation_type_counter": operation_type_counter,
        "study_event_counter": study_event_counter,
        "sentence_field_counter": sentence_field_counter,
        "highlight_field_counter": highlight_field_counter,
        "top_slide_activity": top_slide_activity,
        "unique_materials": unique_materials,
        "unique_generation_keys": unique_generation_keys,
        "operation_logs_total": operation_logs_total,
        "study_events_total": study_events_total,
        "avg_operation_logs_per_session": round(operation_logs_total / session_count, 1),
        "avg_study_events_per_session": round(study_events_total / session_count, 1),
        "avg_active_minutes_per_session": round(session_minutes_total / session_count, 1),
        "sessions_with_sentence_edits": sessions_with_sentence_edits,
        "sessions_with_highlight_edits": sessions_with_highlight_edits,
        "sessions_with_exports": sessions_with_exports,
        "recent_sessions": enriched_sessions,
    }


def _research_summary_int(summary: Any, key: str) -> int:
    value = summary.get(key) if isinstance(summary, dict) else 0
    try:
        return int(value or 0)
    except Exception:
        return 0


def _count_slide_activity(counter: Counter, slide_idx: Any) -> None:
    try:
        if slide_idx is None:
            return
        counter[int(slide_idx)] += 1
    except Exception:
        return


def _estimate_session_minutes(session: Dict[str, Any]) -> float:
    stamps = []
    for row in _get_operation_logs(session):
        stamps.append(_parse_dt(row.get("at")))
    for row in _get_study_events(session):
        stamps.append(_parse_dt(row.get("at")))
    stamps.append(_parse_dt(session.get("saved_at")))
    stamps = [dt for dt in stamps if dt.timestamp() > 0]
    if len(stamps) < 2:
        return 0.0
    return max(0.0, (max(stamps) - min(stamps)).total_seconds() / 60.0)


def _build_daily_activity(
    jobs: List[Dict[str, Any]],
    exports: List[Dict[str, Any]],
    sessions: List[Dict[str, Any]],
    *,
    days: int = 14,
) -> List[Dict[str, Any]]:
    today = datetime.now().date()
    rows: Dict[str, Dict[str, Any]] = {}
    for offset in range(days - 1, -1, -1):
        date_key = (today - timedelta(days=offset)).isoformat()
        rows[date_key] = {
            "date": date_key,
            "label": date_key[5:],
            "jobs": 0,
            "exports": 0,
            "research": 0,
            "total": 0,
        }

    for item in jobs:
        key = _parse_dt(item.get("created_at")).date().isoformat()
        if key in rows:
            rows[key]["jobs"] += 1
            rows[key]["total"] += 1
    for item in exports:
        key = _parse_dt(item.get("created_at")).date().isoformat()
        if key in rows:
            rows[key]["exports"] += 1
            rows[key]["total"] += 1
    for item in sessions:
        key = _parse_dt(item.get("saved_at")).date().isoformat()
        if key in rows:
            rows[key]["research"] += 1
            rows[key]["total"] += 1

    return list(rows.values())
