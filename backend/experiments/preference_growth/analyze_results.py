from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

EXPERIMENT_ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(EXPERIMENT_ROOT / "local" / ".matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(EXPERIMENT_ROOT / "local" / ".cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load_rows(run_dir: Path) -> list[dict]:
    rows = []
    for path in sorted((run_dir / "personas").glob("*/round_*/*.json")):
        if path.name not in {"control.json", "treatment.json"}:
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        evaluation_path = path.with_name(path.stem + ".blind_evaluation.json")
        evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else {}
        round_name = path.parent.name
        rows.append({
            "persona": path.parent.parent.name,
            "round": int(round_name.split("_", 2)[1]),
            "material": round_name.split("_", 2)[2],
            "condition": record["condition"],
            "memory_count": int(record.get("memory_count") or 0),
            **record["metrics"],
            "preference_fit": evaluation.get("preference_fit"),
            "content_fidelity": evaluation.get("content_fidelity"),
            "naturalness": evaluation.get("naturalness"),
            "overapplication_count": evaluation.get("overapplication_count"),
            "missing_opportunity_count": evaluation.get("missing_opportunity_count"),
        })
    return rows


def write_csv(rows: list[dict], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def paired_summary(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for row in rows:
        grouped[(row["persona"], row["round"])][row["condition"]] = row
    pairs = []
    for (persona, round_index), conditions in sorted(grouped.items()):
        if "control" not in conditions or "treatment" not in conditions:
            continue
        control = conditions["control"]
        treatment = conditions["treatment"]
        baseline = float(control["mean_sentence_edit_burden"])
        treated = float(treatment["mean_sentence_edit_burden"])
        reduction = (baseline - treated) / baseline if baseline else 0.0
        pairs.append({
            "persona": persona,
            "round": round_index,
            "control_edit_burden": baseline,
            "treatment_edit_burden": treated,
            "relative_reduction": round(reduction, 4),
            "control_edited_rate": control["edited_sentence_rate"],
            "treatment_edited_rate": treatment["edited_sentence_rate"],
            "memory_count": treatment["memory_count"],
            "control_preference_fit": control.get("preference_fit"),
            "treatment_preference_fit": treatment.get("preference_fit"),
            "control_overapplication": control.get("overapplication_count"),
            "treatment_overapplication": treatment.get("overapplication_count"),
        })
    return pairs


def plot(rows: list[dict], destination: Path) -> None:
    personas = sorted({row["persona"] for row in rows})
    fig, axes = plt.subplots(len(personas), 1, figsize=(8, max(3.4, 3.2 * len(personas))), squeeze=False)
    for axis, persona in zip(axes[:, 0], personas):
        subset = [row for row in rows if row["persona"] == persona]
        for condition, marker in (("control", "o"), ("treatment", "s")):
            values = sorted((row for row in subset if row["condition"] == condition), key=lambda row: row["round"])
            axis.plot(
                [row["round"] for row in values],
                [row["mean_sentence_edit_burden"] for row in values],
                marker=marker,
                label=condition,
            )
        axis.set_title(persona)
        axis.set_xlabel("Usage round")
        axis.set_ylabel("Edit burden")
        axis.set_xticks(sorted({row["round"] for row in subset}))
        axis.grid(alpha=0.25)
        axis.legend()
    fig.suptitle("Preference memory pilot: editing burden")
    fig.tight_layout()
    fig.savefig(destination, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_report(run_dir: Path, rows: list[dict], pairs: list[dict]) -> None:
    report = run_dir / "reports" / "summary.md"
    lines = [
        "# Preference growth pilot results",
        "",
        "> この結果は合成教材・模擬ユーザによる予備実験であり、実ユーザへの一般化や教育効果を示さない。",
        "",
        "## Paired comparison",
        "",
        "| Persona | Round | Control burden | Treatment burden | Relative reduction | Preference fit C→T | Overapply C→T | Memories |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in pairs:
        lines.append(
            f"| {row['persona']} | {row['round']} | {row['control_edit_burden']:.4f} | "
            f"{row['treatment_edit_burden']:.4f} | {row['relative_reduction']:.1%} | "
            f"{row['control_preference_fit']}→{row['treatment_preference_fit']} | "
            f"{row['control_overapplication']}→{row['treatment_overapplication']} | {row['memory_count']} |"
        )
    if pairs:
        mean_reduction = sum(row["relative_reduction"] for row in pairs) / len(pairs)
        lines.extend(["", f"Paired observations: {len(pairs)}. Mean relative reduction: {mean_reduction:.1%}."])
    lines.extend([
        "",
        "## Interpretation constraints",
        "",
        "- 生成の非決定性があるため、単一生成の差を因果効果と断定しない。",
        "- 主要指標は編集距離。LLMによる質評価は補助指標として扱う。",
        "- 本パイロットの目的は実装成立性と失敗モードの発見である。",
        "- 本実験では反復生成、順序ランダム化、実ユーザ、複数評価者を追加する。",
    ])
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    rows = load_rows(run_dir)
    if not rows:
        raise SystemExit("no experiment records found")
    pairs = paired_summary(rows)
    reports = run_dir / "reports"
    write_csv(rows, reports / "condition_metrics.csv")
    write_csv(pairs, reports / "paired_comparison.csv")
    plot(rows, reports / "editing_burden.png")
    write_report(run_dir, rows, pairs)
    print(reports)


if __name__ == "__main__":
    main()
