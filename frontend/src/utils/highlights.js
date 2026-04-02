function toNum(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function normalizeSentenceIds(ids, legacySid = null) {
  const source = Array.isArray(ids) ? ids : (legacySid ? [legacySid] : []);
  return [...new Set(source.map((id) => String(id)).filter(Boolean))];
}

export function normalizeHighlight(raw, index = 0) {
  return {
    id: raw?.id ?? `h_${index + 1}`,
    slide_idx: toNum(raw?.slide_idx, 0),
    sentence_ids: normalizeSentenceIds(raw?.sentence_ids, raw?.sid),
    kind: raw?.kind ?? "marker",
    x: toNum(raw?.x, 0),
    y: toNum(raw?.y, 0),
    w: toNum(raw?.w, 1),
    h: toNum(raw?.h, 1),
  };
}

function regionIoU(a, b) {
  const ax2 = a.x + a.w;
  const ay2 = a.y + a.h;
  const bx2 = b.x + b.w;
  const by2 = b.y + b.h;
  const ix1 = Math.max(a.x, b.x);
  const iy1 = Math.max(a.y, b.y);
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  const iw = Math.max(0, ix2 - ix1);
  const ih = Math.max(0, iy2 - iy1);
  const inter = iw * ih;
  const union = a.w * a.h + b.w * b.h - inter;
  return union > 0 ? inter / union : 0;
}

function centerDistance(a, b) {
  const acx = a.x + a.w / 2;
  const acy = a.y + a.h / 2;
  const bcx = b.x + b.w / 2;
  const bcy = b.y + b.h / 2;
  return Math.hypot(acx - bcx, acy - bcy);
}

export function areHighlightsEquivalent(a, b) {
  if (!a || !b) return false;
  if (a.slide_idx !== b.slide_idx) return false;
  const iou = regionIoU(a, b);
  if (iou >= 0.82) return true;
  const sizeClose = Math.abs(a.w - b.w) <= 4 && Math.abs(a.h - b.h) <= 4;
  return sizeClose && centerDistance(a, b) <= 3.5;
}

export function mergeGeneratedHighlights(highlights) {
  const merged = [];
  for (const raw of highlights ?? []) {
    const next = normalizeHighlight(raw, merged.length);
    const existing = merged.find((item) => areHighlightsEquivalent(item, next));
    if (!existing) {
      merged.push(next);
      continue;
    }
    existing.sentence_ids = [...new Set([...existing.sentence_ids, ...next.sentence_ids])];
  }
  return merged.map((item, index) => ({ ...item, id: item.id ?? `h_${index + 1}` }));
}

export function findHighlightForSentence(highlights, sentenceId) {
  return (highlights ?? []).find((hl) => (hl.sentence_ids ?? []).includes(String(sentenceId))) ?? null;
}

export function getSlideHighlights(highlights, slideIdx) {
  return (highlights ?? []).filter((hl) => hl.slide_idx === slideIdx);
}

export function buildSentenceHighlightsForExport(highlights, sentences) {
  const rows = [];
  for (const sentence of sentences ?? []) {
    const hl = findHighlightForSentence(highlights, sentence.id);
    if (!hl) continue;
    rows.push({
      id: hl.id,
      sid: sentence.id,
      slide_idx: hl.slide_idx,
      kind: hl.kind,
      x: hl.x,
      y: hl.y,
      w: hl.w,
      h: hl.h,
    });
  }
  return rows;
}
