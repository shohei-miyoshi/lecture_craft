from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def one_line(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a local, inspectable experiment-process report.")
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    persona_root = run_dir / "personas"
    if not persona_root.exists():
        raise SystemExit("personas directory not found")

    lines = [
        "# Preference growth: experiment process data",
        "",
        "> This local report contains raw simulated edits. It is intentionally excluded from Git.",
        "",
    ]
    index: list[dict[str, Any]] = []
    for persona_dir in sorted(path for path in persona_root.iterdir() if path.is_dir()):
        lines.extend([f"## {persona_dir.name}", ""])
        for round_dir in sorted(persona_dir.glob("round_*")):
            round_label = round_dir.name
            lines.extend([f"### {round_label}", ""])
            memories = load_json(round_dir / "learned_memories.json") if (round_dir / "learned_memories.json").exists() else []
            for record_path in [round_dir / "control.json", round_dir / "treatment.json"]:
                if not record_path.exists():
                    continue
                record = load_json(record_path)
                condition = record_path.stem
                metrics = record.get("metrics") or {}
                edits = ((record.get("edited") or {}).get("edits") or [])
                blind_path = record_path.with_name(f"{condition}.blind_evaluation.json")
                blind = load_json(blind_path) if blind_path.exists() else {}
                lines.extend([
                    f"#### {condition}",
                    "",
                    f"- memory count at generation: {record.get('memory_count', 0)}",
                    f"- edit burden: {metrics.get('mean_sentence_edit_burden')}",
                    f"- edited sentences: {metrics.get('edited_sentence_count')} / {metrics.get('sentence_count')}",
                    f"- blind evaluation: {one_line(json.dumps(blind, ensure_ascii=False)) if blind else 'not evaluated'}",
                    "",
                ])
                if edits:
                    lines.extend([
                        "| # | Slide | Before | After | Reason | Gold category | Extracted preference | Kind / scope |",
                        "|---:|---:|---|---|---|---|---|---|",
                    ])
                    for i, edit in enumerate(edits, 1):
                        inferred = memories[i - 1] if i <= len(memories) and condition == ("control" if "round_01_" in round_label else "treatment") else {}
                        lines.append(
                            f"| {i} | {edit.get('slide_idx')} | {one_line(edit.get('before'))} | "
                            f"{one_line(edit.get('after'))} | {one_line(edit.get('reason'))} | "
                            f"{one_line(edit.get('gold_category'))} | {one_line(inferred.get('preference_text')) or '—'} | "
                            f"{one_line(inferred.get('preference_kind')) or '—'} / {one_line(inferred.get('preference_scope')) or '—'} |"
                        )
                        index.append({
                            "persona": persona_dir.name,
                            "round": round_label,
                            "condition": condition,
                            "edit": edit,
                            "inference": inferred,
                        })
                    lines.append("")
                else:
                    lines.extend(["No edit was required.", ""])

    report_dir = run_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "process_and_edit_examples.md"
    index_path = report_dir / "process_and_edit_examples.json"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)
    print(index_path)


if __name__ == "__main__":
    main()
