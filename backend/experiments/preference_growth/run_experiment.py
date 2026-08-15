from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from app.cache import build_generate_cache_plan  # noqa: E402
from app.models import GenerateRequest  # noqa: E402
from app.preference_memory import induce_preference_from_edit, normalized_edit_distance  # noqa: E402
from app.service import generate_media  # noqa: E402
from auto_lecture import config as auto_config  # noqa: E402
from auto_lecture.gpt_client import create_client  # noqa: E402
from auto_lecture.gpt_utils import (  # noqa: E402
    build_responses_system_message,
    build_responses_user_message,
    call_responses_text,
)


def json_object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("response did not contain JSON object")
    value = json.loads(text[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("response JSON must be an object")
    return value


def assert_isolated(path: Path) -> Path:
    resolved = path.resolve()
    local_root = (EXPERIMENT_ROOT / "local").resolve()
    if resolved != local_root and local_root not in resolved.parents:
        raise RuntimeError(f"experiment output must stay under {local_root}: {resolved}")
    return resolved


def configure_isolated_runtime(run_dir: Path) -> None:
    run_dir = assert_isolated(run_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{run_dir / 'db' / 'experiment.sqlite3'}"
    os.environ["LECTURE_CRAFT_STORAGE_ROOT"] = str(run_dir / "storage")
    os.environ["LECTURE_CRAFT_PIPELINE_OUTPUTS_ROOT"] = str(run_dir / "pipeline_outputs")
    for key in ("DATABASE_URL", "LECTURE_CRAFT_STORAGE_ROOT", "LECTURE_CRAFT_PIPELINE_OUTPUTS_ROOT"):
        value = os.environ[key]
        path = Path(value.removeprefix("sqlite:///")).resolve()
        if (EXPERIMENT_ROOT / "local").resolve() not in path.parents:
            raise RuntimeError(f"unsafe experiment path in {key}: {value}")


def call_json(prompt: str, system: str) -> dict[str, Any]:
    _response, text = call_responses_text(
        create_client(),
        modelname=os.getenv("LECTURE_CRAFT_MODEL_EXPERIMENT", auto_config.API_MODEL_EXPLANATION),
        messages=[
            build_responses_system_message(system),
            build_responses_user_message(prompt),
        ],
    )
    return json_object(text)


def simulate_user_edit(sentences: list[dict[str, Any]], persona: dict[str, Any]) -> dict[str, Any]:
    compact = [
        {"id": row.get("id"), "slide_idx": row.get("slide_idx"), "text": row.get("text")}
        for row in sentences
    ]
    prompt = (
        "あなたはLectureCraftを利用する模擬ユーザです。以下の非公開編集方針に従い、"
        "実際に利用できる講義台本へ必要な箇所だけを編集してください。"
        "方針を機械的に全文章へ適用せず、すでに満たす文は変更しません。"
        "内容訂正や局所変更を行う場合はpreferenceと区別してください。JSON以外は出力しません。\n\n"
        f"非公開編集方針: {persona['private_editing_policy']}\n"
        f"台本: {json.dumps(compact, ensure_ascii=False)}\n\n"
        '出力: {"edits":[{"id":"...","updated_text":"...",'
        '"category":"preference|content_correction|local_instruction|typo",'
        '"reason":"..."}],"usable_as_final":true|false}'
    )
    result = call_json(prompt, "固定された模擬ユーザ役として、最小限で一貫した編集を行ってください。")
    by_id = {str(row.get("id")): row for row in sentences}
    edits = []
    edited = [dict(row) for row in sentences]
    edited_by_id = {str(row.get("id")): row for row in edited}
    for edit in result.get("edits") or []:
        if not isinstance(edit, dict):
            continue
        sentence_id = str(edit.get("id") or "")
        updated = str(edit.get("updated_text") or "").strip()
        if sentence_id not in by_id or not updated:
            continue
        before = str(by_id[sentence_id].get("text") or "")
        if before == updated:
            continue
        edited_by_id[sentence_id]["text"] = updated
        edits.append({
            "id": sentence_id,
            "slide_idx": by_id[sentence_id].get("slide_idx"),
            "before": before,
            "after": updated,
            "gold_category": edit.get("category"),
            "reason": edit.get("reason"),
            "edit_distance": normalized_edit_distance(before, updated),
        })
    return {"sentences": edited, "edits": edits, "usable_as_final": bool(result.get("usable_as_final", True))}


def extract_memories(edits: list[dict[str, Any]], *, context: dict[str, Any]) -> list[dict[str, Any]]:
    memories = []
    for edit in edits:
        inferred = induce_preference_from_edit(
            before={"text": edit["before"]},
            after={"text": edit["after"]},
            slide_context={**context, "slide_idx": edit.get("slide_idx")},
        )
        memories.append({**inferred, "gold_category": edit.get("gold_category"), "edit_reason": edit.get("reason")})
    return memories


def generation_request(config: dict[str, Any], *, run_id: str, job_id: str, memories: list[dict[str, Any]]) -> GenerateRequest:
    return GenerateRequest(
        filename=f"{run_id}.pdf",
        detail=config["detail"],
        difficulty=config["difficulty"],
        mode=config["mode"],
        generation_run_id=run_id,
        generation_job_id=job_id,
        script_review_enabled=True,
        generation_conditions={
            "kg_mode": config["kg_mode"],
            "log_reuse_enabled": bool(memories),
            "prompt_strategy_version": "preference_growth_pilot_v1",
        },
        correction_memories=memories,
    )


def generate_condition(
    config: dict[str, Any],
    pdf_bytes: bytes,
    *,
    condition: str,
    memories: list[dict[str, Any]],
    canonical_kg: Path | None = None,
) -> tuple[dict[str, Any], GenerateRequest, Path]:
    token = uuid.uuid4().hex[:12]
    req = generation_request(config, run_id=f"exp_run_{token}", job_id=f"exp_job_{token}", memories=memories)
    plan = build_generate_cache_plan(req, pdf_bytes)
    kg_path = Path(plan.output_root_name) / "pre_generation_knowledge_graph.json"
    if canonical_kg is not None:
        kg_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(canonical_kg, kg_path)
    response = generate_media(
        req,
        pdf_bytes=pdf_bytes,
        progress_callback=lambda progress, message: print(f"[{condition}] {progress:3d}% {message}", flush=True),
    )
    if not kg_path.exists():
        raise RuntimeError("KG was not generated")
    return response, req, kg_path


def condition_metrics(original: list[dict[str, Any]], edited_result: dict[str, Any]) -> dict[str, Any]:
    edits = edited_result["edits"]
    sentence_count = max(1, len(original))
    weighted_distance = sum(float(row["edit_distance"]) for row in edits) / sentence_count
    return {
        "sentence_count": len(original),
        "edited_sentence_count": len(edits),
        "edited_sentence_rate": round(len(edits) / sentence_count, 4),
        "mean_sentence_edit_burden": round(weighted_distance, 4),
        "usable_as_final": edited_result["usable_as_final"],
    }


def load_record(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def record_kg_path(record: dict[str, Any], round_dir: Path) -> Path:
    path = round_dir / "canonical_kg.json"
    if not path.exists():
        graph = record.get("generated", {}).get("knowledge_graph")
        if not isinstance(graph, dict) or not graph.get("nodes"):
            raise RuntimeError("completed control record has no reusable KG")
        path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-id", default=datetime.now().strftime("pilot-%Y%m%d-%H%M%S"))
    parser.add_argument("--personas", nargs="*", help="optional persona ids")
    parser.add_argument("--stop-after-round", type=int, help="checkpoint/resume verification")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    run_dir = assert_isolated(EXPERIMENT_ROOT / "local" / args.run_id)
    configure_isolated_runtime(run_dir)
    fixtures_dir = run_dir / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    from generate_fixtures import render_material
    for material in config["materials"]:
        render_material(material, fixtures_dir / f"{material['id']}.pdf")
    (run_dir / "config.snapshot.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    selected = set(args.personas or [])
    personas = [row for row in config["personas"] if not selected or row["id"] in selected]
    for persona in personas:
        persona_dir = run_dir / "personas" / persona["id"]
        accumulated: list[dict[str, Any]] = []
        for round_index in range(1, int(config["rounds"]) + 1):
            if args.stop_after_round and round_index > args.stop_after_round:
                break
            material = config["materials"][round_index - 1]
            round_dir = persona_dir / f"round_{round_index:02d}_{material['id']}"
            round_dir.mkdir(parents=True, exist_ok=True)
            pdf_bytes = (fixtures_dir / f"{material['id']}.pdf").read_bytes()
            control_path = round_dir / "control.json"
            control_record = load_record(control_path)
            if control_record is None:
                control, _control_req, control_kg = generate_condition(
                    config, pdf_bytes, condition="control", memories=[]
                )
                control_edit = simulate_user_edit(control.get("sentences") or [], persona)
                control_record = {
                    "condition": "control",
                    "generated": control,
                    "edited": control_edit,
                    "metrics": condition_metrics(control.get("sentences") or [], control_edit),
                }
                control_path.write_text(json.dumps(control_record, ensure_ascii=False, indent=2), encoding="utf-8")
                shutil.copy2(control_kg, round_dir / "canonical_kg.json")
            else:
                print(f"[resume] {control_path}", flush=True)
                control = control_record["generated"]
                control_edit = control_record["edited"]
                control_kg = record_kg_path(control_record, round_dir)

            if round_index == 1:
                memory_path = round_dir / "learned_memories.json"
                learned = (
                    json.loads(memory_path.read_text(encoding="utf-8"))
                    if memory_path.exists()
                    else extract_memories(
                        control_edit["edits"],
                        context={"mode": config["mode"], "difficulty": config["difficulty"], "detail": config["detail"]},
                    )
                )
                accumulated.extend(row for row in learned if row.get("preference_kind") == "preference" and row.get("preference_text"))
                memory_path.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")
                continue

            treatment_path = round_dir / "treatment.json"
            treatment_record = load_record(treatment_path)
            if treatment_record is None:
                treatment, _treatment_req, treatment_kg = generate_condition(
                    config,
                    pdf_bytes,
                    condition="treatment",
                    memories=accumulated,
                    canonical_kg=control_kg,
                )
                if control_kg.read_bytes() != treatment_kg.read_bytes():
                    raise RuntimeError("control and treatment did not use identical KG")
                treatment_edit = simulate_user_edit(treatment.get("sentences") or [], persona)
                treatment_record = {
                    "condition": "treatment",
                    "memory_count": len(accumulated),
                    "generated": treatment,
                    "edited": treatment_edit,
                    "metrics": condition_metrics(treatment.get("sentences") or [], treatment_edit),
                }
                treatment_path.write_text(json.dumps(treatment_record, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                print(f"[resume] {treatment_path}", flush=True)
                treatment_edit = treatment_record["edited"]
            memory_path = round_dir / "learned_memories.json"
            learned = (
                json.loads(memory_path.read_text(encoding="utf-8"))
                if memory_path.exists()
                else extract_memories(
                    treatment_edit["edits"],
                    context={"mode": config["mode"], "difficulty": config["difficulty"], "detail": config["detail"]},
                )
            )
            accumulated.extend(row for row in learned if row.get("preference_kind") == "preference" and row.get("preference_text"))
            memory_path.write_text(json.dumps(learned, ensure_ascii=False, indent=2), encoding="utf-8")
        (persona_dir / "memory_final.json").write_text(json.dumps(accumulated, ensure_ascii=False, indent=2), encoding="utf-8")
    print(run_dir)


if __name__ == "__main__":
    main()
