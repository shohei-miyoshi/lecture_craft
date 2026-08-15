from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

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
        raise ValueError("judge response did not contain JSON")
    return json.loads(text[start:end + 1])


def judge(*, script: list[dict[str, Any]], material: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    payload = [{"slide_idx": row.get("slide_idx"), "text": row.get("text")} for row in script]
    prompt = (
        "以下の講義台本を、提示された教材内容と模擬ユーザ方針に照らして評価してください。"
        "生成条件名や比較相手はありません。教材にない事実を好みのために追加していないかも確認してください。"
        "JSON以外は出力しません。\n\n"
        f"教材: {json.dumps(material['slides'], ensure_ascii=False)}\n"
        f"ユーザ方針: {persona['private_editing_policy']}\n"
        f"台本: {json.dumps(payload, ensure_ascii=False)}\n\n"
        '出力: {"preference_fit":1-5,"content_fidelity":1-5,"naturalness":1-5,'
        '"overapplication_count":0以上の整数,"missing_opportunity_count":0以上の整数,'
        '"brief_reason":"短い根拠"}'
    )
    _response, text = call_responses_text(
        create_client(),
        modelname=os.getenv("LECTURE_CRAFT_MODEL_EXPERIMENT_JUDGE", auto_config.API_MODEL_EXPLANATION),
        messages=[
            build_responses_system_message("条件を推測せず、単独の台本として厳格かつ一貫して評価してください。"),
            build_responses_user_message(prompt),
        ],
    )
    return json_object(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    personas = {row["id"]: row for row in config["personas"]}
    materials = {row["id"]: row for row in config["materials"]}
    candidates = []
    for path in (run_dir / "personas").glob("*/round_*/*.json"):
        if path.name not in {"control.json", "treatment.json"}:
            continue
        candidates.append(path)
    candidates.sort(key=lambda path: hashlib.sha256(str(path).encode()).hexdigest())
    for path in candidates:
        output = path.with_name(path.stem + ".blind_evaluation.json")
        if output.exists():
            print(f"[resume] {output}", flush=True)
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        persona_id = path.parent.parent.name
        material_id = path.parent.name.split("_", 2)[2]
        evaluation = judge(
            script=record["generated"].get("sentences") or [],
            material=materials[material_id],
            persona=personas[persona_id],
        )
        output.write_text(json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8")
        print(output, flush=True)


if __name__ == "__main__":
    main()
