from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence, Tuple

import networkx as nx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from auto_lecture import config as auto_config
from auto_lecture.gpt_client import create_client
from auto_lecture.gpt_utils import (
    build_responses_system_message,
    build_responses_user_message,
    call_responses_text,
)

from .models import KgPreviewCompareRequest, KgPreviewRequest
from .service import ApiError, ensure_pdf_images, ensure_pdf_upload, short_id, timestamp_slug


CATALOG_ROOT = PROJECT_ROOT / "outputs" / "kg_preview" / "catalog"
DEFAULT_CATALOG_LIMIT = 24
MAX_COMPARE_VARIANTS = 3


KG_PROMPT_TEMPLATE = """[SYSTEM]
You are an expert knowledge graph builder for university-level courses. Your task is to extract **core prerequisite concepts** that represent the essential knowledge structure of the lecture.

[USER]
Extract prerequisite concept relationships from the **Target lecture** in **### Task → Input** and output them as directed triplets forming a **directed acyclic graph (DAG)**.

## Output format (STRICT)
- One triplet per line, exactly:
  (concept_A, Is-a-Prerequisite-of, concept_B)
- No numbering, no bullets, no headings, no extra text.
- Concept names must be written in **{LANGUAGE}**.
- If no valid prerequisite relationships exist, output exactly:
  None

## Scope (STRICT)
- Use **only** the content in **### Task → Input** to identify concepts and prerequisite edges.
- **### Examples** are **reference-only** to show the input/output pattern.

---

## Step 1 — Concept Extraction

### 1.1 What to INCLUDE
- The lecture's primary topic
- Parent category of the main topic
- Key subtypes or variants explained in detail
- Foundational concepts that the main topic builds upon
- Technical terms that are explicitly defined with explanation
- Broad category terms and intermediate hub concepts that connect multiple topics

### 1.2 What to EXCLUDE
- Combined concepts in the form "X の Y"
- Concepts that are only listed but not explained
- Action/operation words
- Implementation details
- Slide logistics such as まとめ or 演習
- Generic descriptive terms that do not carry instructional meaning

## Step 2 — Concept Naming
- Use the canonical textbook term in **{LANGUAGE}**
- Use noun phrases
- Merge surface variants referring to the same concept

## Step 3 — Prerequisite Edges (A → B)
Add edge **A → B** when **A is required to understand B**:
1. Definition dependency
2. Taxonomy
3. Foundation → Application
4. Component → System

**Direction**: Always from General → Specific, Foundation → Application

## Step 4 — DAG Constraint
- Output a graph with **no cycles**
- If a candidate edge would create a cycle, omit that edge

## Step 5 — Final Check
Before outputting, verify:
1. The lecture's main topic and its parent category are included
2. Key subtypes/variants are included
3. Foundational concepts are included
4. No "X の Y" combined concepts
5. Edge directions go from General → Specific

### Task
Course:
{COURSE_NAME}

Input:
{CONTENT}

Output:
"""


KG_EVIDENCE_PROMPT_TEMPLATE = """[SYSTEM]
You are enriching an existing prerequisite knowledge graph for a university lecture.

[USER]
You are given:
1. A lecture as slide images.
2. A baseline prerequisite knowledge graph that is already fixed.

Your job is to keep the baseline graph structure as-is and add evidence metadata that helps downstream explanation planning.

## Output format (STRICT)
Return a single JSON object only. Do not wrap it in markdown.

```json
{
  "nodes": [
    {
      "id": "concept name",
      "importance": 1,
      "slide_refs": [1],
      "evidence_text": ["short phrase from slide"]
    }
  ],
  "edges": [
    {
      "source": "concept A",
      "target": "concept B",
      "relation": "Is-a-Prerequisite-of",
      "slide_refs": [1],
      "evidence_text": ["short phrase from slide"],
      "rationale": "why A is needed before B"
    }
  ],
  "notes": ["optional short note"]
}
```

## Important constraints
- Keep node IDs and edge endpoints exactly consistent with the baseline graph below.
- Do not add new nodes.
- Do not add new edges.
- `importance` is an integer from 1 to 5.
- `slide_refs` are 1-based slide numbers.
- `evidence_text` should contain short phrases copied or closely paraphrased from the slide content.
- `rationale` should be one short sentence in **{LANGUAGE}**.
- If evidence is weak, keep `slide_refs` / `evidence_text` empty rather than inventing.

## Baseline graph
{BASELINE_GRAPH}

## Task
Course:
{COURSE_NAME}

Input:
{CONTENT}

Output:
"""


KG_MULTIREL_PROMPT_TEMPLATE = """[SYSTEM]
You are converting a prerequisite graph into an explanation-oriented knowledge graph for a university lecture.

[USER]
You are given:
1. A lecture as slide images.
2. A fixed concept inventory from a baseline graph.

Your job is to build an explanation-oriented graph using only those concepts.

## Allowed relation labels
- Is-a-Prerequisite-of
- explains
- example_of
- contrasts_with
- part_of
- used_for
- step_before

## Output format (STRICT)
Return a single JSON object only. Do not wrap it in markdown.

```json
{
  "nodes": [
    {
      "id": "concept name",
      "importance": 3,
      "slide_refs": [1],
      "evidence_text": ["short phrase from slide"]
    }
  ],
  "edges": [
    {
      "source": "concept A",
      "target": "concept B",
      "relation": "explains",
      "slide_refs": [1],
      "evidence_text": ["short phrase from slide"],
      "rationale": "short explanation"
    }
  ],
  "notes": ["optional short note"]
}
```

## Important constraints
- Use only the concept inventory below.
- Do not invent new concepts.
- Use at most 18 edges.
- Prefer relations that help explanation planning, not only prerequisite structure.
- `importance` is an integer from 1 to 5.
- `slide_refs` are 1-based slide numbers.
- `rationale` should be one short sentence in **{LANGUAGE}**.

## Concept inventory
{CONCEPT_INVENTORY}

## Task
Course:
{COURSE_NAME}

Input:
{CONTENT}

Output:
"""


KG_ORDER_PROMPT_TEMPLATE = """[SYSTEM]
You are designing an explanation order for a university lecture from a fixed prerequisite graph.

[USER]
You are given:
1. A lecture as slide images.
2. A fixed prerequisite graph.

Your job is to propose a compact explanation order for downstream script generation.

## Output format (STRICT)
Return a single JSON object only. Do not wrap it in markdown.

```json
{
  "steps": [
    {
      "step": 1,
      "focus": "concept name",
      "related_concepts": ["concept A", "concept B"],
      "goal": "what to explain at this step",
      "why_now": "why this step comes here",
      "slide_refs": [1]
    }
  ],
  "notes": ["optional short note"]
}
```

## Important constraints
- Keep the number of steps between 3 and 8.
- `focus` must come from the prerequisite graph concepts.
- `related_concepts` must also come from the prerequisite graph concepts.
- `slide_refs` are 1-based slide numbers and can be empty if uncertain.
- `goal` and `why_now` should be short and written in **{LANGUAGE}**.

## Baseline graph
{BASELINE_GRAPH}

## Task
Course:
{COURSE_NAME}

Input:
{CONTENT}

Output:
"""


Triplet = Tuple[str, str, str]


@dataclass(frozen=True)
class KgVariantSpec:
    id: str
    label: str
    description: str
    kind: str
    runner: Callable[["KgRunContext", "KgVariantSpec"], Dict[str, Any]]
    enabled: bool = True


@dataclass
class KgRunContext:
    filename: str
    model_name: str
    course_name: str
    language: str
    material_name: str
    material_fingerprint: str
    image_paths: List[str]
    client: Any
    title: str
    project_id: str | None
    owner_user_id: str | None
    shared: Dict[str, Any]


def natural_sort_key(filename: str) -> List[Any]:
    text_value = str(filename)
    return [int(text) if text.isdigit() else text for text in re.split(r"(\d+)", text_value)]


def canonical_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fill_prompt_template(template: str, **values: Any) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", str(value))
    return rendered


def parse_triplets(response_text: str) -> List[Triplet]:
    triplets: List[Triplet] = []
    if response_text.strip().lower() == "none":
        return triplets

    pattern_with_parens = r"\(([^,()]+),\s*Is-a-Prerequisite-of,\s*([^)]+)\)"
    matches = re.findall(pattern_with_parens, response_text, re.IGNORECASE)
    if matches:
        for concept_a, concept_b in matches:
            left = canonical_text(concept_a)
            right = canonical_text(concept_b)
            if left and right and len(left) < 100 and len(right) < 100:
                triplets.append((left, "Is-a-Prerequisite-of", right))
        return triplets

    pattern_no_parens = r"^([^,]+),\s*Is-a-Prerequisite-of,\s*(.+)$"
    for line in response_text.splitlines():
        match = re.match(pattern_no_parens, line.strip(), re.IGNORECASE)
        if not match:
            continue
        left = canonical_text(match.group(1))
        right = canonical_text(match.group(2))
        if left and right and len(left) < 100 and len(right) < 100:
            triplets.append((left, "Is-a-Prerequisite-of", right))
    return triplets


def normalize_triplets(triplets: Sequence[Triplet]) -> Tuple[List[Triplet], Dict[str, int]]:
    seen = set()
    normalized: List[Triplet] = []
    removed_self_loops = 0
    removed_duplicates = 0

    for prerequisite, relation, dependent in triplets:
        left = canonical_text(prerequisite)
        rel = canonical_text(relation) or "Is-a-Prerequisite-of"
        right = canonical_text(dependent)
        if not left or not right:
            continue
        if left == right:
            removed_self_loops += 1
            continue
        key = (left, rel, right)
        if key in seen:
            removed_duplicates += 1
            continue
        seen.add(key)
        normalized.append(key)

    stats = {
        "removed_self_loops": removed_self_loops,
        "removed_duplicates": removed_duplicates,
    }
    return normalized, stats


def extract_json_object(text: str) -> Dict[str, Any]:
    source = str(text or "").strip()
    if not source:
        raise ValueError("empty response")

    candidates = [source]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", source, re.DOTALL | re.IGNORECASE)
    candidates.extend(fenced)

    brace_start = source.find("{")
    brace_end = source.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        candidates.append(source[brace_start:brace_end + 1])

    seen = set()
    for candidate in candidates:
        blob = candidate.strip()
        if not blob or blob in seen:
            continue
        seen.add(blob)
        try:
            parsed = json.loads(blob)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("JSON object could not be parsed")


def sanitize_slide_refs(values: Any, slide_count: int) -> List[int]:
    rows = []
    for value in values or []:
        try:
            number = int(value)
        except Exception:
            continue
        if 1 <= number <= slide_count and number not in rows:
            rows.append(number)
    return rows


def sanitize_evidence_text(values: Any, *, limit: int = 3) -> List[str]:
    rows: List[str] = []
    for value in values or []:
        text = canonical_text(value)
        if not text or text in rows:
            continue
        rows.append(text[:160])
        if len(rows) >= limit:
            break
    return rows


def sanitize_importance(value: Any) -> int | None:
    try:
        return max(1, min(int(value), 5))
    except Exception:
        return None


def sanitize_relation_label(value: Any) -> str:
    label = canonical_text(value)
    allowed = {
        "Is-a-Prerequisite-of",
        "explains",
        "example_of",
        "contrasts_with",
        "part_of",
        "used_for",
        "step_before",
    }
    return label if label in allowed else "Is-a-Prerequisite-of"


def check_dag(triplets: Sequence[Triplet]) -> Tuple[bool, List[List[str]]]:
    graph = nx.DiGraph()
    for prerequisite, _, dependent in triplets:
        graph.add_edge(prerequisite, dependent)
    is_dag = nx.is_directed_acyclic_graph(graph)
    if is_dag:
        return True, []
    try:
        return False, list(nx.simple_cycles(graph))
    except Exception:
        return False, []


def format_cycle_feedback(cycles: Sequence[Sequence[str]]) -> str:
    feedback = "\n\n⚠️ CRITICAL ERROR: Your knowledge graph contains cycles!\n\n"
    feedback += "A prerequisite knowledge graph MUST be a DAG (Directed Acyclic Graph).\n"
    feedback += "Cycles mean circular dependencies, which is logically impossible for prerequisite relationships.\n\n"
    feedback += f"Found {len(cycles)} cycle(s):\n\n"
    for index, cycle in enumerate(cycles[:5], start=1):
        feedback += f"{index}. {' → '.join(list(cycle) + [cycle[0]])}\n"
    if len(cycles) > 5:
        feedback += f"\n... and {len(cycles) - 5} more cycles\n"
    feedback += "\nPlease fix these cycles by correcting edge directions or removing incorrect edges.\n"
    feedback += "Output the CORRECTED knowledge graph triplets below (same format):\n"
    return feedback


def build_dot_text(title: str, triplets: Sequence[Triplet]) -> str:
    graph = nx.DiGraph()
    for prerequisite, relation, dependent in triplets:
        graph.add_edge(prerequisite, dependent, relation=relation)

    lines = [
        "digraph knowledge_graph {",
        '  graph [rankdir=TB, splines=ortho, nodesep=0.8, ranksep=1.2, bgcolor="white", labelloc="t", fontsize=20, fontname="Arial", label="%s"];'
        % title.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n"),
    ]

    for node in graph.nodes():
        in_degree = graph.in_degree(node)
        out_degree = graph.out_degree(node)
        if in_degree == 0:
            fillcolor = "#FFB6B6"
        elif out_degree == 0:
            fillcolor = "#B6E2FF"
        else:
            fillcolor = "#C8E6C9"
        label = f"{node}\\n[{in_degree}→{out_degree}]".replace("\\", "\\\\").replace('"', '\\"')
        lines.append(
            f'  "{node}" [label="{label}", style="filled", fillcolor="{fillcolor}", shape="box", fontname="Arial", fontsize=11, margin="0.2,0.1"];'
        )

    for prerequisite, _, dependent in triplets:
        lines.append(f'  "{prerequisite}" -> "{dependent}" [color="#666666", arrowsize="0.8", penwidth="1.5"];')

    lines.append("}")
    return "\n".join(lines) + "\n"


def render_graphviz_if_available(dot_path: Path) -> Dict[str, Any]:
    dot_binary = shutil.which("dot")
    if not dot_binary:
        return {"available": False, "reason": "Graphviz の dot コマンドが見つかりません"}

    outputs: Dict[str, Any] = {"available": True, "png": None, "svg": None}
    for fmt in ("png", "svg"):
        out_path = dot_path.with_suffix(f".{fmt}")
        try:
            subprocess.run(
                [dot_binary, f"-T{fmt}", str(dot_path), "-o", str(out_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            outputs[fmt] = str(out_path)
        except Exception as exc:
            outputs["available"] = False
            outputs["reason"] = f"Graphviz {fmt} 生成に失敗しました: {exc}"
            outputs[fmt] = None
            break
    return outputs


def build_graph_payload(triplets: Sequence[Triplet], *, node_inventory: Sequence[str] | None = None) -> Dict[str, Any]:
    graph = nx.DiGraph()
    for node in node_inventory or []:
        normalized = canonical_text(node)
        if normalized:
            graph.add_node(normalized)
    for prerequisite, relation, dependent in triplets:
        graph.add_edge(prerequisite, dependent, relation=relation)

    nodes = []
    for node in sorted(graph.nodes(), key=lambda value: canonical_text(value)):
        in_degree = graph.in_degree(node)
        out_degree = graph.out_degree(node)
        if in_degree == 0:
            role = "root"
        elif out_degree == 0:
            role = "leaf"
        else:
            role = "intermediate"
        nodes.append(
            {
                "id": node,
                "in_degree": in_degree,
                "out_degree": out_degree,
                "role": role,
            }
        )

    edges = [
        {"source": prerequisite, "target": dependent, "relation": relation}
        for prerequisite, relation, dependent in triplets
    ]
    return {"nodes": nodes, "edges": edges}


def enrich_graph_payload(
    graph_payload: Dict[str, Any],
    *,
    node_details: Sequence[Dict[str, Any]] | None = None,
    edge_details: Sequence[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    next_graph = json.loads(json.dumps(graph_payload))
    node_map = {
        canonical_text(row.get("id")): row
        for row in (node_details or [])
        if canonical_text(row.get("id"))
    }
    edge_map = {
        (
            canonical_text(row.get("source")),
            canonical_text(row.get("target")),
            canonical_text(row.get("relation")) or "Is-a-Prerequisite-of",
        ): row
        for row in (edge_details or [])
        if canonical_text(row.get("source")) and canonical_text(row.get("target"))
    }

    for node in next_graph.get("nodes") or []:
        detail = node_map.get(canonical_text(node.get("id")))
        if not detail:
            continue
        node["importance"] = detail.get("importance")
        node["slide_refs"] = detail.get("slide_refs") or []
        node["evidence_text"] = detail.get("evidence_text") or []

    for edge in next_graph.get("edges") or []:
        detail = edge_map.get(
            (
                canonical_text(edge.get("source")),
                canonical_text(edge.get("target")),
                canonical_text(edge.get("relation")) or "Is-a-Prerequisite-of",
            )
        )
        if not detail:
            continue
        edge["slide_refs"] = detail.get("slide_refs") or []
        edge["evidence_text"] = detail.get("evidence_text") or []
        edge["rationale"] = detail.get("rationale") or ""

    return next_graph


def write_triplets_csv(path: Path, triplets: Sequence[Triplet]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["prerequisite", "relation", "dependent"])
        writer.writerows(triplets)


def build_result_payload(
    result_id: str,
    output_dir: Path,
    variant: KgVariantSpec,
    context: KgRunContext,
    *,
    prompt: str,
    raw_response: str,
    triplets: Sequence[Triplet],
    is_dag: bool,
    cycles: Sequence[Sequence[str]],
    correction_attempts: int,
    summary_text: str,
    notes: Sequence[str],
    extra_metadata: Dict[str, Any] | None = None,
    extra_payload: Dict[str, Any] | None = None,
    graph_payload_override: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now().isoformat()
    graph_payload = graph_payload_override or build_graph_payload(triplets)
    triplet_rows = [
        {"prerequisite": prerequisite, "relation": relation, "dependent": dependent}
        for prerequisite, relation, dependent in triplets
    ]

    triplets_csv = output_dir / "triplets.csv"
    prompt_path = output_dir / "prompt.txt"
    raw_response_path = output_dir / "raw_response.txt"
    metadata_path = output_dir / "metadata.json"
    dot_path = output_dir / "knowledge_graph.dot"
    result_path = output_dir / "result.json"

    write_triplets_csv(triplets_csv, triplets)
    prompt_path.write_text(prompt, encoding="utf-8")
    raw_response_path.write_text(raw_response, encoding="utf-8")
    dot_path.write_text(build_dot_text(context.title, triplets), encoding="utf-8")

    visualization = render_graphviz_if_available(dot_path)
    artifacts = {
        "triplets_csv": str(triplets_csv),
        "prompt": str(prompt_path),
        "raw_response": str(raw_response_path),
        "metadata": str(metadata_path),
        "dot": str(dot_path),
    }
    if visualization.get("png"):
        artifacts["png"] = str(visualization["png"])
    if visualization.get("svg"):
        artifacts["svg"] = str(visualization["svg"])

    metadata = {
        "result_id": result_id,
        "variant_id": variant.id,
        "variant_label": variant.label,
        "variant_description": variant.description,
        "variant_kind": variant.kind,
        "created_at": created_at,
        "owner_user_id": context.owner_user_id,
        "project_id": context.project_id,
        "filename": context.filename,
        "material_name": context.material_name,
        "material_fingerprint": context.material_fingerprint,
        "model": context.model_name,
        "course_name": context.course_name,
        "language": context.language,
        "slide_count": len(context.image_paths),
        "triplet_count": len(triplets),
        "node_count": len(graph_payload["nodes"]),
        "is_dag": is_dag,
        "cycles": list(cycles),
        "correction_attempts": correction_attempts,
        "summary_text": summary_text,
        "notes": list(notes),
        "visualization": visualization,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    payload = {
        "ok": True,
        "result_id": result_id,
        "created_at": created_at,
        "filename": context.filename,
        "material_name": context.material_name,
        "material_fingerprint": context.material_fingerprint,
        "model": context.model_name,
        "owner_user_id": context.owner_user_id,
        "project": {
            "id": context.project_id,
        } if context.project_id else None,
        "output_dir": str(output_dir),
        "variant": {
            "id": variant.id,
            "label": variant.label,
            "description": variant.description,
            "kind": variant.kind,
            "enabled": variant.enabled,
        },
        "summary": {
            "slide_count": len(context.image_paths),
            "triplet_count": len(triplets),
            "node_count": len(graph_payload["nodes"]),
            "is_dag": is_dag,
            "correction_attempts": correction_attempts,
            "summary_text": summary_text,
            "notes": list(notes),
        },
        "triplets": triplet_rows,
        "graph": graph_payload,
        "prompt": prompt,
        "raw_response": raw_response,
        "metadata": metadata,
        "artifacts": artifacts,
        "visualization": visualization,
    }
    if extra_payload:
        payload.update(extra_payload)

    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def run_openai_triplet_extraction(client: Any, prompt: str, image_paths: Sequence[str], model_name: str) -> str:
    _response, text = call_responses_text(
        client,
        modelname=model_name,
        messages=[
            build_responses_system_message(
                "You are an expert knowledge graph builder for university-level courses."
            ),
            build_responses_user_message(prompt, image_paths),
        ],
    )
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise RuntimeError("KG preview extraction failed: empty model response")


def run_cycle_correction(client: Any, response_text: str, cycles: Sequence[Sequence[str]], model_name: str) -> str:
    correction_prompt = f"Previous response:\n{response_text}\n\n{format_cycle_feedback(cycles)}"
    _response, text = call_responses_text(
        client,
        modelname=model_name,
        messages=[
            build_responses_system_message(
                "You correct prerequisite knowledge graph triplets so the final graph is a DAG."
            ),
            build_responses_user_message(correction_prompt, []),
        ],
    )
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise RuntimeError("KG preview correction failed: empty model response")


def run_openai_json_extraction(
    client: Any,
    prompt: str,
    image_paths: Sequence[str],
    model_name: str,
    *,
    system_instruction: str | None = None,
    error_label: str = "KG JSON extraction",
) -> Dict[str, Any]:
    _response, text = call_responses_text(
        client,
        modelname=model_name,
        messages=[
            build_responses_system_message(
                system_instruction or "You must return one strict JSON object for the requested lecture knowledge graph task."
            ),
            build_responses_user_message(prompt, image_paths),
        ],
    )
    if isinstance(text, str) and text.strip():
        return extract_json_object(text.strip())
    raise RuntimeError(f"{error_label} failed: empty model response")


def build_baseline_graph_text(triplets: Sequence[Triplet]) -> str:
    if not triplets:
        return "None"
    rows = [f"- {left} -> {right}" for left, _relation, right in triplets]
    return "\n".join(rows)


def build_concept_inventory_text(nodes: Sequence[str]) -> str:
    if not nodes:
        return "None"
    return "\n".join(f"- {node}" for node in nodes)


def topological_generations(triplets: Sequence[Triplet]) -> List[List[str]]:
    graph = nx.DiGraph()
    for source, _relation, target in triplets:
        graph.add_edge(source, target)
    if not graph.nodes:
        return []
    if not nx.is_directed_acyclic_graph(graph):
        return [sorted(graph.nodes(), key=canonical_text)]
    return [sorted(list(group), key=canonical_text) for group in nx.topological_generations(graph)]


def compute_concept_scores(triplets: Sequence[Triplet]) -> Dict[str, int]:
    graph = nx.DiGraph()
    for source, _relation, target in triplets:
        graph.add_edge(source, target)
    scores: Dict[str, int] = {}
    for node in graph.nodes():
        descendants = len(nx.descendants(graph, node))
        scores[node] = (graph.out_degree(node) * 3) + descendants + max(0, 2 - graph.in_degree(node))
    return scores


def normalize_importance_from_scores(scores: Dict[str, int]) -> Dict[str, int]:
    if not scores:
        return {}
    lowest = min(scores.values())
    highest = max(scores.values())
    if highest == lowest:
        return {node: 3 for node in scores}
    return {
        node: max(1, min(5, int(round(1 + ((score - lowest) / (highest - lowest)) * 4))))
        for node, score in scores.items()
    }


def build_fallback_order_steps(
    baseline_triplets: Sequence[Triplet],
    *,
    max_steps: int = 6,
) -> List[Dict[str, Any]]:
    generations = topological_generations(baseline_triplets)
    if not generations:
        return []

    scores = compute_concept_scores(baseline_triplets)
    steps: List[Dict[str, Any]] = []
    for generation in generations[:max_steps]:
        ranked = sorted(
            generation,
            key=lambda node: (-scores.get(node, 0), canonical_text(node)),
        )
        if not ranked:
            continue
        focus = ranked[0]
        related = ranked[1:4]
        steps.append(
            {
                "step": len(steps) + 1,
                "focus": focus,
                "related_concepts": related,
                "goal": f"{focus} の意味と、この講義での役割を押さえる。",
                "why_now": "後続の概念を理解するための土台になるため。" if len(steps) == 0 else "前段の概念を踏まえて理解を広げるため。",
                "slide_refs": [],
            }
        )

    return steps


def relation_counter(edges: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in edges:
        label = sanitize_relation_label(row.get("relation"))
        counts[label] = counts.get(label, 0) + 1
    return counts


def build_prompt(context: KgRunContext) -> str:
    return fill_prompt_template(
        KG_PROMPT_TEMPLATE,
        COURSE_NAME=context.course_name,
        LANGUAGE=context.language,
        CONTENT=f"{len(context.image_paths)} lecture slides (images shown above)",
    )


def execute_raw_extraction(context: KgRunContext) -> Dict[str, Any]:
    cached = context.shared.get("raw_extraction")
    if cached:
        return cached

    prompt = build_prompt(context)
    response_text = run_openai_triplet_extraction(context.client, prompt, context.image_paths, context.model_name)
    triplets = parse_triplets(response_text)
    is_dag = True
    cycles: List[List[str]] = []
    correction_attempts = 0
    notes: List[str] = []

    while triplets and correction_attempts < 3:
        is_dag, cycles = check_dag(triplets)
        if is_dag:
            break
        correction_attempts += 1
        corrected_text = run_cycle_correction(context.client, response_text, cycles, context.model_name)
        corrected_triplets = parse_triplets(corrected_text)
        if not corrected_triplets:
            notes.append("cycle 修正を試みましたが、修正版 triplet が空になりました。")
            break
        response_text = corrected_text
        triplets = corrected_triplets

    if correction_attempts > 0:
        notes.append(f"cycle 修正を {correction_attempts} 回試行しました。")
    if triplets and not is_dag:
        notes.append("最終結果に cycle が残っています。")

    result = {
        "prompt": prompt,
        "raw_response": response_text,
        "triplets": triplets,
        "is_dag": is_dag,
        "cycles": cycles,
        "correction_attempts": correction_attempts,
        "notes": notes,
    }
    context.shared["raw_extraction"] = result
    return result


def run_raw_variant(context: KgRunContext, _variant: KgVariantSpec) -> Dict[str, Any]:
    raw = execute_raw_extraction(context)
    return {
        **raw,
        "summary_text": "既存実装の prerequisite 抽出を、そのまま比較用 payload に載せた原型です。",
        "extra_metadata": {"source_variant": "assistant_raw_port"},
    }


def run_normalized_json_variant(context: KgRunContext, _variant: KgVariantSpec) -> Dict[str, Any]:
    raw = execute_raw_extraction(context)
    normalized_triplets, stats = normalize_triplets(raw["triplets"])
    is_dag, cycles = check_dag(normalized_triplets)
    notes = list(raw.get("notes") or [])
    if stats["removed_duplicates"] > 0:
        notes.append(f"重複 edge を {stats['removed_duplicates']} 件整理しました。")
    if stats["removed_self_loops"] > 0:
        notes.append(f"自己ループを {stats['removed_self_loops']} 件除外しました。")
    if normalized_triplets and not is_dag:
        notes.append("整形後も cycle が残っています。")

    return {
        "prompt": raw["prompt"],
        "raw_response": raw["raw_response"],
        "triplets": normalized_triplets,
        "is_dag": is_dag,
        "cycles": cycles,
        "correction_attempts": raw.get("correction_attempts", 0),
        "notes": notes,
        "summary_text": "raw 結果をもとに、重複・自己ループを整理して JSON 向けに正規化した比較版です。",
        "extra_metadata": {
            "source_variant": "raw",
            "normalization": stats,
        },
    }


def build_evidence_prompt(context: KgRunContext, baseline_triplets: Sequence[Triplet]) -> str:
    return fill_prompt_template(
        KG_EVIDENCE_PROMPT_TEMPLATE,
        COURSE_NAME=context.course_name,
        LANGUAGE=context.language,
        BASELINE_GRAPH=build_baseline_graph_text(baseline_triplets),
        CONTENT=f"{len(context.image_paths)} lecture slides (images shown above)",
    )


def build_multirel_prompt(context: KgRunContext, concept_inventory: Sequence[str]) -> str:
    return fill_prompt_template(
        KG_MULTIREL_PROMPT_TEMPLATE,
        COURSE_NAME=context.course_name,
        LANGUAGE=context.language,
        CONCEPT_INVENTORY=build_concept_inventory_text(concept_inventory),
        CONTENT=f"{len(context.image_paths)} lecture slides (images shown above)",
    )


def build_order_prompt(context: KgRunContext, baseline_triplets: Sequence[Triplet]) -> str:
    return fill_prompt_template(
        KG_ORDER_PROMPT_TEMPLATE,
        COURSE_NAME=context.course_name,
        LANGUAGE=context.language,
        BASELINE_GRAPH=build_baseline_graph_text(baseline_triplets),
        CONTENT=f"{len(context.image_paths)} lecture slides (images shown above)",
    )


def align_evidence_payload(
    parsed: Dict[str, Any],
    baseline_triplets: Sequence[Triplet],
    *,
    slide_count: int,
) -> Dict[str, Any]:
    baseline_nodes = sorted({node for left, _relation, right in baseline_triplets for node in (left, right)}, key=canonical_text)
    baseline_node_lookup = {canonical_text(node): node for node in baseline_nodes}
    baseline_edges = {
        (
            canonical_text(left),
            canonical_text(right),
            canonical_text(relation) or "Is-a-Prerequisite-of",
        ): (left, relation, right)
        for left, relation, right in baseline_triplets
    }

    nodes_by_id = {
        node: {
            "id": node,
            "importance": None,
            "slide_refs": [],
            "evidence_text": [],
        }
        for node in baseline_nodes
    }
    missing_nodes = set(baseline_nodes)

    for row in parsed.get("nodes") or []:
        node_id = baseline_node_lookup.get(canonical_text(row.get("id")))
        if not node_id:
            continue
        missing_nodes.discard(node_id)
        nodes_by_id[node_id] = {
            "id": node_id,
            "importance": sanitize_importance(row.get("importance")),
            "slide_refs": sanitize_slide_refs(row.get("slide_refs"), slide_count),
            "evidence_text": sanitize_evidence_text(row.get("evidence_text")),
        }

    edges_by_key = {
        baseline_edges[key]: {
            "source": baseline_edges[key][0],
            "target": baseline_edges[key][2],
            "relation": baseline_edges[key][1],
            "slide_refs": [],
            "evidence_text": [],
            "rationale": "",
        }
        for key in baseline_edges
    }
    missing_edges = set(edges_by_key.keys())

    for row in parsed.get("edges") or []:
        key = (
            canonical_text(row.get("source")),
            canonical_text(row.get("target")),
            canonical_text(row.get("relation")) or "Is-a-Prerequisite-of",
        )
        baseline_edge = baseline_edges.get(key)
        if not baseline_edge:
            continue
        missing_edges.discard(baseline_edge)
        edges_by_key[baseline_edge] = {
            "source": baseline_edge[0],
            "target": baseline_edge[2],
            "relation": baseline_edge[1],
            "slide_refs": sanitize_slide_refs(row.get("slide_refs"), slide_count),
            "evidence_text": sanitize_evidence_text(row.get("evidence_text")),
            "rationale": canonical_text(row.get("rationale"))[:200],
        }

    return {
        "nodes": [nodes_by_id[node] for node in baseline_nodes],
        "edges": [edges_by_key[edge] for edge in baseline_triplets],
        "notes": [canonical_text(value)[:200] for value in (parsed.get("notes") or []) if canonical_text(value)],
        "missing_nodes": len(missing_nodes),
        "missing_edges": len(missing_edges),
    }


def execute_evidence_enrichment(context: KgRunContext) -> Dict[str, Any]:
    cached = context.shared.get("evidence_enrichment")
    if cached:
        return cached

    raw = execute_raw_extraction(context)
    baseline_triplets, normalization_stats = normalize_triplets(raw["triplets"])
    prompt = build_evidence_prompt(context, baseline_triplets)
    parsed = run_openai_json_extraction(context.client, prompt, context.image_paths, context.model_name)
    structured = align_evidence_payload(parsed, baseline_triplets, slide_count=len(context.image_paths))
    graph_payload = enrich_graph_payload(
        build_graph_payload(baseline_triplets),
        node_details=structured["nodes"],
        edge_details=structured["edges"],
    )
    result = {
        "raw": raw,
        "baseline_triplets": baseline_triplets,
        "normalization_stats": normalization_stats,
        "prompt": prompt,
        "parsed": parsed,
        "structured": structured,
        "graph_payload": graph_payload,
    }
    context.shared["evidence_enrichment"] = result
    return result


def merge_node_details(
    primary: Sequence[Dict[str, Any]],
    fallback: Sequence[Dict[str, Any]],
    *,
    computed_importance: Dict[str, int] | None = None,
) -> List[Dict[str, Any]]:
    importance_map = {
        canonical_text(key): value
        for key, value in (computed_importance or {}).items()
        if canonical_text(key)
    }
    fallback_map = {
        canonical_text(row.get("id")): row
        for row in fallback
        if canonical_text(row.get("id"))
    }
    merged: List[Dict[str, Any]] = []
    for row in primary:
        node_id = canonical_text(row.get("id"))
        if not node_id:
            continue
        base = fallback_map.get(node_id, {})
        merged.append(
            {
                "id": row.get("id") or base.get("id") or node_id,
                "importance": row.get("importance")
                if row.get("importance") is not None
                else base.get("importance")
                if base.get("importance") is not None
                else importance_map.get(node_id),
                "slide_refs": row.get("slide_refs") or base.get("slide_refs") or [],
                "evidence_text": row.get("evidence_text") or base.get("evidence_text") or [],
            }
        )
    return merged


def align_multirel_payload(
    parsed: Dict[str, Any],
    concept_inventory: Sequence[str],
    *,
    slide_count: int,
) -> Dict[str, Any]:
    concept_lookup = {canonical_text(node): node for node in concept_inventory}
    node_details = {
        node: {
            "id": node,
            "importance": None,
            "slide_refs": [],
            "evidence_text": [],
        }
        for node in concept_inventory
    }

    for row in parsed.get("nodes") or []:
        node_id = concept_lookup.get(canonical_text(row.get("id")))
        if not node_id:
            continue
        node_details[node_id] = {
            "id": node_id,
            "importance": sanitize_importance(row.get("importance")),
            "slide_refs": sanitize_slide_refs(row.get("slide_refs"), slide_count),
            "evidence_text": sanitize_evidence_text(row.get("evidence_text")),
        }

    dedupe = set()
    edges: List[Dict[str, Any]] = []
    dropped_edges = 0
    for row in parsed.get("edges") or []:
        source = concept_lookup.get(canonical_text(row.get("source")))
        target = concept_lookup.get(canonical_text(row.get("target")))
        if not source or not target or source == target:
            dropped_edges += 1
            continue
        relation = sanitize_relation_label(row.get("relation"))
        key = (source, target, relation)
        if key in dedupe:
            continue
        dedupe.add(key)
        edges.append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                "slide_refs": sanitize_slide_refs(row.get("slide_refs"), slide_count),
                "evidence_text": sanitize_evidence_text(row.get("evidence_text")),
                "rationale": canonical_text(row.get("rationale"))[:200],
            }
        )

    notes = [canonical_text(value)[:200] for value in (parsed.get("notes") or []) if canonical_text(value)]
    return {
        "nodes": [node_details[node] for node in concept_inventory],
        "edges": edges,
        "notes": notes,
        "dropped_edges": dropped_edges,
    }


def build_triplets_from_structured_edges(edges: Sequence[Dict[str, Any]]) -> List[Triplet]:
    triplets: List[Triplet] = []
    for row in edges:
        source = canonical_text(row.get("source"))
        target = canonical_text(row.get("target"))
        relation = sanitize_relation_label(row.get("relation"))
        if not source or not target or source == target:
            continue
        triplets.append((source, relation, target))
    return triplets


def align_order_payload(
    parsed: Dict[str, Any],
    available_concepts: Sequence[str],
    *,
    slide_count: int,
) -> Dict[str, Any]:
    concept_lookup = {canonical_text(node): node for node in available_concepts}
    steps = []
    for row in parsed.get("steps") or []:
        focus = concept_lookup.get(canonical_text(row.get("focus")))
        if not focus:
            continue
        related = []
        for concept in row.get("related_concepts") or []:
            normalized = concept_lookup.get(canonical_text(concept))
            if normalized and normalized not in related and normalized != focus:
                related.append(normalized)
        try:
            step_number = int(row.get("step"))
        except Exception:
            step_number = len(steps) + 1
        steps.append(
            {
                "step": step_number,
                "focus": focus,
                "related_concepts": related,
                "goal": canonical_text(row.get("goal"))[:200],
                "why_now": canonical_text(row.get("why_now"))[:200],
                "slide_refs": sanitize_slide_refs(row.get("slide_refs"), slide_count),
            }
        )

    steps.sort(key=lambda row: (int(row.get("step") or 0), canonical_text(row.get("focus"))))
    for index, row in enumerate(steps, start=1):
        row["step"] = index

    notes = [canonical_text(value)[:200] for value in (parsed.get("notes") or []) if canonical_text(value)]
    return {"steps": steps, "notes": notes}


def run_multirel_variant(context: KgRunContext, _variant: KgVariantSpec) -> Dict[str, Any]:
    enrichment = execute_evidence_enrichment(context)
    raw = enrichment["raw"]
    baseline_triplets = enrichment["baseline_triplets"]
    concept_inventory = [row["id"] for row in enrichment["structured"]["nodes"]]
    prompt = build_multirel_prompt(context, concept_inventory)
    parsed = run_openai_json_extraction(
        context.client,
        prompt,
        context.image_paths,
        context.model_name,
        system_instruction="You convert a lecture concept inventory into a strict explanation-oriented JSON knowledge graph.",
        error_label="KG multi-relation extraction",
    )
    structured = align_multirel_payload(parsed, concept_inventory, slide_count=len(context.image_paths))

    if not structured["edges"]:
        fallback_edges = []
        edge_fallback_map = {
            (
                canonical_text(row.get("source")),
                canonical_text(row.get("target")),
                canonical_text(row.get("relation")) or "Is-a-Prerequisite-of",
            ): row
            for row in enrichment["structured"]["edges"]
        }
        for left, relation, right in baseline_triplets:
            detail = edge_fallback_map.get((canonical_text(left), canonical_text(right), canonical_text(relation)), {})
            fallback_edges.append(
                {
                    "source": left,
                    "target": right,
                    "relation": relation,
                    "slide_refs": detail.get("slide_refs") or [],
                    "evidence_text": detail.get("evidence_text") or [],
                    "rationale": detail.get("rationale") or "",
                }
            )
        structured["edges"] = fallback_edges
        structured["notes"].append("多関係 edge が十分に得られなかったため、baseline prerequisite edge を補完しました。")

    computed_importance = normalize_importance_from_scores(compute_concept_scores(baseline_triplets))
    node_details = merge_node_details(
        structured["nodes"],
        enrichment["structured"]["nodes"],
        computed_importance=computed_importance,
    )
    edge_details = structured["edges"]
    triplets = build_triplets_from_structured_edges(edge_details)
    is_dag, cycles = check_dag(triplets)
    relation_counts = relation_counter(edge_details)
    notes = list(raw.get("notes") or [])
    notes.extend(structured.get("notes") or [])
    if structured["dropped_edges"] > 0:
        notes.append(f"concept inventory 外または不正形式の edge を {structured['dropped_edges']} 件除外しました。")
    if not is_dag:
        notes.append("この版は説明用の多関係グラフなので、DAG ではない場合があります。")

    return {
        "prompt": prompt,
        "raw_response": json.dumps(parsed, ensure_ascii=False, indent=2),
        "triplets": triplets,
        "is_dag": is_dag,
        "cycles": cycles,
        "correction_attempts": raw.get("correction_attempts", 0),
        "notes": notes,
        "summary_text": "固定した概念集合のまま relation を増やし、説明向けのつながりを表現する改良版です。",
        "extra_metadata": {
            "source_variant": "evidence_proto",
            "relation_counts": relation_counts,
            "structured_counts": {
                "node_count": len(node_details),
                "edge_count": len(edge_details),
                "dropped_edges": structured["dropped_edges"],
            },
        },
        "extra_payload": {
            "structured": {
                "nodes": node_details,
                "edges": edge_details,
            },
            "analysis_panels": [
                {
                    "kind": "relation_counts",
                    "title": "Relation 内訳",
                    "items": [
                        {"label": relation, "value": count}
                        for relation, count in sorted(relation_counts.items(), key=lambda row: (-row[1], row[0]))
                    ],
                }
            ],
        },
        "graph_payload_override": enrich_graph_payload(
            build_graph_payload(triplets, node_inventory=concept_inventory),
            node_details=node_details,
            edge_details=edge_details,
        ),
    }


def run_order_variant(context: KgRunContext, _variant: KgVariantSpec) -> Dict[str, Any]:
    enrichment = execute_evidence_enrichment(context)
    raw = enrichment["raw"]
    baseline_triplets = enrichment["baseline_triplets"]
    concept_inventory = [row["id"] for row in enrichment["structured"]["nodes"]]
    prompt = build_order_prompt(context, baseline_triplets)
    parsed = run_openai_json_extraction(
        context.client,
        prompt,
        context.image_paths,
        context.model_name,
        system_instruction="You design a compact explanation order from a fixed prerequisite graph and must return one strict JSON object.",
        error_label="KG explanation-order extraction",
    )
    order_plan = align_order_payload(parsed, concept_inventory, slide_count=len(context.image_paths))
    notes = list(raw.get("notes") or [])
    notes.extend(order_plan.get("notes") or [])

    if not order_plan["steps"]:
        order_plan["steps"] = build_fallback_order_steps(baseline_triplets)
        notes.append("LLM から有効な説明順が得られなかったため、トポロジカル順ベースの fallback を使いました。")

    generation_rows = topological_generations(baseline_triplets)
    score_map = compute_concept_scores(baseline_triplets)
    importance_map = normalize_importance_from_scores(score_map)
    node_details = merge_node_details(
        enrichment["structured"]["nodes"],
        enrichment["structured"]["nodes"],
        computed_importance=importance_map,
    )

    return {
        "prompt": prompt,
        "raw_response": json.dumps(parsed, ensure_ascii=False, indent=2),
        "triplets": baseline_triplets,
        "is_dag": raw.get("is_dag", True),
        "cycles": raw.get("cycles") or [],
        "correction_attempts": raw.get("correction_attempts", 0),
        "notes": notes,
        "summary_text": "KG 自体と説明順を分離し、台本生成に渡しやすい step 列を別出力する改良版です。",
        "extra_metadata": {
            "source_variant": "raw",
            "plan_step_count": len(order_plan["steps"]),
            "topology_layer_count": len(generation_rows),
        },
        "extra_payload": {
            "structured": {
                "nodes": node_details,
                "edges": enrichment["structured"]["edges"],
            },
            "order_plan": order_plan,
            "analysis_panels": [
                {
                    "kind": "topology_layers",
                    "title": "Topological Layer",
                    "items": [
                        {"label": f"Layer {index}", "value": " / ".join(layer)}
                        for index, layer in enumerate(generation_rows, start=1)
                    ],
                }
            ],
        },
        "graph_payload_override": enrich_graph_payload(
            build_graph_payload(baseline_triplets, node_inventory=concept_inventory),
            node_details=node_details,
            edge_details=enrichment["structured"]["edges"],
        ),
    }


def run_evidence_variant(context: KgRunContext, _variant: KgVariantSpec) -> Dict[str, Any]:
    enrichment = execute_evidence_enrichment(context)
    raw = enrichment["raw"]
    baseline_triplets = enrichment["baseline_triplets"]
    normalization_stats = enrichment["normalization_stats"]
    structured = enrichment["structured"]

    notes = list(raw.get("notes") or [])
    notes.extend(structured.get("notes") or [])
    if normalization_stats["removed_duplicates"] > 0:
        notes.append(f"baseline 生成時に重複 edge を {normalization_stats['removed_duplicates']} 件整理しています。")
    if normalization_stats["removed_self_loops"] > 0:
        notes.append(f"baseline 生成時に自己ループを {normalization_stats['removed_self_loops']} 件除外しています。")
    if structured["missing_nodes"] > 0:
        notes.append(f"node 根拠が空の概念が {structured['missing_nodes']} 件あります。")
    if structured["missing_edges"] > 0:
        notes.append(f"edge 根拠が空の関係が {structured['missing_edges']} 件あります。")

    return {
        "prompt": enrichment["prompt"],
        "raw_response": json.dumps(enrichment["parsed"], ensure_ascii=False, indent=2),
        "triplets": baseline_triplets,
        "is_dag": raw.get("is_dag", True),
        "cycles": raw.get("cycles") or [],
        "correction_attempts": raw.get("correction_attempts", 0),
        "notes": notes,
        "summary_text": "raw の prerequisite edge を維持したまま、各 node/edge に slide refs・evidence・重要度を付与した改良版です。",
        "extra_metadata": {
            "source_variant": "raw",
            "normalization": normalization_stats,
            "structured_counts": {
                "node_count": len(structured["nodes"]),
                "edge_count": len(structured["edges"]),
                "missing_nodes": structured["missing_nodes"],
                "missing_edges": structured["missing_edges"],
            },
        },
        "extra_payload": {
            "structured": {
                "nodes": structured["nodes"],
                "edges": structured["edges"],
            },
        },
        "graph_payload_override": enrichment["graph_payload"],
    }


def run_not_ready_variant(_context: KgRunContext, variant: KgVariantSpec) -> Dict[str, Any]:
    raise ApiError(400, "KG_VARIANT_DISABLED", f"variant '{variant.id}' はまだ比較実行できません。")


KG_VARIANTS: List[KgVariantSpec] = [
    KgVariantSpec(
        id="raw",
        label="原型",
        description="既存実装の prerequisite 抽出をそのまま表示します。",
        kind="raw",
        runner=run_raw_variant,
        enabled=True,
    ),
    KgVariantSpec(
        id="evidence_proto",
        label="根拠付き試作",
        description="raw の edge を維持したまま、slide refs・evidence・概念重要度を付与します。",
        kind="evidence",
        runner=run_evidence_variant,
        enabled=True,
    ),
    KgVariantSpec(
        id="normalized_json",
        label="JSON整形版",
        description="raw を基に重複・自己ループを整理し、後段利用しやすい形へ寄せます。",
        kind="normalized",
        runner=run_normalized_json_variant,
        enabled=True,
    ),
    KgVariantSpec(
        id="multirel_proto",
        label="多関係試作",
        description="固定した概念集合のまま relation を増やし、説明向けの関係を比較します。",
        kind="multirel",
        runner=run_multirel_variant,
        enabled=True,
    ),
    KgVariantSpec(
        id="order_plan_proto",
        label="説明順分離版",
        description="KG と説明順を分けて、台本に渡す step 列を別出力します。",
        kind="order_plan",
        runner=run_order_variant,
        enabled=True,
    ),
]

KG_VARIANT_BY_ID = {variant.id: variant for variant in KG_VARIANTS}


def list_kg_variants() -> Dict[str, Any]:
    return {
        "variants": [
            {
                "id": variant.id,
                "label": variant.label,
                "description": variant.description,
                "kind": variant.kind,
                "enabled": variant.enabled,
            }
            for variant in KG_VARIANTS
        ],
        "default_model": str(auto_config.API_MODEL_EXPLANATION),
        "max_compare_variants": MAX_COMPARE_VARIANTS,
    }


def validate_variant_selection(variant_ids: Sequence[str]) -> List[KgVariantSpec]:
    unique_ids: List[str] = []
    seen = set()
    for value in variant_ids:
        key = canonical_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_ids.append(key)

    if not unique_ids:
        raise ApiError(400, "KG_VARIANTS_REQUIRED", "比較する variant を 1 つ以上選んでください。")
    if len(unique_ids) > MAX_COMPARE_VARIANTS:
        raise ApiError(400, "KG_VARIANTS_TOO_MANY", f"variant は最大 {MAX_COMPARE_VARIANTS} 件まで選択できます。")

    specs: List[KgVariantSpec] = []
    invalid_ids: List[str] = []
    disabled_ids: List[str] = []
    for variant_id in unique_ids:
        spec = KG_VARIANT_BY_ID.get(variant_id)
        if not spec:
            invalid_ids.append(variant_id)
            continue
        if not spec.enabled:
            disabled_ids.append(variant_id)
            continue
        specs.append(spec)

    if invalid_ids:
        raise ApiError(400, "KG_VARIANT_INVALID", f"不明な variant です: {', '.join(invalid_ids)}")
    if disabled_ids:
        raise ApiError(400, "KG_VARIANT_DISABLED", f"まだ有効化されていない variant です: {', '.join(disabled_ids)}")
    return specs


def prepare_run_context(req: KgPreviewCompareRequest, *, owner_user_id: str | None = None) -> KgRunContext:
    try:
        from .cache import decode_pdf_base64

        pdf_bytes = decode_pdf_base64(req.pdf_base64)
    except ValueError as exc:
        raise ApiError(400, "INVALID_PDF", str(exc)) from exc

    material_fingerprint = hashlib.sha256(pdf_bytes).hexdigest()
    material_name = f"kg_compare_{material_fingerprint[:12]}_{timestamp_slug()}_{short_id()}.pdf"
    ensure_pdf_upload(material_name, pdf_bytes)
    image_paths = sorted(ensure_pdf_images(material_name), key=natural_sort_key)
    if not image_paths:
        raise ApiError(500, "KG_PREVIEW_FAILED", "スライド画像の準備に失敗しました")

    return KgRunContext(
        filename=req.filename,
        model_name=str(req.model or auto_config.API_MODEL_EXPLANATION),
        course_name=str(req.course_name or "情報科学"),
        language=str(req.language or "Japanese"),
        material_name=material_name,
        material_fingerprint=material_fingerprint,
        image_paths=image_paths,
        client=create_client(),
        title=f"{Path(req.filename).stem}\nPrerequisite Knowledge Graph",
        project_id=req.project_id,
        owner_user_id=owner_user_id,
        shared={},
    )


def render_kg_preview_compare(req: KgPreviewCompareRequest, *, owner_user_id: str | None = None) -> Dict[str, Any]:
    specs = validate_variant_selection(req.variant_ids)
    context = prepare_run_context(req, owner_user_id=owner_user_id)
    results = []

    for spec in specs:
        variant_result = spec.runner(context, spec)
        result_id = f"kgres_{timestamp_slug()}_{spec.id}_{short_id()}"
        output_dir = CATALOG_ROOT / result_id
        payload = build_result_payload(
            result_id,
            output_dir,
            spec,
            context,
            prompt=str(variant_result["prompt"]),
            raw_response=str(variant_result.get("raw_response") or ""),
            triplets=list(variant_result.get("triplets") or []),
            is_dag=bool(variant_result.get("is_dag", True)),
            cycles=list(variant_result.get("cycles") or []),
            correction_attempts=int(variant_result.get("correction_attempts") or 0),
            summary_text=str(variant_result.get("summary_text") or ""),
            notes=list(variant_result.get("notes") or []),
            extra_metadata=variant_result.get("extra_metadata") or {},
            extra_payload=variant_result.get("extra_payload") or {},
            graph_payload_override=variant_result.get("graph_payload_override"),
        )
        results.append(payload)

    return {
        "ok": True,
        "filename": context.filename,
        "model": context.model_name,
        "material_name": context.material_name,
        "material_fingerprint": context.material_fingerprint,
        "project_id": context.project_id,
        "results": results,
    }


def render_kg_preview(req: KgPreviewRequest) -> Dict[str, Any]:
    compare_req = KgPreviewCompareRequest(
        pdf_base64=req.pdf_base64,
        filename=req.filename,
        variant_ids=["raw"],
        model=req.model,
        course_name=req.course_name,
        language=req.language,
        project_id=req.project_id,
    )
    payload = render_kg_preview_compare(compare_req)
    return payload["results"][0]


def _catalog_result_path(result_id: str) -> Path:
    return CATALOG_ROOT / result_id / "result.json"


def _read_catalog_payload(result_id: str) -> Dict[str, Any]:
    path = _catalog_result_path(result_id)
    if not path.exists():
        raise ApiError(404, "KG_RESULT_NOT_FOUND", f"result_id '{result_id}' は見つかりません。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApiError(500, "KG_RESULT_READ_FAILED", f"result_id '{result_id}' を読み込めませんでした: {exc}") from exc


def get_kg_preview_result(result_id: str, *, user_id: str | None = None, project_id: str | None = None) -> Dict[str, Any]:
    payload = _read_catalog_payload(result_id)
    owner_user_id = canonical_text(payload.get("owner_user_id"))
    payload_project_id = canonical_text((payload.get("project") or {}).get("id"))
    if user_id and owner_user_id and owner_user_id != canonical_text(user_id):
        raise ApiError(404, "KG_RESULT_NOT_FOUND", f"result_id '{result_id}' は見つかりません。")
    if project_id and payload_project_id != canonical_text(project_id):
        raise ApiError(404, "KG_RESULT_NOT_FOUND", f"project '{project_id}' に result_id '{result_id}' は存在しません。")
    return payload


def build_catalog_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    summary = payload.get("summary") or {}
    variant = payload.get("variant") or {}
    return {
        "result_id": payload.get("result_id"),
        "created_at": payload.get("created_at"),
        "filename": payload.get("filename"),
        "material_name": payload.get("material_name"),
        "material_fingerprint": payload.get("material_fingerprint"),
        "model": payload.get("model"),
        "project": payload.get("project") or None,
        "variant": {
            "id": variant.get("id"),
            "label": variant.get("label"),
            "description": variant.get("description"),
            "kind": variant.get("kind"),
        },
        "summary": {
            "slide_count": summary.get("slide_count"),
            "triplet_count": summary.get("triplet_count"),
            "node_count": summary.get("node_count"),
            "is_dag": summary.get("is_dag"),
            "correction_attempts": summary.get("correction_attempts"),
            "summary_text": summary.get("summary_text"),
            "notes": summary.get("notes") or [],
        },
        "output_dir": payload.get("output_dir"),
    }


def list_kg_preview_results(
    *,
    user_id: str | None = None,
    project_id: str | None = None,
    filename: str | None = None,
    material_fingerprint: str | None = None,
    variant_id: str | None = None,
    limit: int | None = None,
) -> Dict[str, Any]:
    CATALOG_ROOT.mkdir(parents=True, exist_ok=True)
    items: List[Dict[str, Any]] = []

    for result_path in sorted(CATALOG_ROOT.glob("*/result.json"), reverse=True):
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        owner_user_id = canonical_text(payload.get("owner_user_id"))
        payload_project_id = canonical_text((payload.get("project") or {}).get("id"))
        if user_id and owner_user_id and owner_user_id != canonical_text(user_id):
            continue
        if project_id and payload_project_id != canonical_text(project_id):
            continue
        if filename and canonical_text(payload.get("filename")) != canonical_text(filename):
            continue
        if material_fingerprint and canonical_text(payload.get("material_fingerprint")) != canonical_text(material_fingerprint):
            continue
        if variant_id and canonical_text(payload.get("variant", {}).get("id")) != canonical_text(variant_id):
            continue

        items.append(build_catalog_item(payload))

    items.sort(key=lambda row: canonical_text(row.get("created_at")), reverse=True)
    max_items = max(1, min(int(limit or DEFAULT_CATALOG_LIMIT), 100))
    return {"results": items[:max_items], "total": len(items)}
