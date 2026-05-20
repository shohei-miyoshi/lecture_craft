from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Tuple

import networkx as nx


SCORING_VERSION = "degree_axis_v1"
DIFFICULTIES = ("intro", "basic", "advanced")
DETAILS = ("summary", "standard", "detail")
MODES = ("audio", "video", "hl")
DETAIL_LIMITS = {"summary": 3, "standard": 5, "detail": 8}


def canonical_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return fallback
    if not math.isfinite(number):
        return fallback
    return number


def _normalize(values: Dict[str, float]) -> Dict[str, float]:
    if not values:
        return {}
    low = min(values.values())
    high = max(values.values())
    if high == low:
        return {key: 0.5 for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


def _node_rows(graph_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = graph_payload.get("nodes") if isinstance(graph_payload.get("nodes"), list) else []
    clean_rows: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        node_id = canonical_text(row.get("id"))
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        clean_rows.append({**row, "id": node_id})
    return clean_rows


def _edge_rows(graph_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = graph_payload.get("edges") if isinstance(graph_payload.get("edges"), list) else []
    clean_rows: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = canonical_text(row.get("source") or row.get("prerequisite"))
        target = canonical_text(row.get("target") or row.get("dependent"))
        relation = canonical_text(row.get("relation")) or "Is-a-Prerequisite-of"
        if not source or not target or source == target:
            continue
        key = (source, target, relation)
        if key in seen:
            continue
        seen.add(key)
        clean_rows.append({**row, "source": source, "target": target, "relation": relation})
    return clean_rows


def _topology_depths(graph: nx.DiGraph) -> Dict[str, int]:
    if not graph.nodes:
        return {}
    if nx.is_directed_acyclic_graph(graph):
        depths: Dict[str, int] = {}
        for depth, generation in enumerate(nx.topological_generations(graph)):
            for node in generation:
                depths[str(node)] = depth
        return depths

    roots = [node for node in graph.nodes if graph.in_degree(node) == 0]
    if not roots:
        return {str(node): 0 for node in graph.nodes}
    depths = {str(node): 0 for node in graph.nodes}
    for root in roots:
        lengths = nx.single_source_shortest_path_length(graph, root)
        for node, depth in lengths.items():
            key = str(node)
            depths[key] = max(depths.get(key, 0), int(depth))
    return depths


def _safe_ancestors(graph: nx.DiGraph, node: str) -> int:
    try:
        return len(nx.ancestors(graph, node))
    except Exception:
        return 0


def _safe_descendants(graph: nx.DiGraph, node: str) -> int:
    try:
        return len(nx.descendants(graph, node))
    except Exception:
        return 0


def _profile_key(difficulty: str, detail: str, mode: str) -> str:
    return f"{difficulty}.{detail}.{mode}"


def _emphasis_for(difficulty: str) -> str:
    if difficulty == "intro":
        return "foundation"
    if difficulty == "advanced":
        return "application"
    return "bridge"


def _reason_for(row: Dict[str, Any], *, difficulty: str, mode: str) -> str:
    parts = [f"次数中心性 {row['degree_centrality']:.3f}"]
    if difficulty == "intro":
        parts.append("前提・根概念を優先")
    elif difficulty == "advanced":
        parts.append("応用・末端寄り概念を優先")
    else:
        parts.append("橋渡し概念を優先")
    if mode == "video":
        parts.append("slide refs を補正")
    elif mode == "hl":
        parts.append("根拠付き概念を補正")
    else:
        parts.append("全体中心概念を補正")
    return " / ".join(parts)


def build_kg_scoring(graph_payload: Dict[str, Any]) -> Dict[str, Any]:
    node_rows = _node_rows(graph_payload if isinstance(graph_payload, dict) else {})
    edge_rows = _edge_rows(graph_payload if isinstance(graph_payload, dict) else {})

    graph = nx.DiGraph()
    for row in node_rows:
        graph.add_node(row["id"])
    for row in edge_rows:
        graph.add_edge(row["source"], row["target"])

    degree_centrality = nx.degree_centrality(graph) if graph.nodes else {}
    depths = _topology_depths(graph)
    max_depth = max(depths.values()) if depths else 0

    by_id = {row["id"]: row for row in node_rows}
    metrics: Dict[str, Dict[str, Any]] = {}
    for node in sorted(graph.nodes, key=canonical_text):
        node_id = str(node)
        source_row = by_id.get(node_id, {})
        slide_refs = []
        for value in source_row.get("slide_refs") or []:
            try:
                slide_refs.append(int(value))
            except Exception:
                continue
        evidence_text = [
            canonical_text(value)[:160]
            for value in (source_row.get("evidence_text") or [])
            if canonical_text(value)
        ][:3]
        in_degree = int(graph.in_degree(node_id))
        out_degree = int(graph.out_degree(node_id))
        ancestor_count = _safe_ancestors(graph, node_id)
        descendant_count = _safe_descendants(graph, node_id)
        topology_depth = int(depths.get(node_id, 0))
        metrics[node_id] = {
            "id": node_id,
            "degree_centrality": round(_safe_float(degree_centrality.get(node_id)), 6),
            "in_degree": in_degree,
            "out_degree": out_degree,
            "ancestor_count": ancestor_count,
            "descendant_count": descendant_count,
            "topology_depth": topology_depth,
            "is_root": in_degree == 0,
            "is_leaf": out_degree == 0,
            "slide_refs": slide_refs,
            "evidence_text": evidence_text,
        }

    centrality_norm = _normalize({node: row["degree_centrality"] for node, row in metrics.items()})
    in_norm = _normalize({node: float(row["in_degree"]) for node, row in metrics.items()})
    out_norm = _normalize({node: float(row["out_degree"]) for node, row in metrics.items()})
    ancestor_norm = _normalize({node: float(row["ancestor_count"]) for node, row in metrics.items()})
    descendant_norm = _normalize({node: float(row["descendant_count"]) for node, row in metrics.items()})
    depth_norm = {
        node: (float(row["topology_depth"]) / max_depth if max_depth > 0 else 0.0)
        for node, row in metrics.items()
    }
    slide_norm = _normalize({node: float(len(row["slide_refs"])) for node, row in metrics.items()})
    evidence_norm = _normalize({node: float(len(row["evidence_text"])) for node, row in metrics.items()})

    profiles: Dict[str, Dict[str, Any]] = {}
    for difficulty in DIFFICULTIES:
        for detail in DETAILS:
            for mode in MODES:
                scored_rows = []
                for node_id, metric in metrics.items():
                    base = centrality_norm.get(node_id, 0.0)
                    if difficulty == "intro":
                        axis_bonus = (
                            0.28 * out_norm.get(node_id, 0.0)
                            + 0.28 * descendant_norm.get(node_id, 0.0)
                            + 0.22 * (1.0 - depth_norm.get(node_id, 0.0))
                            + (0.30 if metric["is_root"] else 0.0)
                        )
                    elif difficulty == "advanced":
                        axis_bonus = (
                            0.26 * in_norm.get(node_id, 0.0)
                            + 0.28 * ancestor_norm.get(node_id, 0.0)
                            + 0.24 * depth_norm.get(node_id, 0.0)
                            + (0.22 if metric["is_leaf"] else 0.0)
                        )
                    else:
                        bridge = min(in_norm.get(node_id, 0.0), out_norm.get(node_id, 0.0))
                        axis_bonus = (
                            0.28 * bridge
                            + 0.18 * centrality_norm.get(node_id, 0.0)
                            + 0.12 * (1.0 - abs(depth_norm.get(node_id, 0.0) - 0.5))
                        )

                    if mode == "video":
                        mode_bonus = 0.10 * slide_norm.get(node_id, 0.0)
                    elif mode == "hl":
                        mode_bonus = 0.08 * slide_norm.get(node_id, 0.0) + 0.10 * evidence_norm.get(node_id, 0.0)
                    else:
                        mode_bonus = 0.04 * centrality_norm.get(node_id, 0.0)

                    base_weight = 0.62 if difficulty == "basic" else 0.45
                    adjusted = (base_weight * base) + axis_bonus + mode_bonus
                    row = {
                        "id": node_id,
                        "adjusted_score": round(adjusted, 6),
                        "base_degree_centrality": round(metric["degree_centrality"], 6),
                        "emphasis": _emphasis_for(difficulty),
                        "reason": _reason_for(metric, difficulty=difficulty, mode=mode),
                        "slide_refs": metric["slide_refs"],
                        "evidence_text": metric["evidence_text"],
                    }
                    scored_rows.append(row)

                scored_rows.sort(
                    key=lambda row: (
                        -row["adjusted_score"],
                        -row["base_degree_centrality"],
                        canonical_text(row["id"]),
                    )
                )
                limit = DETAIL_LIMITS[detail]
                key = _profile_key(difficulty, detail, mode)
                profiles[key] = {
                    "key": key,
                    "difficulty": difficulty,
                    "detail": detail,
                    "mode": mode,
                    "top_n": limit,
                    "top_concepts": scored_rows[:limit],
                    "brief_concepts": scored_rows[limit:limit + 5],
                }

    base_top = sorted(
        [
            {
                "id": node_id,
                "degree_centrality": row["degree_centrality"],
                "in_degree": row["in_degree"],
                "out_degree": row["out_degree"],
            }
            for node_id, row in metrics.items()
        ],
        key=lambda row: (-row["degree_centrality"], canonical_text(row["id"])),
    )

    return {
        "version": SCORING_VERSION,
        "metrics": metrics,
        "base_top_concepts": base_top[:8],
        "profiles": profiles,
    }


def select_scoring_profile(
    scoring: Dict[str, Any] | None,
    *,
    difficulty: str,
    detail: str,
    mode: str,
) -> Tuple[str, Dict[str, Any]]:
    key = _profile_key(difficulty, detail, mode)
    profiles = scoring.get("profiles") if isinstance(scoring, dict) else {}
    if isinstance(profiles, dict) and isinstance(profiles.get(key), dict):
        return key, profiles[key]
    fallback = next(iter(profiles.items()), None) if isinstance(profiles, dict) else None
    if fallback:
        return str(fallback[0]), fallback[1]
    return key, {"key": key, "top_concepts": [], "brief_concepts": []}
