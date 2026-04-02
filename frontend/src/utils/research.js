function sanitizeSlideMeta(slide) {
  return {
    id: slide?.id ?? null,
    title: slide?.title ?? "",
    width: slide?.width ?? null,
    height: slide?.height ?? null,
    aspect_ratio: slide?.aspect_ratio ?? null,
  };
}

function sanitizeSentence(sentence) {
  return {
    id: sentence?.id ?? null,
    slide_idx: sentence?.slide_idx ?? 0,
    text: sentence?.text ?? "",
    start_sec: sentence?.start_sec ?? 0,
    end_sec: sentence?.end_sec ?? 0,
  };
}

function sanitizeHighlight(highlight) {
  return {
    id: highlight?.id ?? null,
    sid: highlight?.sid ?? null,
    slide_idx: highlight?.slide_idx ?? 0,
    kind: highlight?.kind ?? "marker",
    x: highlight?.x ?? 0,
    y: highlight?.y ?? 0,
    w: highlight?.w ?? 0,
    h: highlight?.h ?? 0,
  };
}

function indexById(rows) {
  const map = new Map();
  for (const row of rows ?? []) {
    if (row?.id) map.set(row.id, row);
  }
  return map;
}

function sameSentence(a, b) {
  return (
    a?.slide_idx === b?.slide_idx
    && a?.text === b?.text
    && Number(a?.start_sec ?? 0) === Number(b?.start_sec ?? 0)
    && Number(a?.end_sec ?? 0) === Number(b?.end_sec ?? 0)
  );
}

function sameHighlight(a, b) {
  return (
    a?.sid === b?.sid
    && a?.slide_idx === b?.slide_idx
    && a?.kind === b?.kind
    && Number(a?.x ?? 0) === Number(b?.x ?? 0)
    && Number(a?.y ?? 0) === Number(b?.y ?? 0)
    && Number(a?.w ?? 0) === Number(b?.w ?? 0)
    && Number(a?.h ?? 0) === Number(b?.h ?? 0)
  );
}

function changedSentenceFields(before, after) {
  const fields = [];
  if (before.slide_idx !== after.slide_idx) fields.push("slide_idx");
  if (before.text !== after.text) fields.push("text");
  if (Number(before.start_sec ?? 0) !== Number(after.start_sec ?? 0)) fields.push("start_sec");
  if (Number(before.end_sec ?? 0) !== Number(after.end_sec ?? 0)) fields.push("end_sec");
  return fields;
}

function changedHighlightFields(before, after) {
  const fields = [];
  if (before.sid !== after.sid) fields.push("sid");
  if (before.slide_idx !== after.slide_idx) fields.push("slide_idx");
  if (before.kind !== after.kind) fields.push("kind");
  if (Number(before.x ?? 0) !== Number(after.x ?? 0)) fields.push("x");
  if (Number(before.y ?? 0) !== Number(after.y ?? 0)) fields.push("y");
  if (Number(before.w ?? 0) !== Number(after.w ?? 0)) fields.push("w");
  if (Number(before.h ?? 0) !== Number(after.h ?? 0)) fields.push("h");
  return fields;
}

function diffEntities(baselineRows, currentRows, sameFn, changedFieldsFn) {
  const beforeMap = indexById(baselineRows);
  const afterMap = indexById(currentRows);
  const accepted = [];
  const modified = [];
  const removed = [];
  const added = [];

  for (const [id, before] of beforeMap.entries()) {
    const after = afterMap.get(id);
    if (!after) {
      removed.push({ id, before });
      continue;
    }
    if (sameFn(before, after)) {
      accepted.push({ id, value: after });
      continue;
    }
    modified.push({
      id,
      before,
      after,
      changed_fields: changedFieldsFn(before, after),
    });
  }

  for (const [id, after] of afterMap.entries()) {
    if (!beforeMap.has(id)) {
      added.push({ id, after });
    }
  }

  return { accepted, modified, removed, added };
}

export function buildResearchSnapshot(state, trigger, extra = {}) {
  const baseline = state.baseline ?? {
    slide_meta: [],
    sentences: [],
    highlights: [],
    generation_ref: state.genRef ?? null,
  };

  const currentSlideMeta = (state.slides ?? []).map(sanitizeSlideMeta);
  const currentSentences = (state.sents ?? []).map(sanitizeSentence);
  const currentHighlights = (state.hls ?? []).map(sanitizeHighlight);

  const sentenceDiff = diffEntities(
    baseline.sentences ?? [],
    currentSentences,
    sameSentence,
    changedSentenceFields,
  );
  const highlightDiff = diffEntities(
    baseline.highlights ?? [],
    currentHighlights,
    sameHighlight,
    changedHighlightFields,
  );

  const sentenceTextModified = sentenceDiff.modified.filter((row) => row.changed_fields.includes("text")).length;
  const sentenceTimingModified = sentenceDiff.modified.filter(
    (row) => row.changed_fields.includes("start_sec") || row.changed_fields.includes("end_sec"),
  ).length;

  return {
    version: "2026-04-02_research_v1",
    created_at: new Date().toISOString(),
    trigger,
    session_id: state.sessionId ?? null,
    mode: state.appMode,
    generation_ref: state.genRef ?? baseline.generation_ref ?? null,
    settings: {
      app_mode: state.appMode,
      detail_index: state.detail,
      level_index: state.level,
      preview_mode: state.prevMode,
      play_speed: state.playSpeed,
      ...extra.settings,
    },
    baseline: {
      mode: baseline.mode ?? state.appMode,
      created_at: baseline.created_at ?? null,
      slide_meta: baseline.slide_meta ?? [],
      sentence_count: (baseline.sentences ?? []).length,
      highlight_count: (baseline.highlights ?? []).length,
    },
    current: {
      slide_meta: currentSlideMeta,
      sentence_count: currentSentences.length,
      highlight_count: currentHighlights.length,
    },
    summary: {
      highlights_accepted: highlightDiff.accepted.length,
      highlights_modified: highlightDiff.modified.length,
      highlights_removed: highlightDiff.removed.length,
      highlights_added: highlightDiff.added.length,
      sentences_accepted: sentenceDiff.accepted.length,
      sentences_modified: sentenceDiff.modified.length,
      sentences_text_modified: sentenceTextModified,
      sentences_timing_modified: sentenceTimingModified,
      sentences_removed: sentenceDiff.removed.length,
      sentences_added: sentenceDiff.added.length,
      study_event_count: (state.studyEvents ?? []).length,
      operation_log_count: (state.opLogs ?? []).length,
    },
    feedback: {
      highlights: highlightDiff,
      sentences: sentenceDiff,
    },
    events: state.studyEvents ?? [],
    operation_logs: state.opLogs ?? [],
    extensions: extra.extensions ?? {},
  };
}
