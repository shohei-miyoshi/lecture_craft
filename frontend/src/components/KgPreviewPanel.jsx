import ELK from "elkjs/lib/elk.bundled.js";
import { useEffect, useMemo, useRef, useState } from "react";
import { DETAIL_LABELS, DETAIL_VALS, DIFF_LABELS, DIFF_VALS, MODE_LABELS, MODE_VALS } from "../utils/constants.js";
import { authFetch } from "../utils/sessionStore.js";
import { toB64 } from "../utils/helpers.js";

const DEFAULT_RELATION = "Is-a-Prerequisite-of";
const elk = new ELK();
const KG_LAYOUT_PADDING = 24;
const KG_NODE_WIDTH = 172;
const KG_NODE_BASE_HEIGHT = 50;
const KG_NODE_LINE_HEIGHT = 16;
const RELATION_PRIORITIES = {
  [DEFAULT_RELATION]: 90,
  step_before: 82,
  explains: 76,
  part_of: 66,
  used_for: 58,
  example_of: 48,
  contrasts_with: 34,
};
const RELATION_STYLES = {
  [DEFAULT_RELATION]: { label: "前提", color: "#90A0B7" },
  explains: { label: "説明", color: "#67B7FF" },
  example_of: { label: "例示", color: "#F5C96A" },
  contrasts_with: { label: "対比", color: "#FF9D7A" },
  part_of: { label: "一部", color: "#C6A4FF" },
  used_for: { label: "用途", color: "#67D3B0" },
  step_before: { label: "順序", color: "#F08CC0" },
  multi: { label: "複合", color: "#D7DEE9" },
};
const DISPLAY_SECTIONS = [
  { id: "graph", label: "Graph" },
  { id: "summary", label: "要約" },
  { id: "triplets", label: "Triplets" },
  { id: "edge_details", label: "根拠付きEdge" },
  { id: "node_details", label: "概念メモ" },
  { id: "order_plan", label: "説明順" },
  { id: "analysis", label: "分析パネル" },
  { id: "raw", label: "Raw" },
  { id: "artifacts", label: "Artifacts" },
];
const DEFAULT_VISIBLE_SECTIONS = ["graph", "summary", "triplets"];

function chunkString(text, size) {
  const rows = [];
  for (let i = 0; i < text.length; i += size) {
    rows.push(text.slice(i, i + size));
  }
  return rows;
}

function wrapLabel(text, maxChars = 12, maxLines = 3) {
  const source = String(text ?? "").trim();
  if (!source) return ["—"];

  const words = source.includes(" ") ? source.split(/\s+/).filter(Boolean) : [];
  let lines = [];

  if (words.length > 1) {
    let current = "";
    for (const word of words) {
      const next = current ? `${current} ${word}` : word;
      if (next.length <= maxChars) {
        current = next;
        continue;
      }
      if (current) lines.push(current);
      current = word;
    }
    if (current) lines.push(current);
  } else {
    lines = chunkString(source, maxChars);
  }

  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines);
    const last = kept[maxLines - 1];
    kept[maxLines - 1] = last.length >= maxChars ? `${last.slice(0, maxChars - 1)}…` : `${last}…`;
    return kept;
  }
  return lines;
}

function relationRowsFromPayload(payload) {
  const graphEdges = payload?.graph?.edges ?? [];
  if (graphEdges.length) {
    return graphEdges.map((row) => ({
      source: String(row?.source ?? "").trim(),
      target: String(row?.target ?? "").trim(),
      relation: String(row?.relation ?? "").trim() || DEFAULT_RELATION,
    }));
  }
  return (payload?.triplets ?? []).map((row) => ({
    source: String(row?.source ?? row?.prerequisite ?? "").trim(),
    target: String(row?.target ?? row?.dependent ?? "").trim(),
    relation: String(row?.relation ?? "").trim() || DEFAULT_RELATION,
  }));
}

function sanitizeKgDescriptionText(value) {
  return String(value ?? "")
    .replaceAll("助教コード由来", "既存実装由来")
    .replaceAll("助教コード", "既存実装")
    .replaceAll("助教", "");
}

function distributedOffsets(count, spread) {
  if (count <= 1) return [0];
  const safeSpread = Math.max(0, spread);
  const start = -safeSpread / 2;
  const step = count === 1 ? 0 : safeSpread / (count - 1);
  return Array.from({ length: count }, (_row, index) => Math.round(start + step * index));
}

function groupedEdgesForDisplay(payload) {
  const grouped = new Map();
  for (const row of relationRowsFromPayload(payload)) {
    const source = String(row?.source ?? "").trim();
    const target = String(row?.target ?? "").trim();
    const relation = String(row?.relation ?? "").trim() || DEFAULT_RELATION;
    if (!source || !target || source === target) continue;
    const key = `${source}→${target}`;
    if (!grouped.has(key)) {
      grouped.set(key, { source, target, relations: new Set() });
    }
    grouped.get(key).relations.add(relation);
  }
  return [...grouped.values()].map((row) => ({
    source: row.source,
    target: row.target,
    relations: [...row.relations].sort((left, right) => {
      if (left === DEFAULT_RELATION && right !== DEFAULT_RELATION) return -1;
      if (right === DEFAULT_RELATION && left !== DEFAULT_RELATION) return 1;
      return left.localeCompare(right, "en");
    }),
  }));
}

function relationLabelForDisplay(relations) {
  const rows = Array.isArray(relations) ? relations.filter(Boolean) : [];
  const nonDefault = rows.filter((row) => row !== DEFAULT_RELATION);
  if (nonDefault.length === 0) return "";
  const labels = nonDefault.map((row) => RELATION_STYLES[row]?.label ?? row);
  if (labels.length <= 2) return labels.join(" / ");
  return `${labels.slice(0, 2).join(" / ")} +${labels.length - 2}`;
}

function edgePriorityScore(edge) {
  return Math.max(...(edge.relations ?? [DEFAULT_RELATION]).map((relation) => RELATION_PRIORITIES[relation] ?? 20));
}

function primaryRelationFor(relations) {
  const rows = Array.isArray(relations) ? relations.filter(Boolean) : [];
  const nonDefault = rows.filter((row) => row !== DEFAULT_RELATION);
  if (nonDefault.length === 1) return nonDefault[0];
  if (nonDefault.length > 1) return "multi";
  return DEFAULT_RELATION;
}

function relationStyleFor(relations) {
  return RELATION_STYLES[primaryRelationFor(relations)] ?? RELATION_STYLES[DEFAULT_RELATION];
}

function buildAdjacency(edgeRows) {
  const adjacency = new Map();
  for (const row of edgeRows) {
    if (!adjacency.has(row.source)) adjacency.set(row.source, new Set());
    adjacency.get(row.source).add(row.target);
    if (!adjacency.has(row.target)) adjacency.set(row.target, new Set());
  }
  return adjacency;
}

function hasAlternativePath(adjacency, source, target) {
  const startTargets = [...(adjacency.get(source) ?? [])].filter((nodeId) => nodeId !== target);
  if (!startTargets.length) return false;
  const queue = [...startTargets];
  const visited = new Set([source]);

  while (queue.length) {
    const current = queue.shift();
    if (!current || visited.has(current)) continue;
    if (current === target) return true;
    visited.add(current);
    for (const next of adjacency.get(current) ?? []) {
      if (!visited.has(next)) queue.push(next);
    }
  }
  return false;
}

function transitiveReductionEdges(edgeRows) {
  const adjacency = buildAdjacency(edgeRows);
  return edgeRows.filter((row) => !hasAlternativePath(adjacency, row.source, row.target));
}

function barycenterScore(nodeId, neighbors, orderIndex, fallback) {
  const indices = [...neighbors]
    .map((row) => orderIndex.get(row))
    .filter((row) => Number.isFinite(row));
  if (!indices.length) return fallback;
  return indices.reduce((sum, row) => sum + row, 0) / indices.length;
}

function computeMaxIncoming(edgeRows) {
  const counts = new Map();
  for (const row of edgeRows) {
    counts.set(row.target, (counts.get(row.target) ?? 0) + 1);
  }
  return Math.max(0, ...counts.values());
}

function buildCompactDisplayEdges(edgeRows, levelMap) {
  const incomingByTarget = new Map();
  for (const row of edgeRows) {
    if (!incomingByTarget.has(row.target)) incomingByTarget.set(row.target, []);
    incomingByTarget.get(row.target).push(row);
  }

  const selected = [];
  const selectedKeys = new Set();
  for (const [target, incoming] of incomingByTarget.entries()) {
    const ordered = [...incoming].sort((left, right) => {
      const leftScore = edgePriorityScore(left);
      const rightScore = edgePriorityScore(right);
      if (leftScore !== rightScore) return rightScore - leftScore;

      const leftSourceLevel = levelMap.get(left.source) ?? 0;
      const rightSourceLevel = levelMap.get(right.source) ?? 0;
      const targetLevel = levelMap.get(target) ?? 0;
      const leftGap = targetLevel - leftSourceLevel;
      const rightGap = targetLevel - rightSourceLevel;
      const leftForward = leftGap > 0 ? 0 : 1;
      const rightForward = rightGap > 0 ? 0 : 1;
      if (leftForward !== rightForward) return leftForward - rightForward;
      if (Math.abs(leftGap) !== Math.abs(rightGap)) return Math.abs(leftGap) - Math.abs(rightGap);
      return left.source.localeCompare(right.source, "ja");
    });
    const picked = ordered[0];
    if (!picked) continue;
    const key = `${picked.source}→${picked.target}`;
    if (selectedKeys.has(key)) continue;
    selectedKeys.add(key);
    selected.push(picked);
  }

  return selected;
}

function buildDisplayGraphData(payload, graphMode = "organized") {
  const nodes = new Map();
  const outMap = new Map();
  const inMap = new Map();
  const graphNodes = payload?.graph?.nodes ?? [];
  const groupedEdges = groupedEdgesForDisplay(payload);
  const hasOnlyPrerequisiteEdges = groupedEdges.every((row) => row.relations.every((relation) => relation === DEFAULT_RELATION));

  for (const row of graphNodes) {
    const id = String(row?.id ?? "").trim();
    if (!id) continue;
    nodes.set(id, {
      id,
      role: row?.role ?? null,
      inDegree: Number(row?.in_degree ?? 0) || 0,
      outDegree: Number(row?.out_degree ?? 0) || 0,
    });
    if (!outMap.has(id)) outMap.set(id, new Set());
    if (!inMap.has(id)) inMap.set(id, new Set());
  }

  for (const row of groupedEdges) {
    const source = String(row?.source ?? "").trim();
    const target = String(row?.target ?? "").trim();
    if (!source || !target) continue;
    if (!nodes.has(source)) nodes.set(source, { id: source });
    if (!nodes.has(target)) nodes.set(target, { id: target });
    if (!outMap.has(source)) outMap.set(source, new Set());
    if (!inMap.has(target)) inMap.set(target, new Set());
    outMap.get(source).add(target);
    inMap.get(target).add(source);
    if (!outMap.has(target)) outMap.set(target, new Set());
    if (!inMap.has(source)) inMap.set(source, new Set());
  }

  const nodeIds = [...nodes.keys()];
  if (!nodeIds.length) {
    return { width: 860, height: 140, nodes: [], edges: [] };
  }

  const indegree = new Map(nodeIds.map((id) => [id, (inMap.get(id)?.size ?? 0)]));
  const levelMap = new Map(nodeIds.map((id) => [id, 0]));
  const queue = nodeIds.filter((id) => (indegree.get(id) ?? 0) === 0).sort((a, b) => a.localeCompare(b, "ja"));
  const visited = new Set();

  while (queue.length) {
    const current = queue.shift();
    if (!current || visited.has(current)) continue;
    visited.add(current);
    const currentLevel = levelMap.get(current) ?? 0;
    const targets = [...(outMap.get(current) ?? [])].sort((a, b) => a.localeCompare(b, "ja"));
    for (const target of targets) {
      levelMap.set(target, Math.max(levelMap.get(target) ?? 0, currentLevel + 1));
      indegree.set(target, (indegree.get(target) ?? 0) - 1);
      if ((indegree.get(target) ?? 0) <= 0) {
        queue.push(target);
      }
    }
  }

  const remaining = nodeIds.filter((id) => !visited.has(id)).sort((a, b) => a.localeCompare(b, "ja"));
  const fallbackBaseLevel = Math.max(0, ...[...levelMap.values()]) + 1;
  remaining.forEach((id, index) => {
    levelMap.set(id, fallbackBaseLevel + index);
  });

  const maxIncoming = computeMaxIncoming(groupedEdges);
  const shouldCompact = graphMode === "organized" && (
    !hasOnlyPrerequisiteEdges
    || !payload?.summary?.is_dag
    || groupedEdges.length > Math.max(nodeIds.length + 1, 8)
    || maxIncoming > 2
  );
  const edges = graphMode === "full"
    ? groupedEdges
    : shouldCompact
      ? buildCompactDisplayEdges(groupedEdges, levelMap)
      : payload?.summary?.is_dag && hasOnlyPrerequisiteEdges
        ? transitiveReductionEdges(groupedEdges)
        : groupedEdges;

  const displayNodes = nodeIds
    .map((id) => {
      const meta = nodes.get(id) ?? { id };
      const inDegree = Number(meta.inDegree ?? inMap.get(id)?.size ?? 0) || 0;
      const outDegree = Number(meta.outDegree ?? outMap.get(id)?.size ?? 0) || 0;
      const role = meta.role ?? (inDegree === 0 ? "root" : outDegree === 0 ? "leaf" : "intermediate");
      const fill = role === "root" ? "#FFB6B6" : role === "leaf" ? "#B6E2FF" : "#C8E6C9";
      const labelLines = wrapLabel(id);
      return {
        id,
        role,
        inDegree,
        outDegree,
        labelLines,
        width: KG_NODE_WIDTH,
        height: KG_NODE_BASE_HEIGHT + Math.max(0, labelLines.length - 1) * KG_NODE_LINE_HEIGHT,
        fill,
      };
    })
    .sort((left, right) => {
      const rolePriority = { root: 0, intermediate: 1, leaf: 2 };
      const leftRole = rolePriority[left.role] ?? 3;
      const rightRole = rolePriority[right.role] ?? 3;
      if (leftRole !== rightRole) return leftRole - rightRole;
      if (left.inDegree !== right.inDegree) return left.inDegree - right.inDegree;
      if (left.outDegree !== right.outDegree) return right.outDegree - left.outDegree;
      return left.id.localeCompare(right.id, "ja");
    });

  const displayEdges = edges.map((row) => ({
    key: `${row.source}→${row.target}`,
    sourceId: row.source,
    targetId: row.target,
    relations: row.relations ?? [DEFAULT_RELATION],
    relationLabel: relationLabelForDisplay(row.relations),
    relationStyle: relationStyleFor(row.relations),
  }));

  return {
    graphMode,
    compacted: shouldCompact,
    groupedEdgesCount: groupedEdges.length,
    hiddenEdges: Math.max(0, groupedEdges.length - displayEdges.length),
    shownEdges: displayEdges.length,
    nodes: displayNodes,
    edges: displayEdges,
    relationLegend: [...new Map(
      displayEdges.map((edge) => [edge.relationStyle.label, edge.relationStyle]),
    ).values()],
  };
}

function polylinePathFromPoints(points) {
  if (!Array.isArray(points) || !points.length) return "";
  return points.reduce((path, point, index) => (
    `${path}${index === 0 ? "M" : " L"} ${Math.round(point.x)} ${Math.round(point.y)}`
  ), "");
}

function polylineMidpoint(points) {
  if (!Array.isArray(points) || !points.length) {
    return { x: 0, y: 0 };
  }
  if (points.length === 1) return points[0];

  const segments = [];
  let totalLength = 0;
  for (let index = 1; index < points.length; index += 1) {
    const start = points[index - 1];
    const end = points[index];
    const length = Math.hypot(end.x - start.x, end.y - start.y);
    segments.push({ start, end, length });
    totalLength += length;
  }

  if (totalLength <= 0) {
    return points[Math.floor(points.length / 2)];
  }

  const targetLength = totalLength / 2;
  let walked = 0;
  for (const segment of segments) {
    if (walked + segment.length >= targetLength) {
      const ratio = (targetLength - walked) / Math.max(segment.length, 1);
      return {
        x: segment.start.x + (segment.end.x - segment.start.x) * ratio,
        y: segment.start.y + (segment.end.y - segment.start.y) * ratio,
      };
    }
    walked += segment.length;
  }

  return points[points.length - 1];
}

async function buildElkGraphLayout(payload, graphMode = "organized") {
  const prepared = buildDisplayGraphData(payload, graphMode);
  if (!prepared.nodes.length) {
    return { width: 860, height: 140, nodes: [], edges: [], ...prepared };
  }

  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.edgeRouting": graphMode === "full" ? "POLYLINE" : "ORTHOGONAL",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": "BRANDES_KOEPF",
      "elk.spacing.nodeNode": "36",
      "elk.layered.spacing.nodeNodeBetweenLayers": graphMode === "full" ? "80" : "96",
      "elk.spacing.edgeNode": "24",
      "elk.spacing.edgeEdge": "18",
    },
    children: prepared.nodes.map((node) => ({
      id: node.id,
      width: node.width,
      height: node.height,
    })),
    edges: prepared.edges.map((edge) => ({
      id: edge.key,
      sources: [edge.sourceId],
      targets: [edge.targetId],
    })),
  };

  const layouted = await elk.layout(elkGraph);
  const nodeLayout = new Map((layouted.children ?? []).map((node) => [node.id, node]));
  const edgeLayout = new Map((layouted.edges ?? []).map((edge) => [edge.id, edge]));

  const laidOutNodes = prepared.nodes.map((node) => {
    const layoutNode = nodeLayout.get(node.id) ?? { x: 0, y: 0, width: node.width, height: node.height };
    return {
      ...node,
      x: Math.round((layoutNode.x ?? 0) + KG_LAYOUT_PADDING),
      y: Math.round((layoutNode.y ?? 0) + KG_LAYOUT_PADDING),
      width: Math.round(layoutNode.width ?? node.width),
      height: Math.round(layoutNode.height ?? node.height),
    };
  });

  const laidOutEdges = prepared.edges.map((edge) => {
    const sourceNode = laidOutNodes.find((node) => node.id === edge.sourceId);
    const targetNode = laidOutNodes.find((node) => node.id === edge.targetId);
    const fallbackPoints = sourceNode && targetNode
      ? [
          { x: sourceNode.x + sourceNode.width / 2, y: sourceNode.y + sourceNode.height },
          { x: targetNode.x + targetNode.width / 2, y: targetNode.y },
        ]
      : [];
    const section = edgeLayout.get(edge.key)?.sections?.[0];
    const points = section
      ? [
          section.startPoint,
          ...(section.bendPoints ?? []),
          section.endPoint,
        ].filter(Boolean).map((point) => ({
          x: point.x + KG_LAYOUT_PADDING,
          y: point.y + KG_LAYOUT_PADDING,
        }))
      : fallbackPoints;
    const labelPoint = polylineMidpoint(points);
    return {
      ...edge,
      path: polylinePathFromPoints(points),
      labelX: Math.round(labelPoint.x),
      labelY: Math.round(labelPoint.y - 10),
    };
  });

  return {
    ...prepared,
    width: Math.max(760, Math.round((layouted.width ?? 720) + KG_LAYOUT_PADDING * 2)),
    height: Math.max(140, Math.round((layouted.height ?? 80) + KG_LAYOUT_PADDING * 2)),
    nodes: laidOutNodes,
    edges: laidOutEdges,
  };
}

function buildFallbackGraphLayout(payload, graphMode = "organized") {
  const prepared = buildDisplayGraphData(payload, graphMode);
  const { nodes: displayNodes, edges: preparedEdges, groupedEdgesCount } = prepared;
  const nodeIds = displayNodes.map((node) => node.id);
  const nodeMetaById = new Map(displayNodes.map((node) => [node.id, node]));
  const outMap = new Map(nodeIds.map((id) => [id, new Set()]));
  const inMap = new Map(nodeIds.map((id) => [id, new Set()]));

  for (const edge of preparedEdges) {
    if (!outMap.has(edge.sourceId)) outMap.set(edge.sourceId, new Set());
    if (!inMap.has(edge.targetId)) inMap.set(edge.targetId, new Set());
    if (!outMap.has(edge.targetId)) outMap.set(edge.targetId, new Set());
    if (!inMap.has(edge.sourceId)) inMap.set(edge.sourceId, new Set());
    outMap.get(edge.sourceId).add(edge.targetId);
    inMap.get(edge.targetId).add(edge.sourceId);
  }

  if (!nodeIds.length) {
    return { width: 860, height: 140, nodes: [], edges: [], ...prepared };
  }

  const levelMap = new Map(nodeIds.map((id) => [id, 0]));
  const indegree = new Map(nodeIds.map((id) => [id, inMap.get(id)?.size ?? 0]));
  const queue = nodeIds.filter((id) => (indegree.get(id) ?? 0) === 0).sort((a, b) => a.localeCompare(b, "ja"));
  const visited = new Set();

  while (queue.length) {
    const current = queue.shift();
    if (!current || visited.has(current)) continue;
    visited.add(current);
    const currentLevel = levelMap.get(current) ?? 0;
    const targets = [...(outMap.get(current) ?? [])].sort((a, b) => a.localeCompare(b, "ja"));
    for (const target of targets) {
      levelMap.set(target, Math.max(levelMap.get(target) ?? 0, currentLevel + 1));
      indegree.set(target, (indegree.get(target) ?? 0) - 1);
      if ((indegree.get(target) ?? 0) <= 0) {
        queue.push(target);
      }
    }
  }

  const remaining = nodeIds.filter((id) => !visited.has(id)).sort((a, b) => a.localeCompare(b, "ja"));
  const fallbackBaseLevel = Math.max(0, ...[...levelMap.values()]) + 1;
  remaining.forEach((id, index) => {
    levelMap.set(id, fallbackBaseLevel + index);
  });

  const grouped = new Map();
  for (const id of nodeIds) {
    const level = levelMap.get(id) ?? 0;
    if (!grouped.has(level)) grouped.set(level, []);
    grouped.get(level).push(id);
  }

  const orderIndex = new Map();
  const sortedLevels = [...grouped.keys()].sort((a, b) => a - b);
  for (const level of sortedLevels) {
    const ids = grouped.get(level) ?? [];
    ids.sort((left, right) => {
      const leftScore = barycenterScore(left, inMap.get(left) ?? [], orderIndex, Number.MAX_SAFE_INTEGER / 4);
      const rightScore = barycenterScore(right, inMap.get(right) ?? [], orderIndex, Number.MAX_SAFE_INTEGER / 4);
      if (leftScore !== rightScore) return leftScore - rightScore;
      return left.localeCompare(right, "ja");
    });
    ids.forEach((id, index) => orderIndex.set(id, index));
  }

  const paddingX = 24;
  const paddingY = 24;
  const colGap = 24;
  const rowGap = 116;
  const maxColumns = Math.max(...[...grouped.values()].map((rows) => rows.length));
  const canvasWidth = Math.max(760, paddingX * 2 + maxColumns * KG_NODE_WIDTH + Math.max(0, maxColumns - 1) * colGap);

  const laidOutNodes = [];
  for (const [level, ids] of [...grouped.entries()].sort((a, b) => a[0] - b[0])) {
    const rowWidth = ids.length * KG_NODE_WIDTH + Math.max(0, ids.length - 1) * colGap;
    const rowStartX = Math.round((canvasWidth - rowWidth) / 2);

    ids.forEach((id, index) => {
      const meta = nodeMetaById.get(id) ?? { id, labelLines: wrapLabel(id), fill: "#C8E6C9", inDegree: 0, outDegree: 0, height: KG_NODE_BASE_HEIGHT };
      const x = rowStartX + index * (KG_NODE_WIDTH + colGap);
      const y = paddingY + level * rowGap;
      laidOutNodes.push({
        id,
        labelLines: meta.labelLines,
        x,
        y,
        width: KG_NODE_WIDTH,
        height: meta.height,
        inDegree: meta.inDegree,
        outDegree: meta.outDegree,
        fill: meta.fill,
      });
    });
  }

  const nodeLookup = new Map(laidOutNodes.map((node) => [node.id, node]));
  const outgoingEdgesByNode = new Map();
  const incomingEdgesByNode = new Map();
  const edgeRows = [];

  for (const row of preparedEdges) {
    const source = nodeLookup.get(row.sourceId);
    const target = nodeLookup.get(row.targetId);
    if (!source || !target) continue;
    const edge = {
      sourceId: row.sourceId,
      targetId: row.targetId,
      relations: row.relations ?? [DEFAULT_RELATION],
      relationLabel: row.relationLabel,
      relationStyle: row.relationStyle,
      source,
      target,
    };
    edgeRows.push(edge);
    if (!outgoingEdgesByNode.has(edge.sourceId)) outgoingEdgesByNode.set(edge.sourceId, []);
    if (!incomingEdgesByNode.has(edge.targetId)) incomingEdgesByNode.set(edge.targetId, []);
    outgoingEdgesByNode.get(edge.sourceId).push(edge);
    incomingEdgesByNode.get(edge.targetId).push(edge);
  }

  const sourcePortOffsets = new Map();
  for (const [nodeId, nodeEdges] of outgoingEdgesByNode.entries()) {
    const sorted = [...nodeEdges].sort((left, right) => {
      if (left.target.x !== right.target.x) return left.target.x - right.target.x;
      return left.target.y - right.target.y;
    });
    const offsets = distributedOffsets(sorted.length, Math.min(110, 28 * Math.max(1, sorted.length - 1)));
    sorted.forEach((edge, index) => {
      sourcePortOffsets.set(`${edge.sourceId}->${edge.targetId}`, offsets[index] ?? 0);
    });
  }

  const targetPortOffsets = new Map();
  for (const [nodeId, nodeEdges] of incomingEdgesByNode.entries()) {
    const sorted = [...nodeEdges].sort((left, right) => {
      if (left.source.x !== right.source.x) return left.source.x - right.source.x;
      return left.source.y - right.source.y;
    });
    const offsets = distributedOffsets(sorted.length, Math.min(110, 28 * Math.max(1, sorted.length - 1)));
    sorted.forEach((edge, index) => {
      targetPortOffsets.set(`${edge.sourceId}->${edge.targetId}`, offsets[index] ?? 0);
    });
  }

  const laidOutEdges = [];
  edgeRows.forEach((edge, edgeIndex) => {
    const edgeKey = `${edge.sourceId}->${edge.targetId}`;
    const x1 = edge.source.x + edge.source.width / 2 + (sourcePortOffsets.get(edgeKey) ?? 0);
    const y1 = edge.source.y + edge.source.height;
    const x2 = edge.target.x + edge.target.width / 2 + (targetPortOffsets.get(edgeKey) ?? 0);
    const y2 = edge.target.y;
    const edgeDepth = Math.max(16, 18 + Math.abs(sourcePortOffsets.get(edgeKey) ?? 0) * 0.18);
    const shoulderY = y1 + edgeDepth;
    const targetShoulderY = y2 - edgeDepth;
    const verticalDirection = y2 >= y1 ? 1 : -1;
    const midpointY = verticalDirection > 0
      ? y1 + Math.max(28, (y2 - y1) * 0.48)
      : Math.min(y1 - 42, y2 - 26);
    const bendMagnitude = ((edgeIndex % 2 === 0 ? 1 : -1) * (12 + (edgeIndex % 3) * 8))
      + ((sourcePortOffsets.get(edgeKey) ?? 0) - (targetPortOffsets.get(edgeKey) ?? 0)) * 0.22;
    const controlX1 = x1 + bendMagnitude;
    const controlX2 = x2 - bendMagnitude;
    const path = verticalDirection > 0
      ? `M ${x1} ${y1} L ${x1} ${shoulderY} C ${controlX1} ${midpointY}, ${controlX2} ${midpointY}, ${x2} ${targetShoulderY} L ${x2} ${y2}`
      : `M ${x1} ${edge.source.y + edge.source.height / 2} C ${controlX1} ${midpointY}, ${controlX2} ${midpointY}, ${x2} ${edge.target.y + edge.target.height / 2}`;
    const labelX = Math.round((x1 + x2 + controlX1 + controlX2) / 4);
    const labelY = Math.round(verticalDirection > 0 ? midpointY - 8 : midpointY - 10);
    laidOutEdges.push({
      key: edgeKey,
      path,
      relationLabel: edge.relationLabel,
      relationCount: edge.relations.length,
      relationStyle: edge.relationStyle,
      labelX,
      labelY,
      verticalDirection,
    });
  });

  const maxY = Math.max(...laidOutNodes.map((node) => node.y + node.height), 0);
  const canvasHeight = maxY + paddingY + 24;

  return {
    width: canvasWidth,
    height: canvasHeight,
    nodes: laidOutNodes,
    edges: laidOutEdges,
    ...prepared,
    shownEdges: laidOutEdges.length,
  };
}

function formatKgError(err) {
  const raw = String(err?.message || err || "failed");
  if (raw === "Failed to fetch") {
    return "バックエンドに接続できませんでした。`make backend` が起動中か確認してください。";
  }
  return raw;
}

function timeText(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString("ja-JP", { hour12: false });
  } catch {
    return String(value);
  }
}

async function hashPdfFile(file) {
  if (!file) return null;
  const buffer = await file.arrayBuffer();
  const digest = await globalThis.crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((n) => n.toString(16).padStart(2, "0")).join("");
}

function mergeComparisonResults(current, incoming) {
  const currentRows = Array.isArray(current) ? current : [];
  const incomingRows = Array.isArray(incoming) ? incoming : [];
  const byId = new Map(currentRows.map((row) => [row.result_id, row]));
  for (const row of incomingRows) {
    if (row?.result_id) byId.set(row.result_id, row);
  }

  const orderedIds = [];
  for (const row of incomingRows) {
    if (row?.result_id && !orderedIds.includes(row.result_id)) orderedIds.push(row.result_id);
  }
  for (const row of currentRows) {
    if (row?.result_id && !orderedIds.includes(row.result_id)) orderedIds.push(row.result_id);
  }
  return orderedIds.slice(0, 3).map((id) => byId.get(id)).filter(Boolean);
}

function pillStyle(active, disabled = false) {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 10px",
    borderRadius: 999,
    border: `1px solid ${active ? "rgba(130,178,255,.42)" : "rgba(255,255,255,.08)"}`,
    background: active ? "rgba(91,141,239,.16)" : "rgba(255,255,255,.02)",
    color: disabled ? "var(--tm)" : active ? "var(--ac)" : "var(--ts)",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
    transition: "var(--tr)",
    userSelect: "none",
  };
}

function SummaryBadge({ children, tone = "default" }) {
  const palette = tone === "good"
    ? { bg: "var(--gd)", bd: "rgba(76,175,130,.28)", color: "var(--gr)" }
    : tone === "warn"
      ? { bg: "var(--amd)", bd: "rgba(232,169,75,.28)", color: "var(--am)" }
      : { bg: "var(--s2)", bd: "var(--bd)", color: "var(--ts)" };
  return (
    <span style={{ padding: "3px 8px", borderRadius: 999, background: palette.bg, border: `1px solid ${palette.bd}`, color: palette.color, fontSize: 10 }}>
      {children}
    </span>
  );
}

function profileKeyFor({ difficulty, detail, mode }) {
  return `${difficulty}.${detail}.${mode}`;
}

function selectScoringProfile(payload, scoreProfile) {
  const scoring = payload?.scoring ?? {};
  const profiles = scoring?.profiles ?? {};
  const key = profileKeyFor(scoreProfile);
  return {
    key,
    profile: profiles[key] ?? null,
  };
}

function formatScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toFixed(3);
}

function ConceptScoreList({ title, concepts, emptyText = "該当なし" }) {
  const rows = Array.isArray(concepts) ? concepts : [];
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--tp)" }}>{title}</div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 10, color: "var(--tm)" }}>{emptyText}</div>
      ) : (
        <div style={{ display: "grid", gap: 5 }}>
          {rows.map((row, index) => (
            <div key={`${title}_${row?.id ?? index}`} style={{ display: "grid", gap: 3, padding: "7px 8px", borderRadius: 8, border: "1px solid rgba(255,255,255,.05)", background: "rgba(255,255,255,.02)", fontSize: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <span style={{ color: "#fff", fontWeight: 700 }}>{index + 1}. {row?.id ?? "—"}</span>
                <span style={{ color: "var(--ac)" }}>{formatScore(row?.adjusted_score ?? row?.degree_centrality)}</span>
              </div>
              {row?.reason && <div style={{ color: "var(--tm)", lineHeight: 1.45 }}>{row.reason}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function GraphPreview({ payload, compact = false, graphMode = "organized" }) {
  const [graph, setGraph] = useState(null);
  const [graphError, setGraphError] = useState(null);
  const [graphLoading, setGraphLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setGraphLoading(true);
    setGraphError(null);

    buildElkGraphLayout(payload, graphMode)
      .then((nextGraph) => {
        if (cancelled) return;
        setGraph(nextGraph);
      })
      .catch((error) => {
        console.warn("ELK graph layout failed, falling back:", error, payload);
        try {
          const fallbackGraph = buildFallbackGraphLayout(payload, graphMode);
          if (cancelled) return;
          setGraph(fallbackGraph);
        } catch (fallbackError) {
          console.warn("KG graph preview fallback failed:", fallbackError, payload);
          if (cancelled) return;
          setGraphError(fallbackError);
        }
      })
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [payload, graphMode]);

  if (graphError) {
    return (
      <div style={{ fontSize: 10, color: "var(--rd)", lineHeight: 1.6 }}>
        グラフ表示に失敗しました。Triplets や要約は引き続き確認できます。
      </div>
    );
  }

  if (!graph) {
    return (
      <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
        レイアウトを計算中です...
      </div>
    );
  }

  const viewportHeight = compact
    ? 220
    : Math.max(300, Math.min(640, Math.round(graph.height * 0.82)));

  if (!graph.nodes.length) {
    return <div style={{ fontSize: 10, color: "var(--tm)" }}>図示できるノードがまだありません。</div>;
  }

  return (
    <div style={{ display: "grid", gap: 8 }}>
      {!compact && (
        <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
          {graph.graphMode === "full"
            ? `全エッジ表示: 図に ${graph.shownEdges} 本の関係をそのまま表示しています。`
            : graph.compacted || graph.hiddenEdges > 0
              ? `整理表示: 図では主要な関係 ${graph.shownEdges} 本を表示しています。${graph.hiddenEdges > 0 ? ` 残り ${graph.hiddenEdges} 本は Triplets に残しています。` : ""}`
              : `整理表示: 図に ${graph.shownEdges} 本の関係を表示しています。`}
          {graphLoading ? " レイアウトを更新中です..." : ""}
        </div>
      )}
      {!compact && graph.relationLegend?.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {graph.relationLegend.map((row) => (
            <span
              key={row.label}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "3px 8px",
                borderRadius: 999,
                background: "rgba(255,255,255,.03)",
                border: "1px solid rgba(255,255,255,.08)",
                color: "var(--ts)",
                fontSize: 10,
              }}
            >
              <span style={{ width: 10, height: 10, borderRadius: 999, background: row.color, boxShadow: `0 0 0 1px ${row.color}33` }} />
              {row.label}
            </span>
          ))}
        </div>
      )}
      <div
        style={{
          overflow: "hidden",
          borderRadius: 10,
          border: "1px solid rgba(255,255,255,.05)",
          background: "linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.01))",
          padding: compact ? 6 : 10,
        }}
      >
      <svg
        viewBox={`0 0 ${graph.width} ${graph.height}`}
        preserveAspectRatio="xMidYMin meet"
        style={{
          width: "100%",
          height: viewportHeight,
          display: "block",
          background: "transparent",
        }}
      >
        <defs>
          {graph.relationLegend.map((row) => (
            <marker
              key={`marker_${row.label}`}
              id={`kg-compare-arrow-${row.label}`}
              markerWidth="10"
              markerHeight="10"
              refX="8"
              refY="5"
              orient="auto"
              markerUnits="strokeWidth"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={row.color} />
            </marker>
          ))}
        </defs>

        {graph.edges.map((edge) => (
          <g key={edge.key}>
            <path
              d={edge.path}
              fill="none"
              stroke={edge.relationStyle?.color ?? "#7a8ea8"}
              strokeWidth={edge.relationLabel ? "2.3" : "2"}
              markerEnd={`url(#kg-compare-arrow-${edge.relationStyle?.label ?? "前提"})`}
              opacity="0.95"
            />
            {edge.relationLabel && (
              <>
                {(() => {
                  const labelWidth = Math.max(78, Math.min(176, edge.relationLabel.length * 8 + 22));
                  return (
                    <>
                      <rect
                        x={edge.labelX - labelWidth / 2}
                        y={edge.labelY - 12}
                        width={labelWidth}
                        height="20"
                        rx="10"
                        ry="10"
                        fill="rgba(20,24,30,.86)"
                        stroke={`${edge.relationStyle?.color ?? "#7a8ea8"}55`}
                      />
                      <text
                        x={edge.labelX}
                        y={edge.labelY + 2.5}
                        textAnchor="middle"
                        fontSize="11"
                        fontWeight="700"
                        fontFamily="var(--fm)"
                        fill={edge.relationStyle?.color ?? "#dbe6ff"}
                      >
                        {edge.relationLabel}
                      </text>
                    </>
                  );
                })()}
              </>
            )}
          </g>
        ))}

        {graph.nodes.map((node) => (
          <g key={node.id} transform={`translate(${node.x}, ${node.y})`}>
            <rect
              x="0"
              y="0"
              rx="10"
              ry="10"
              width={node.width}
              height={node.height}
              fill={node.fill}
              stroke="rgba(20,24,30,.38)"
              strokeWidth="1.25"
            />
            {node.labelLines.map((line, index) => (
              <text
                key={`${node.id}_${index}`}
                x={node.width / 2}
                y={24 + index * 16}
                textAnchor="middle"
                fontSize="13"
                fontFamily="var(--fm)"
                fill="#1c2129"
              >
                {line}
              </text>
            ))}
            <text
              x={node.width / 2}
              y={node.height - 10}
              textAnchor="middle"
              fontSize="11"
              fontFamily="var(--fm)"
              fill="rgba(28,33,41,.82)"
            >
              [{node.inDegree}→{node.outDegree}]
            </text>
          </g>
        ))}
      </svg>
      </div>
    </div>
  );
}

function ResultOverviewCard({ payload, selected, onToggle }) {
  const summary = payload?.summary ?? {};
  const variant = payload?.variant ?? {};
  const descriptionText = sanitizeKgDescriptionText(variant.description ?? "—");
  const summaryText = sanitizeKgDescriptionText(summary.summary_text || "比較対象に残すかどうかをここで選びます。");
  const baseTop = payload?.scoring?.base_top_concepts ?? [];
  return (
    <button
      onClick={onToggle}
      style={{
        textAlign: "left",
        padding: 10,
        borderRadius: 12,
        border: `1px solid ${selected ? "rgba(130,178,255,.38)" : "rgba(255,255,255,.06)"}`,
        background: selected ? "rgba(91,141,239,.1)" : "rgba(255,255,255,.02)",
        display: "grid",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>
            {selected ? "✓ " : ""}{variant.label ?? "variant"}
          </div>
          <div style={{ fontSize: 9, color: "var(--tm)", lineHeight: 1.5 }}>
            {descriptionText}
          </div>
        </div>
        <div style={{ fontSize: 9, color: "var(--tm)", flexShrink: 0 }}>{timeText(payload?.created_at)}</div>
      </div>
      <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55, minHeight: 30 }}>
        {summaryText}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <SummaryBadge>triplet {summary.triplet_count ?? 0}</SummaryBadge>
        <SummaryBadge>node {summary.node_count ?? 0}</SummaryBadge>
        <SummaryBadge tone={summary.is_dag ? "good" : "warn"}>{summary.is_dag ? "循環なし (DAG)" : "循環あり"}</SummaryBadge>
      </div>
      {baseTop.length > 0 && (
        <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.55 }}>
          次数中心性Top: {baseTop.slice(0, 3).map((row) => row.id).join(" / ")}
        </div>
      )}
    </button>
  );
}

function KgResultCard({ payload, onRemove, visibleSections, graphMode, scoreProfile }) {
  const summary = payload?.summary ?? {};
  const triplets = payload?.triplets ?? [];
  const variant = payload?.variant ?? {};
  const notes = (summary?.notes ?? []).map((note) => sanitizeKgDescriptionText(note));
  const visualization = payload?.visualization ?? {};
  const structured = payload?.structured ?? null;
  const nodeDetails = structured?.nodes ?? [];
  const edgeDetails = structured?.edges ?? [];
  const orderPlan = payload?.order_plan ?? null;
  const analysisPanels = Array.isArray(payload?.analysis_panels) ? payload.analysis_panels : [];
  const scoring = payload?.scoring ?? {};
  const scoringMetrics = scoring?.metrics ?? {};
  const baseTop = scoring?.base_top_concepts ?? [];
  const selectedScoring = selectScoringProfile(payload, scoreProfile);
  const topConcepts = selectedScoring.profile?.top_concepts ?? [];
  const descriptionText = sanitizeKgDescriptionText(variant.description ?? "—");
  const summaryText = sanitizeKgDescriptionText(summary.summary_text || "summary なし");
  const visible = new Set(visibleSections);
  const showSummary = visible.has("summary");
  const showGraph = visible.has("graph");
  const showTriplets = visible.has("triplets");
  const showEdgeDetails = visible.has("edge_details");
  const showNodeDetails = visible.has("node_details");
  const showOrderPlan = visible.has("order_plan");
  const showAnalysis = visible.has("analysis");
  const showRaw = visible.has("raw");
  const showArtifacts = visible.has("artifacts");

  return (
    <section style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 10, border: "1px solid rgba(255,255,255,.06)", borderRadius: 12, background: "linear-gradient(180deg, rgba(255,255,255,.03), rgba(255,255,255,.01))", padding: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--tp)", marginBottom: 4 }}>{variant.label ?? "variant"}</div>
          <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55 }}>{descriptionText}</div>
        </div>
        <button
          onClick={onRemove}
          style={{ padding: "3px 7px", borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--tm)", fontSize: 10 }}
        >
          ×
        </button>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <SummaryBadge>{timeText(payload?.created_at)}</SummaryBadge>
        <SummaryBadge>triplet {summary.triplet_count ?? 0}</SummaryBadge>
        <SummaryBadge>node {summary.node_count ?? 0}</SummaryBadge>
        <SummaryBadge tone={summary.is_dag ? "good" : "warn"}>{summary.is_dag ? "循環なし (DAG)" : "循環あり"}</SummaryBadge>
      </div>

      {showSummary && (
      <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.6 }}>
        {summaryText}
        {!visualization.available && visualization.reason ? ` Graphviz出力は未生成です: ${visualization.reason}` : ""}
      </div>
      )}

      {showSummary && scoring?.version && (
        <div style={{ display: "grid", gap: 8, border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>重要語句スコア</div>
            <SummaryBadge>{selectedScoring.key}</SummaryBadge>
          </div>
          <ConceptScoreList title="次数中心性Top" concepts={baseTop.slice(0, 5).map((row) => ({ ...row, adjusted_score: row.degree_centrality }))} />
          <ConceptScoreList title="この条件で詳説する語句" concepts={topConcepts} />
        </div>
      )}

      {showSummary && notes.length > 0 && (
        <div style={{ display: "grid", gap: 5 }}>
          {notes.map((note, index) => (
            <div key={`${payload.result_id}_note_${index}`} style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55 }}>
              ・{note}
            </div>
          ))}
        </div>
      )}

      {showGraph && (
      <div>
        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>Graph</div>
        <GraphPreview payload={payload} graphMode={graphMode} />
      </div>
      )}

      {showSummary && (
        <div style={{ display: "grid", gap: 5 }}>
          <div style={{ fontSize: 11, fontWeight: 700 }}>要約メモ</div>
          <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.6 }}>
            {summaryText}
          </div>
          {notes.length > 0 && (
            <div style={{ display: "grid", gap: 5 }}>
              {notes.map((note, index) => (
                <div key={`${payload.result_id}_summary_note_${index}`} style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55 }}>
                  ・{note}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showTriplets && triplets.length > 0 && (
      <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>Triplets</summary>
        <div style={{ display: "grid", gap: 6, maxHeight: 240, overflowY: "auto", paddingRight: 2, marginTop: 10 }}>
          {triplets.map((row, index) => (
            <div key={`${payload.result_id}_${index}`} style={{ fontSize: 10, lineHeight: 1.55, padding: "7px 8px", borderRadius: 8, background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.05)" }}>
              <span style={{ color: "#fff" }}>{row.prerequisite ?? row.source ?? "—"}</span>
              <span style={{ color: "var(--tm)", margin: "0 6px" }}>→</span>
              <span style={{ color: "var(--ac)" }}>{row.dependent ?? row.target ?? "—"}</span>
              {!!row.relation && (
                <span style={{ display: "inline-block", marginLeft: 8, fontSize: 9, color: "var(--tm)" }}>
                  [{row.relation}]
                </span>
              )}
            </div>
          ))}
        </div>
      </details>
      )}

      {showEdgeDetails && edgeDetails.length > 0 && (
        <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>根拠付き Edge</summary>
          <div style={{ display: "grid", gap: 7, maxHeight: 220, overflowY: "auto", paddingRight: 2 }}>
            {edgeDetails.map((row, index) => (
              <div key={`${payload.result_id}_edge_${index}`} style={{ fontSize: 10, lineHeight: 1.6, padding: "8px 9px", borderRadius: 8, background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.05)" }}>
                <div style={{ marginBottom: 4 }}>
                  <span style={{ color: "#fff" }}>{row.source}</span>
                  <span style={{ color: "var(--tm)", margin: "0 6px" }}>→</span>
                  <span style={{ color: "var(--ac)" }}>{row.target}</span>
                  {!!row.relation && (
                    <span style={{ display: "inline-block", marginLeft: 8, fontSize: 9, color: "var(--tm)" }}>
                      [{row.relation}]
                    </span>
                  )}
                </div>
                <div style={{ color: "var(--tm)" }}>
                  slide: {(row.slide_refs?.length ?? 0) > 0 ? row.slide_refs.join(", ") : "—"}
                </div>
                <div style={{ color: "var(--ts)" }}>
                  evidence: {(row.evidence_text?.length ?? 0) > 0 ? row.evidence_text.join(" / ") : "—"}
                </div>
                <div style={{ color: "var(--ts)" }}>
                  rationale: {row.rationale || "—"}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {showNodeDetails && nodeDetails.length > 0 && (
        <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>概念メモ</summary>
          <div style={{ display: "grid", gap: 7, maxHeight: 220, overflowY: "auto", paddingRight: 2 }}>
            {nodeDetails.map((row, index) => (
              <div key={`${payload.result_id}_node_${index}`} style={{ fontSize: 10, lineHeight: 1.6, padding: "8px 9px", borderRadius: 8, background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.05)" }}>
                <div style={{ marginBottom: 4, color: "#fff" }}>{row.id}</div>
                <div style={{ color: "var(--tm)" }}>importance: {row.importance ?? "—"}</div>
                <div style={{ color: "var(--tm)" }}>degree centrality: {formatScore(scoringMetrics?.[row.id]?.degree_centrality)}</div>
                <div style={{ color: "var(--tm)" }}>adjusted score: {formatScore(topConcepts.find((concept) => concept?.id === row.id)?.adjusted_score)}</div>
                <div style={{ color: "var(--tm)" }}>slide: {(row.slide_refs?.length ?? 0) > 0 ? row.slide_refs.join(", ") : "—"}</div>
                <div style={{ color: "var(--ts)" }}>evidence: {(row.evidence_text?.length ?? 0) > 0 ? row.evidence_text.join(" / ") : "—"}</div>
              </div>
            ))}
          </div>
        </details>
      )}

      {showOrderPlan && orderPlan?.steps?.length > 0 && (
        <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>説明順プラン</summary>
          <div style={{ display: "grid", gap: 7, maxHeight: 260, overflowY: "auto", paddingRight: 2 }}>
            {orderPlan.steps.map((row, index) => (
              <div key={`${payload.result_id}_step_${index}`} style={{ fontSize: 10, lineHeight: 1.6, padding: "8px 9px", borderRadius: 8, background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.05)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                  <div style={{ color: "#fff", fontWeight: 700 }}>Step {row.step}: {row.focus}</div>
                  <div style={{ color: "var(--tm)" }}>
                    slide: {(row.slide_refs?.length ?? 0) > 0 ? row.slide_refs.join(", ") : "—"}
                  </div>
                </div>
                <div style={{ color: "var(--ts)" }}>goal: {row.goal || "—"}</div>
                <div style={{ color: "var(--ts)" }}>why now: {row.why_now || "—"}</div>
                <div style={{ color: "var(--tm)" }}>
                  related: {(row.related_concepts?.length ?? 0) > 0 ? row.related_concepts.join(" / ") : "—"}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}

      {showAnalysis && analysisPanels.length > 0 && (
        <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
          <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>分析パネル</summary>
          <div style={{ display: "grid", gap: 10, marginTop: 10 }}>
          {analysisPanels.map((panel, panelIndex) => (
            <div key={`${payload.result_id}_panel_${panelIndex}`}>
              <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 8 }}>{panel?.title ?? "追加分析"}</div>
              <div style={{ display: "grid", gap: 7, maxHeight: 220, overflowY: "auto", paddingRight: 2 }}>
                {(panel?.items ?? []).map((item, itemIndex) => (
                  <div key={`${payload.result_id}_panel_${panelIndex}_${itemIndex}`} style={{ fontSize: 10, lineHeight: 1.6, padding: "8px 9px", borderRadius: 8, background: "rgba(255,255,255,.02)", border: "1px solid rgba(255,255,255,.05)" }}>
                    <div style={{ color: "#fff", marginBottom: 3 }}>{item?.label ?? "—"}</div>
                    <div style={{ color: "var(--tm)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{item?.value ?? "—"}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          </div>
        </details>
      )}

      {showRaw && (
      <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>Raw Response</summary>
        <pre style={{ margin: "10px 0 0", whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: 10, lineHeight: 1.6, color: "var(--ts)", fontFamily: "var(--fm)" }}>
          {payload?.raw_response || "—"}
        </pre>
      </details>
      )}

      {showArtifacts && (
      <details style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 10, background: "rgba(255,255,255,.02)", padding: 10 }}>
        <summary style={{ cursor: "pointer", fontSize: 11, fontWeight: 700 }}>Artifacts</summary>
        <div style={{ display: "grid", gap: 6, fontSize: 10, color: "var(--ts)", marginTop: 10, wordBreak: "break-all" }}>
          <div>result_id: {payload?.result_id ?? "—"}</div>
          <div>出力ディレクトリ: {payload?.output_dir ?? "—"}</div>
          <div>CSV: {payload?.artifacts?.triplets_csv ?? "—"}</div>
          <div>DOT: {payload?.artifacts?.dot ?? "—"}</div>
          <div>Prompt: {payload?.artifacts?.prompt ?? "—"}</div>
          <div>Raw Response: {payload?.artifacts?.raw_response ?? "—"}</div>
          <div>Metadata: {payload?.artifacts?.metadata ?? "—"}</div>
          <div>PNG: {payload?.artifacts?.png ?? "—"}</div>
          <div>SVG: {payload?.artifacts?.svg ?? "—"}</div>
        </div>
      </details>
      )}
    </section>
  );
}

export default function KgPreviewPanel({ state, dispatch, pdfFile, addToast }) {
  const variants = state.kgVariants ?? [];
  const selectedVariantIds = state.kgSelectedVariantIds ?? [];
  const selectedResultIds = state.kgSelectedResultIds ?? [];
  const comparisonResults = state.kgComparisonResults ?? [];
  const catalog = state.kgCatalog ?? [];
  const busy = state.kgBusy;
  const error = state.kgError;
  const defaultModel = state.kgDefaultModel ?? "gpt-5";
  const visibleSections = Array.isArray(state.kgVisibleSections) && state.kgVisibleSections.length
    ? state.kgVisibleSections
    : DEFAULT_VISIBLE_SECTIONS;
  const graphViewMode = state.kgGraphViewMode ?? "organized";
  const scoreMode = state.kgScoreMode ?? "audio";
  const scoreDetailIdx = Number.isInteger(state.kgScoreDetail) ? state.kgScoreDetail : 1;
  const scoreDifficultyIdx = Number.isInteger(state.kgScoreDifficulty) ? state.kgScoreDifficulty : 1;
  const scoreProfile = {
    mode: scoreMode,
    detail: DETAIL_VALS[scoreDetailIdx] ?? "standard",
    difficulty: DIFF_VALS[scoreDifficultyIdx] ?? "basic",
  };
  const catalogOpen = Boolean(state.kgCatalogOpen);
  const catalogBusy = Boolean(state.kgCatalogBusy);
  const catalogSelection = state.kgCatalogSelection ?? [];
  const currentProjectId = state.projectMeta?.id ?? null;
  const previousProjectIdRef = useRef(currentProjectId);

  useEffect(() => {
    if (previousProjectIdRef.current === currentProjectId) return;
    previousProjectIdRef.current = currentProjectId;
    dispatch({ type: "SET", k: "kgComparisonResults", v: [] });
    dispatch({ type: "SET", k: "kgSelectedResultIds", v: [] });
    dispatch({ type: "SET", k: "kgCatalog", v: [] });
    dispatch({ type: "SET", k: "kgCatalogOpen", v: false });
    dispatch({ type: "SET", k: "kgCatalogSelection", v: [] });
    dispatch({ type: "SET", k: "kgCatalogBusy", v: false });
    dispatch({ type: "SET", k: "kgError", v: null });
  }, [currentProjectId, dispatch]);

  useEffect(() => {
    const availableIds = comparisonResults.map((row) => row?.result_id).filter(Boolean);
    const kept = selectedResultIds.filter((id) => availableIds.includes(id));
    const nextIds = kept.length ? kept : availableIds;
    const changed = nextIds.length !== selectedResultIds.length || nextIds.some((id, index) => id !== selectedResultIds[index]);
    if (changed) {
      dispatch({ type: "SET", k: "kgSelectedResultIds", v: nextIds });
    }
  }, [comparisonResults, dispatch, selectedResultIds]);

  useEffect(() => {
    let active = true;
    if (variants.length > 0) return undefined;
    dispatch({ type: "SET", k: "kgBusy", v: true });
    dispatch({ type: "SET", k: "kgError", v: null });
    authFetch("/api/kg-preview/variants", { method: "GET" })
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((payload) => {
        if (!active) return;
        const nextVariants = payload?.variants ?? [];
        dispatch({ type: "SET", k: "kgVariants", v: nextVariants });
        dispatch({ type: "SET", k: "kgDefaultModel", v: payload?.default_model ?? "gpt-5" });
        if (!selectedVariantIds.length) {
          const defaults = nextVariants.filter((row) => row?.enabled).slice(0, 2).map((row) => row.id);
          dispatch({ type: "SET", k: "kgSelectedVariantIds", v: defaults });
        }
        dispatch({ type: "SET", k: "kgBusy", v: false });
      })
      .catch((err) => {
        if (!active) return;
        dispatch({ type: "SET", k: "kgBusy", v: false });
        dispatch({ type: "SET", k: "kgError", v: formatKgError(err) });
      });
    return () => {
      active = false;
    };
  }, [dispatch, selectedVariantIds.length, variants.length]);

  const enabledVariants = useMemo(
    () => variants.filter((row) => row?.enabled),
    [variants],
  );

  const focusedResults = useMemo(() => {
    const ids = selectedResultIds.length ? selectedResultIds : comparisonResults.map((row) => row?.result_id).filter(Boolean);
    const byId = new Map(comparisonResults.map((row) => [row.result_id, row]));
    return ids.map((id) => byId.get(id)).filter(Boolean);
  }, [comparisonResults, selectedResultIds]);

  const comparisonColumns = focusedResults.length >= 3 ? "repeat(3, minmax(0, 1fr))" : focusedResults.length === 2 ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)";

  const toggleVariant = (variantId) => {
    const current = selectedVariantIds;
    if (current.includes(variantId)) {
      dispatch({ type: "SET", k: "kgSelectedVariantIds", v: current.filter((id) => id !== variantId) });
      return;
    }
    if (current.length >= 3) {
      addToast?.("in", "variant は最大3件まで選択できます");
      return;
    }
    dispatch({ type: "SET", k: "kgSelectedVariantIds", v: [...current, variantId] });
  };

  const removeResult = (resultId) => {
    const next = comparisonResults.filter((row) => row?.result_id !== resultId);
    dispatch({ type: "SET", k: "kgComparisonResults", v: next });
    dispatch({ type: "SET", k: "kgSelectedResultIds", v: next.map((row) => row.result_id) });
  };

  const toggleFocusedResult = (resultId) => {
    const nextIds = selectedResultIds.includes(resultId)
      ? selectedResultIds.filter((id) => id !== resultId)
      : [...selectedResultIds, resultId];
    dispatch({ type: "SET", k: "kgSelectedResultIds", v: nextIds });
  };

  const toggleSection = (sectionId) => {
    const current = visibleSections;
    if (current.includes(sectionId)) {
      if (current.length === 1) return;
      dispatch({ type: "SET", k: "kgVisibleSections", v: current.filter((id) => id !== sectionId) });
      return;
    }
    dispatch({ type: "SET", k: "kgVisibleSections", v: [...current, sectionId] });
  };

  const applySectionPreset = (preset) => {
    if (preset === "graph_only") {
      dispatch({ type: "SET", k: "kgVisibleSections", v: ["graph"] });
      return;
    }
    if (preset === "standard") {
      dispatch({ type: "SET", k: "kgVisibleSections", v: DEFAULT_VISIBLE_SECTIONS });
      return;
    }
    if (preset === "all") {
      dispatch({ type: "SET", k: "kgVisibleSections", v: DISPLAY_SECTIONS.map((row) => row.id) });
    }
  };

  const isGraphOnlyPreset = visibleSections.length === 1 && visibleSections[0] === "graph";
  const isStandardPreset = visibleSections.length === DEFAULT_VISIBLE_SECTIONS.length
    && DEFAULT_VISIBLE_SECTIONS.every((sectionId, index) => visibleSections[index] === sectionId);
  const isAllPreset = visibleSections.length === DISPLAY_SECTIONS.length
    && DISPLAY_SECTIONS.every((row) => visibleSections.includes(row.id));
  const isDagExplanation = "DAG は循環のないグラフ、cycleあり は関係がループしているグラフです。";

  const runCompare = async () => {
    if (!pdfFile) {
      addToast?.("er", "PDFをアップロードしてください");
      return;
    }
    if (!selectedVariantIds.length) {
      addToast?.("er", "比較する variant を選んでください");
      return;
    }
    dispatch({ type: "SET", k: "kgBusy", v: true });
    dispatch({ type: "SET", k: "kgError", v: null });
    dispatch({
      type: "APP_LOG",
      message: `KG比較を開始しました（file=${pdfFile.name}, variants=${selectedVariantIds.join(",")})`,
      meta: { type: "kg_compare_start", filename: pdfFile.name, variants: selectedVariantIds, project_id: currentProjectId },
    });
    try {
      const b64 = await toB64(pdfFile);
      const res = await authFetch("/api/kg-preview/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pdf_base64: b64,
          filename: pdfFile.name,
          variant_ids: selectedVariantIds,
          project_id: currentProjectId,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `HTTP ${res.status}`);
      }
      const payload = await res.json();
      const nextResults = mergeComparisonResults(comparisonResults, payload?.results ?? []);
      dispatch({ type: "SET", k: "kgComparisonResults", v: nextResults });
      dispatch({ type: "SET", k: "kgSelectedResultIds", v: nextResults.map((row) => row.result_id) });
      dispatch({ type: "SET", k: "kgBusy", v: false });
      dispatch({
        type: "APP_LOG",
        message: `KG比較が完了しました（results=${(payload?.results ?? []).length}）`,
        meta: { type: "kg_compare_success", result_count: (payload?.results ?? []).length, variants: selectedVariantIds, project_id: currentProjectId },
      });
      addToast?.("ok", "KG比較結果を更新しました");
    } catch (err) {
      const message = formatKgError(err);
      dispatch({ type: "SET", k: "kgBusy", v: false });
      dispatch({ type: "SET", k: "kgError", v: message });
      dispatch({
        type: "APP_LOG",
        message: `KG比較に失敗しました（reason=${message}）`,
        meta: { type: "kg_compare_error", reason: message, variants: selectedVariantIds, project_id: currentProjectId },
      });
      addToast?.("er", message);
    }
  };

  const loadCatalog = async () => {
    if (!currentProjectId) {
      dispatch({ type: "SET", k: "kgCatalog", v: [] });
      dispatch({ type: "SET", k: "kgSelectedResultIds", v: [] });
      dispatch({ type: "SET", k: "kgCatalogSelection", v: [] });
      dispatch({ type: "SET", k: "kgCatalogOpen", v: false });
      addToast?.("in", "保存済みKGは保存済みプロジェクトごとに管理されます。先にプロジェクトを保存してください");
      return;
    }
    dispatch({ type: "SET", k: "kgCatalogBusy", v: true });
    dispatch({ type: "SET", k: "kgError", v: null });
    try {
      const activeFingerprint = pdfFile
        ? await hashPdfFile(pdfFile)
        : comparisonResults[0]?.material_fingerprint ?? null;
      let path = `/api/kg-preview/results?limit=24`;
      if (currentProjectId) {
        path += `&project_id=${encodeURIComponent(currentProjectId)}`;
      }
      if (activeFingerprint) {
        path += `&material_fingerprint=${encodeURIComponent(activeFingerprint)}`;
      } else if (pdfFile?.name) {
        path += `&filename=${encodeURIComponent(pdfFile.name)}`;
      }
      let res = await authFetch(path, { method: "GET" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      let payload = await res.json();
      if ((payload?.results?.length ?? 0) === 0 && activeFingerprint && pdfFile?.name) {
        const projectQuery = currentProjectId ? `&project_id=${encodeURIComponent(currentProjectId)}` : "";
        res = await authFetch(`/api/kg-preview/results?limit=24${projectQuery}&filename=${encodeURIComponent(pdfFile.name)}`, { method: "GET" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        payload = await res.json();
      }
      dispatch({ type: "SET", k: "kgCatalog", v: payload?.results ?? [] });
      dispatch({ type: "SET", k: "kgCatalogSelection", v: selectedResultIds });
    } catch (err) {
      dispatch({ type: "SET", k: "kgError", v: formatKgError(err) });
      addToast?.("er", "保存済み結果の取得に失敗しました");
    } finally {
      dispatch({ type: "SET", k: "kgCatalogBusy", v: false });
    }
  };

  const toggleCatalog = async () => {
    if (!currentProjectId) {
      dispatch({ type: "SET", k: "kgCatalog", v: [] });
      dispatch({ type: "SET", k: "kgSelectedResultIds", v: [] });
      dispatch({ type: "SET", k: "kgCatalogSelection", v: [] });
      dispatch({ type: "SET", k: "kgCatalogOpen", v: false });
      addToast?.("in", "保存済みKGは保存済みプロジェクトごとに管理されます。先にプロジェクトを保存してください");
      return;
    }
    const nextOpen = !catalogOpen;
    dispatch({ type: "SET", k: "kgCatalogOpen", v: nextOpen });
    if (nextOpen) {
      await loadCatalog();
    }
  };

  const toggleCatalogSelection = (resultId) => {
    if (catalogSelection.includes(resultId)) {
      dispatch({ type: "SET", k: "kgCatalogSelection", v: catalogSelection.filter((id) => id !== resultId) });
      return;
    }
    if (catalogSelection.length >= 3) {
      addToast?.("in", "保存済み結果も最大3件まで選択できます");
      return;
    }
    dispatch({ type: "SET", k: "kgCatalogSelection", v: [...catalogSelection, resultId] });
  };

  const applyCatalogSelection = async () => {
    if (!catalogSelection.length) {
      addToast?.("in", "比較に載せる保存済み結果を選んでください");
      return;
    }
    dispatch({ type: "SET", k: "kgCatalogBusy", v: true });
    try {
      const detailRows = [];
      for (const resultId of catalogSelection) {
        const projectQuery = currentProjectId ? `?project_id=${encodeURIComponent(currentProjectId)}` : "";
        const res = await authFetch(`/api/kg-preview/results/${encodeURIComponent(resultId)}${projectQuery}`, { method: "GET" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        detailRows.push(await res.json());
      }
      const nextResults = mergeComparisonResults(comparisonResults, detailRows);
      dispatch({ type: "SET", k: "kgComparisonResults", v: nextResults });
      dispatch({ type: "SET", k: "kgSelectedResultIds", v: nextResults.map((row) => row.result_id) });
      dispatch({ type: "SET", k: "kgCatalogOpen", v: false });
      addToast?.("ok", "保存済み結果を比較面に追加しました");
    } catch (err) {
      const message = formatKgError(err);
      dispatch({ type: "SET", k: "kgError", v: message });
      addToast?.("er", message);
    } finally {
      dispatch({ type: "SET", k: "kgCatalogBusy", v: false });
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, height: "100%" }}>
      <div style={{ padding: "12px 14px 10px", borderBottom: "1px solid rgba(255,255,255,.05)", flexShrink: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, marginBottom: 8 }}>
          <div>
            <div style={{ fontFamily: "var(--ff)", fontSize: 12, fontWeight: 700, marginBottom: 4 }}>
              KG 比較
            </div>
            <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.6 }}>
              同じ PDF に対して複数 variant を並べて比較します。保存済み結果の参照は現在の保存済み project に限定され、ここでは最大3件を表示します。
            </div>
          </div>
          <SummaryBadge>{defaultModel}</SummaryBadge>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
          {enabledVariants.length === 0 ? (
            <div style={{ fontSize: 10, color: "var(--tm)" }}>variant 読み込み中...</div>
          ) : (
            enabledVariants.map((variant) => {
              const checked = selectedVariantIds.includes(variant.id);
              const disabled = !checked && selectedVariantIds.length >= 3;
              return (
                <button key={variant.id} onClick={() => toggleVariant(variant.id)} style={pillStyle(checked, disabled)} disabled={disabled}>
                  <span style={{ width: 14, textAlign: "center", color: checked ? "var(--ac)" : "var(--tm)" }}>{checked ? "✓" : "○"}</span>
                  <span style={{ fontSize: 10 }}>{variant.label}</span>
                </button>
              );
            })
          )}
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          <button
            onClick={runCompare}
            disabled={busy || !pdfFile || selectedVariantIds.length === 0}
            style={{
              padding: "7px 12px",
              borderRadius: 9,
              border: "1px solid rgba(130,178,255,.38)",
              background: busy ? "rgba(122,165,242,.28)" : "rgba(122,165,242,.18)",
              color: busy ? "#dfe8ff" : "var(--ac)",
              fontSize: 11,
              fontWeight: 700,
              cursor: busy ? "progress" : (!pdfFile ? "not-allowed" : "pointer"),
            }}
          >
            {busy ? "比較実行中..." : "比較実行"}
          </button>
          <button
            onClick={toggleCatalog}
            disabled={!currentProjectId}
            style={{
              padding: "7px 12px",
              borderRadius: 9,
              border: "1px solid rgba(255,255,255,.12)",
              background: "rgba(255,255,255,.03)",
              color: !currentProjectId ? "var(--tm)" : "var(--tp)",
              fontSize: 11,
              fontWeight: 700,
              cursor: !currentProjectId ? "not-allowed" : "pointer",
              opacity: !currentProjectId ? 0.5 : 1,
            }}
          >
            {catalogOpen ? "保存済み結果を閉じる" : "保存済み結果"}
          </button>
        </div>

        {!!error && (
          <div style={{ marginTop: 10, fontSize: 10, lineHeight: 1.6, color: "var(--rd)" }}>
            {error}
          </div>
        )}
      </div>

      {catalogOpen && (
        <div style={{ padding: 12, borderBottom: "1px solid rgba(255,255,255,.05)", background: "rgba(255,255,255,.015)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700 }}>保存済み結果</div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={loadCatalog}
                disabled={catalogBusy}
                style={{ padding: "5px 9px", borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--ts)", fontSize: 10 }}
              >
                再読込
              </button>
              <button
                onClick={applyCatalogSelection}
                disabled={catalogBusy || catalogSelection.length === 0}
                style={{ padding: "5px 9px", borderRadius: 8, border: "1px solid rgba(130,178,255,.38)", background: "rgba(122,165,242,.18)", color: "var(--ac)", fontSize: 10, fontWeight: 700 }}
              >
                比較面に反映
              </button>
            </div>
          </div>

          {catalogBusy ? (
            <div style={{ fontSize: 10, color: "var(--tm)" }}>保存済み結果を読み込み中...</div>
          ) : catalog.length === 0 ? (
            <div style={{ fontSize: 10, color: "var(--tm)" }}>この PDF に近い保存済み結果はまだありません。</div>
          ) : (
            <div style={{ display: "grid", gap: 8, maxHeight: 220, overflowY: "auto" }}>
              {catalog.map((row) => {
                const selected = catalogSelection.includes(row.result_id);
                const disabled = !selected && catalogSelection.length >= 3;
                return (
                  <button
                    key={row.result_id}
                    onClick={() => toggleCatalogSelection(row.result_id)}
                    disabled={disabled}
                    style={{
                      textAlign: "left",
                      padding: 10,
                      borderRadius: 10,
                      border: `1px solid ${selected ? "rgba(130,178,255,.34)" : "rgba(255,255,255,.06)"}`,
                      background: selected ? "rgba(91,141,239,.12)" : "rgba(255,255,255,.02)",
                      color: disabled ? "var(--tm)" : "var(--ts)",
                      opacity: disabled ? 0.45 : 1,
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 10, marginBottom: 4 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>
                        {selected ? "✓ " : ""}{row?.variant?.label ?? row?.variant?.id ?? "variant"}
                      </div>
                      <div style={{ fontSize: 9, color: "var(--tm)" }}>{timeText(row?.created_at)}</div>
                    </div>
                    <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55, marginBottom: 6 }}>
                      {row?.variant?.description ?? "—"}
                    </div>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                      <SummaryBadge>triplet {row?.summary?.triplet_count ?? 0}</SummaryBadge>
                      <SummaryBadge>node {row?.summary?.node_count ?? 0}</SummaryBadge>
                      <SummaryBadge tone={row?.summary?.is_dag ? "good" : "warn"}>
                        {row?.summary?.is_dag ? "循環なし (DAG)" : "循環あり"}
                      </SummaryBadge>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 12 }}>
        {comparisonResults.length === 0 ? (
          <div style={{ padding: 16, color: "var(--tm)", fontSize: 11, lineHeight: 1.7 }}>
            まだ比較結果はありません。PDF を選んだ上で variant を選択し、「比較実行」を押すとここに並びます。過去の保存済み結果だけ見たい場合は「保存済み結果」から選べます。
          </div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            <section style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 12, background: "rgba(255,255,255,.015)", padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>結果一覧</div>
                  <div style={{ fontSize: 10, color: "var(--tm)" }}>見たい結果だけ選んで下の比較に残せます。</div>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button onClick={() => dispatch({ type: "SET", k: "kgSelectedResultIds", v: comparisonResults.map((row) => row.result_id).filter(Boolean) })} style={{ padding: "5px 9px", borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--ts)", fontSize: 10 }}>全表示</button>
                  <button onClick={() => dispatch({ type: "SET", k: "kgSelectedResultIds", v: [] })} style={{ padding: "5px 9px", borderRadius: 8, border: "1px solid rgba(255,255,255,.1)", background: "rgba(255,255,255,.03)", color: "var(--ts)", fontSize: 10 }}>選択解除</button>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 }}>
                {comparisonResults.map((payload) => (
                  <ResultOverviewCard
                    key={`${payload.result_id}_overview`}
                    payload={payload}
                    selected={focusedResults.some((row) => row.result_id === payload.result_id)}
                    onToggle={() => toggleFocusedResult(payload.result_id)}
                  />
                ))}
              </div>
            </section>

            <section style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 12, background: "rgba(255,255,255,.015)", padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>表示項目</div>
                  <div style={{ fontSize: 10, color: "var(--tm)" }}>上は選択専用、下の比較カードだけに詳細を出します。必要な項目だけ表示してください。</div>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button onClick={() => applySectionPreset("graph_only")} style={{ padding: "5px 9px", borderRadius: 8, border: isGraphOnlyPreset ? "1px solid rgba(130,178,255,.32)" : "1px solid rgba(255,255,255,.1)", background: isGraphOnlyPreset ? "rgba(122,165,242,.14)" : "rgba(255,255,255,.03)", color: isGraphOnlyPreset ? "var(--ac)" : "var(--ts)", fontSize: 10 }}>図だけ</button>
                  <button onClick={() => applySectionPreset("standard")} style={{ padding: "5px 9px", borderRadius: 8, border: isStandardPreset ? "1px solid rgba(130,178,255,.32)" : "1px solid rgba(255,255,255,.1)", background: isStandardPreset ? "rgba(122,165,242,.14)" : "rgba(255,255,255,.03)", color: isStandardPreset ? "var(--ac)" : "var(--ts)", fontSize: 10 }}>標準</button>
                  <button onClick={() => applySectionPreset("all")} style={{ padding: "5px 9px", borderRadius: 8, border: isAllPreset ? "1px solid rgba(130,178,255,.32)" : "1px solid rgba(255,255,255,.1)", background: isAllPreset ? "rgba(122,165,242,.14)" : "rgba(255,255,255,.03)", color: isAllPreset ? "var(--ac)" : "var(--ts)", fontSize: 10 }}>全部</button>
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
                <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.7 }}>
                  {isDagExplanation}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <button
                    onClick={() => dispatch({ type: "SET", k: "kgGraphViewMode", v: "organized" })}
                    style={{
                      padding: "5px 9px",
                      borderRadius: 8,
                      border: graphViewMode === "organized" ? "1px solid rgba(130,178,255,.32)" : "1px solid rgba(255,255,255,.1)",
                      background: graphViewMode === "organized" ? "rgba(122,165,242,.14)" : "rgba(255,255,255,.03)",
                      color: graphViewMode === "organized" ? "var(--ac)" : "var(--ts)",
                      fontSize: 10,
                    }}
                  >
                    整理表示
                  </button>
                  <button
                    onClick={() => dispatch({ type: "SET", k: "kgGraphViewMode", v: "full" })}
                    style={{
                      padding: "5px 9px",
                      borderRadius: 8,
                      border: graphViewMode === "full" ? "1px solid rgba(130,178,255,.32)" : "1px solid rgba(255,255,255,.1)",
                      background: graphViewMode === "full" ? "rgba(122,165,242,.14)" : "rgba(255,255,255,.03)",
                      color: graphViewMode === "full" ? "var(--ac)" : "var(--ts)",
                      fontSize: 10,
                    }}
                  >
                    全エッジ表示
                  </button>
                </div>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {DISPLAY_SECTIONS.map((section) => {
                  const active = visibleSections.includes(section.id);
                  return (
                    <button
                      key={section.id}
                      onClick={() => toggleSection(section.id)}
                      style={pillStyle(active, !active && visibleSections.length >= DISPLAY_SECTIONS.length)}
                    >
                      <span style={{ width: 14, textAlign: "center", color: active ? "var(--ac)" : "var(--tm)" }}>{active ? "✓" : "○"}</span>
                      <span style={{ fontSize: 10 }}>{section.label}</span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section style={{ border: "1px solid rgba(255,255,255,.05)", borderRadius: 12, background: "rgba(255,255,255,.015)", padding: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "var(--tp)" }}>スコア確認条件</div>
                  <div style={{ fontSize: 10, color: "var(--tm)" }}>同一 KG に対して、学習者要求ごとの重点語句ランキングを切り替えます。</div>
                </div>
                <SummaryBadge>{profileKeyFor(scoreProfile)}</SummaryBadge>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
                <div>
                  <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>提示形態</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {MODE_LABELS.map((label, idx) => (
                      <button key={label} onClick={() => dispatch({ type: "SET", k: "kgScoreMode", v: MODE_VALS[idx] ?? "audio" })} style={pillStyle(scoreMode === (MODE_VALS[idx] ?? "audio"))}>
                        <span style={{ fontSize: 10 }}>{label}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>詳細度</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {DETAIL_LABELS.map((label, idx) => (
                      <button key={label} onClick={() => dispatch({ type: "SET", k: "kgScoreDetail", v: idx })} style={pillStyle(scoreDetailIdx === idx)}>
                        <span style={{ fontSize: 10 }}>{label}</span>
                      </button>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>難易度</div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {DIFF_LABELS.map((label, idx) => (
                      <button key={label} onClick={() => dispatch({ type: "SET", k: "kgScoreDifficulty", v: idx })} style={pillStyle(scoreDifficultyIdx === idx)}>
                        <span style={{ fontSize: 10 }}>{label}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            {focusedResults.length === 0 ? (
              <div style={{ padding: 16, color: "var(--tm)", fontSize: 11, lineHeight: 1.7, border: "1px dashed rgba(255,255,255,.08)", borderRadius: 12 }}>
                上の結果一覧から、比較したい結果を選んでください。
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: comparisonColumns, gap: 12, alignItems: "start" }}>
                {focusedResults.map((payload) => (
                  <KgResultCard
                    key={payload.result_id}
                    payload={payload}
                    onRemove={() => removeResult(payload.result_id)}
                    visibleSections={visibleSections}
                    graphMode={graphViewMode}
                    scoreProfile={scoreProfile}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
