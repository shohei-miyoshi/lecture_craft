/**
 * LectureCraft — アプリ全状態 Reducer
 *
 * appMode（提示形態）は生成後にロックされる。
 * 別のモードで再生成する場合はリセットが必要。
 */

import { findHighlightForSentence, mergeGeneratedHighlights, normalizeHighlight } from "../utils/highlights.js";
import { fingerprintProjectData } from "../utils/projectStore.js";

export const INITIAL_STATE = {
  // データ
  slides:    [],
  sents:     [],
  hls:       [],
  totDur:    0,
  generated: false,
  genRef:    null,
  sessionId: null,
  baseline:  null,
  projectMeta: null,
  inputPdf: null,
  syncStatus: "idle",
  previewFrame: { width: 1600, height: 900, aspect_ratio: 16 / 9 },
  savedFingerprint: null,

  // ナビゲーション
  curSl:    0,
  selSent:  null,
  selHl:    null,

  // 設定軸
  appMode:  "hl",   // "audio" | "video" | "hl"  ← 生成後ロック
  detail:   1,      // 0=要約 1=標準 2=精緻
  level:    1,      // 0=入門 1=基礎 2=発展
  prevMode: "hl",   // プレビュー表示モード

  // 生成ステータス
  status:    "idle",
  statusMsg: "待機中",
  progress:  0,
  showProg:  false,

  // 描画モード
  drawMode:    false,
  drawSentId:  null,
  drawKind:    "marker",

  // 再生
  curT:      0,
  playing:   false,
  playSpeed: 1.0,
  seekSignal: 0,   // シーク操作ごとにインクリメント（usePlaybackの再起動トリガー）
  previewActiveSentenceId: null,
  previewAudioStale: true,

  // 操作ログ
  opLogs:    [],
  studyEvents: [],
  historyPast: [],
  historyFuture: [],
};

const MAX_OP_LOGS = 300;
const MAX_STUDY_EVENTS = 2000;
const MAX_HISTORY = 80;
const INTERNAL_SCRIPT_LINE_RE = /^(?:#\s*(?:slide\b|image\s*:)|image\s*:|created at\b)/i;

function makeLog(message, meta = {}) {
  return {
    id: `log_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    at: new Date().toISOString(),
    message,
    meta,
  };
}

function appendLog(logs, message, meta = {}) {
  const next = [...(logs ?? []), makeLog(message, meta)];
  return next.slice(-MAX_OP_LOGS);
}

function shortText(text, n = 36) {
  const s = String(text ?? "").replace(/\s+/g, " ").trim();
  return s.length <= n ? s : `${s.slice(0, n).trimEnd()}…`;
}

function makeSessionId() {
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function clonePlain(value) {
  return JSON.parse(JSON.stringify(value));
}

function sanitizeSlideMeta(slide) {
  return {
    id: slide?.id ?? null,
    title: slide?.title ?? "",
    width: slide?.width ?? null,
    height: slide?.height ?? null,
    aspect_ratio: slide?.aspect_ratio ?? null,
    backend_mode: slide?.backend_mode ?? null,
    backend_detail: slide?.backend_detail ?? null,
    backend_difficulty: slide?.backend_difficulty ?? null,
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

function isInternalScriptSentence(sentence) {
  const text = String(sentence?.text ?? "").replace(/^\ufeff/, "").trim();
  return !text || INTERNAL_SCRIPT_LINE_RE.test(text);
}

function normalizeSentencesForUi(sentences = []) {
  return (sentences ?? []).filter((sentence) => !isInternalScriptSentence(sentence));
}

function sanitizeHighlight(highlight) {
  const normalized = normalizeHighlight(highlight ?? {});
  return {
    id: normalized.id,
    sentence_ids: normalized.sentence_ids,
    slide_idx: normalized.slide_idx,
    kind: normalized.kind,
    x: normalized.x,
    y: normalized.y,
    w: normalized.w,
    h: normalized.h,
  };
}

function sentenceIdsForHighlight(highlight) {
  if (Array.isArray(highlight?.sentence_ids)) {
    return highlight.sentence_ids.map((id) => String(id)).filter(Boolean);
  }
  return highlight?.sid ? [String(highlight.sid)] : [];
}

function highlightOverlapScore(a, b) {
  if (!a || !b || Number(a.slide_idx) !== Number(b.slide_idx)) return 0;
  const ax2 = Number(a.x ?? 0) + Number(a.w ?? 0);
  const ay2 = Number(a.y ?? 0) + Number(a.h ?? 0);
  const bx2 = Number(b.x ?? 0) + Number(b.w ?? 0);
  const by2 = Number(b.y ?? 0) + Number(b.h ?? 0);
  const ix1 = Math.max(Number(a.x ?? 0), Number(b.x ?? 0));
  const iy1 = Math.max(Number(a.y ?? 0), Number(b.y ?? 0));
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  const iw = Math.max(0, ix2 - ix1);
  const ih = Math.max(0, iy2 - iy1);
  const inter = iw * ih;
  const union = Number(a.w ?? 0) * Number(a.h ?? 0) + Number(b.w ?? 0) * Number(b.h ?? 0) - inter;
  return union > 0 ? inter / union : 0;
}

function mergeScriptAssignmentsIntoCurrentLayout(currentHighlights, generatedHighlights) {
  const normalizedGenerated = mergeGeneratedHighlights(generatedHighlights ?? []);
  if (!currentHighlights?.length) return normalizedGenerated;
  if (!normalizedGenerated.length) return currentHighlights;

  const used = new Set();
  return currentHighlights.map((current) => {
    const reviewed = normalizeHighlight(current);
    let best = null;
    let bestScore = 0;
    for (const generated of normalizedGenerated) {
      if (used.has(generated.id)) continue;
      const score = highlightOverlapScore(reviewed, generated);
      if (score > bestScore) {
        best = generated;
        bestScore = score;
      }
    }
    if (!best || bestScore < 0.25) {
      return {
        ...reviewed,
        sentence_ids: reviewed.sentence_ids ?? [],
      };
    }
    used.add(best.id);
    const sentence_ids = sentenceIdsForHighlight(best);
    return {
      ...reviewed,
      sentence_ids,
      sid: sentence_ids[0] ?? undefined,
    };
  });
}

function reconcileHighlightsWithSentences(highlights = [], sentences = []) {
  const slideBySentence = new Map(
    (sentences ?? []).map((sentence) => [String(sentence.id), Number(sentence.slide_idx ?? 0)]),
  );
  return (highlights ?? []).map((highlight) => {
    const normalized = normalizeHighlight(highlight);
    const sentence_ids = [...new Set(sentenceIdsForHighlight(normalized))]
      .filter((id) => slideBySentence.has(id) && slideBySentence.get(id) === Number(normalized.slide_idx ?? 0));
    return {
      ...normalized,
      sentence_ids,
      sid: sentence_ids[0] ?? undefined,
    };
  });
}

function buildBaseline(data, appMode) {
  return {
    created_at: new Date().toISOString(),
    mode: appMode,
    slide_meta: (data.slides ?? []).map(sanitizeSlideMeta),
    sentences: (data.sentences ?? []).map(sanitizeSentence),
    highlights: (data.highlights ?? []).map(sanitizeHighlight),
    generation_ref: data.generation_ref ?? null,
  };
}

function normalizeBaselineForUi(baseline, fallbackData, appMode) {
  const source = baseline ?? buildBaseline(fallbackData, appMode);
  const sentences = normalizeSentencesForUi(source.sentences ?? []);
  const highlights = reconcileHighlightsWithSentences(source.highlights ?? [], sentences);
  return {
    ...source,
    sentences,
    highlights,
  };
}

function derivePreviewFrame(slides = []) {
  const rows = (slides ?? [])
    .map((slide) => {
      const width = Number(slide?.width ?? 0);
      const height = Number(slide?.height ?? 0);
      if (!(width > 0) || !(height > 0)) return null;
      return { width, height, key: `${width}x${height}` };
    })
    .filter(Boolean);

  if (!rows.length) {
    return { width: 1600, height: 900, aspect_ratio: 16 / 9 };
  }

  const counts = new Map();
  for (const row of rows) {
    counts.set(row.key, (counts.get(row.key) ?? 0) + 1);
  }
  const winnerKey = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? rows[0].key;
  const winner = rows.find((row) => row.key === winnerKey) ?? rows[0];
  return {
    width: winner.width,
    height: winner.height,
    aspect_ratio: winner.width / Math.max(winner.height, 1),
  };
}

function deriveTotalDuration(sentences = [], fallback = 0) {
  const ends = (sentences ?? [])
    .map((sentence) => Number(sentence?.end_sec ?? 0))
    .filter((value) => Number.isFinite(value));
  if (!ends.length) return Math.max(0, Number(fallback ?? 0) || 0);
  return Math.max(0, ...ends);
}

function mergeSlidesWithPersistentImages(currentSlides = [], generatedSlides = []) {
  if (!currentSlides.length) return generatedSlides;
  if (!generatedSlides.length) return currentSlides;

  const generatedById = new Map(
    generatedSlides
      .filter((slide) => slide?.id != null)
      .map((slide) => [String(slide.id), slide]),
  );
  return currentSlides.map((current, idx) => {
    const generated = generatedById.get(String(current?.id)) ?? generatedSlides[idx];
    if (!generated) return current;
    return {
      ...generated,
      ...current,
      image_base64: current?.image_base64 ?? generated?.image_base64 ?? null,
      image_artifact_id: generated?.image_artifact_id ?? current?.image_artifact_id ?? null,
      image_url: generated?.image_url ?? current?.image_url ?? null,
      image_available: Boolean(
        current?.image_base64
        || generated?.image_base64
        || generated?.image_url
        || current?.image_url
        || generated?.image_available
        || current?.image_available
      ),
    };
  });
}

function makeStudyEvent(kind, payload = {}) {
  return {
    id: `evt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    at: new Date().toISOString(),
    kind,
    payload: clonePlain(payload),
  };
}

function appendStudyEvent(events, event) {
  const next = [...(events ?? []), event];
  return next.slice(-MAX_STUDY_EVENTS);
}

function snapshotHistoryState(state) {
  return clonePlain({
    slides: state.slides,
    sents: state.sents,
    hls: state.hls,
    totDur: state.totDur,
    generated: state.generated,
    genRef: state.genRef,
    sessionId: state.sessionId,
    baseline: state.baseline,
    projectMeta: state.projectMeta,
    inputPdf: state.inputPdf,
    previewFrame: state.previewFrame,
    savedFingerprint: state.savedFingerprint,
    curSl: state.curSl,
    selSent: state.selSent,
    selHl: state.selHl,
    appMode: state.appMode,
    detail: state.detail,
    level: state.level,
    prevMode: state.prevMode,
    status: state.status,
    statusMsg: state.statusMsg,
    progress: state.progress,
    showProg: state.showProg,
    drawMode: state.drawMode,
    drawSentId: state.drawSentId,
    drawKind: state.drawKind,
    curT: state.curT,
    playing: state.playing,
    playSpeed: state.playSpeed,
    seekSignal: state.seekSignal,
    previewAudioStale: state.previewAudioStale,
    opLogs: state.opLogs,
    studyEvents: state.studyEvents,
  });
}

function restoreHistoryState(state, snapshot, past, future) {
  const scriptChanged = JSON.stringify(state.sents ?? []) !== JSON.stringify(snapshot.sents ?? []);
  return {
    ...state,
    ...clonePlain(snapshot),
    previewAudioStale: scriptChanged || Boolean(snapshot.previewAudioStale),
    historyPast: past,
    historyFuture: future,
  };
}

export function reducer(state, action) {
  switch (action.type) {
    case "PUSH_HISTORY": {
      const past = [...state.historyPast, snapshotHistoryState(state)].slice(-MAX_HISTORY);
      return {
        ...state,
        historyPast: past,
        historyFuture: [],
      };
    }

    case "UNDO": {
      if (!state.historyPast.length) return state;
      const snapshot = state.historyPast[state.historyPast.length - 1];
      const past = state.historyPast.slice(0, -1);
      const future = [snapshotHistoryState(state), ...state.historyFuture].slice(0, MAX_HISTORY);
      return restoreHistoryState(state, snapshot, past, future);
    }

    case "REDO": {
      if (!state.historyFuture.length) return state;
      const snapshot = state.historyFuture[0];
      const future = state.historyFuture.slice(1);
      const past = [...state.historyPast, snapshotHistoryState(state)].slice(-MAX_HISTORY);
      return restoreHistoryState(state, snapshot, past, future);
    }

    // ── データロード（生成・インポート共通） ──
    case "LOAD": {
      const sents  = normalizeSentencesForUi(action.d.sentences ?? []);
      const totDur = action.d.total_duration
        ?? deriveTotalDuration(sents, 0);
      const normalizedHighlights = reconcileHighlightsWithSentences(
        mergeGeneratedHighlights(action.d.highlights ?? []),
        sents,
      );
      const savedSettings = action.d.settings ?? null;
      // ロードされたデータに mode が含まれていれば appMode も上書き
      const appMode = action.d.mode ?? state.appMode;
      const previewFrame = savedSettings?.preview_frame ?? derivePreviewFrame(action.d.slides ?? []);
      const generated = typeof action.d.generated === "boolean"
        ? action.d.generated
        : (action.d.slides ?? []).length > 0;
      const persistedSettings = savedSettings
        ? { ...savedSettings, preview_frame: previewFrame }
        : {
            detail: state.detail,
            level: state.level,
            prev_mode: appMode === "audio" ? "audio" : appMode === "video" ? "plain" : "hl",
            play_speed: state.playSpeed,
            preview_frame: previewFrame,
          };
      const baseline = normalizeBaselineForUi(
        action.d.baseline,
        { ...action.d, sentences: sents, highlights: normalizedHighlights },
        appMode,
      );
      const sessionId = action.d.session_id ?? makeSessionId();
      const shouldTrackLoad = !action.markSaved;
      const nextOpLogs = shouldTrackLoad
        ? appendLog(
            action.d.operation_logs ?? [],
            `講義データを読み込みました（slides=${(action.d.slides ?? []).length}, sentences=${sents.length}, mode=${appMode}）`,
            { type: "load", mode: appMode, slides: (action.d.slides ?? []).length, sentences: sents.length },
          )
        : (action.d.operation_logs ?? []);
      const nextStudyEvents = shouldTrackLoad
        ? appendStudyEvent(
            action.d.study_events ?? [],
            makeStudyEvent("session_loaded", {
              session_id: sessionId,
              mode: appMode,
              slide_count: (action.d.slides ?? []).length,
              sentence_count: sents.length,
              highlight_count: normalizedHighlights.length,
              generation_ref: action.d.generation_ref ?? null,
            }),
          )
        : (action.d.study_events ?? []);
      const savedFingerprint = fingerprintProjectData({
        slides: action.d.slides ?? [],
        sentences: sents,
        highlights: normalizedHighlights,
        total_duration: action.d.total_duration ?? totDur,
        generated,
        mode: appMode,
        generation_ref: action.d.generation_ref ?? null,
        operation_logs: action.markSaved ? nextOpLogs : (action.d.operation_logs ?? []),
        study_events: action.markSaved ? nextStudyEvents : (action.d.study_events ?? []),
        settings: persistedSettings,
        project_meta: action.d.project_meta ?? state.projectMeta ?? null,
        input_pdf: action.d.input_pdf ?? null,
      });
      const prevMode = savedSettings?.prev_mode
        ?? (appMode === "audio" ? "audio" : appMode === "video" ? "plain" : "hl");
      return {
        ...state,
        slides:    action.d.slides ?? [],
        sents,
        hls:       normalizedHighlights,
        totDur,
        genRef:    action.d.generation_ref ?? null,
        appMode,
        curSl:     0,
        generated,
        selSent:   null,
        selHl:     null,
        curT:      0,
        playing:   false,
        previewActiveSentenceId: null,
        previewAudioStale: action.d.preview_audio?.stale ?? true,
        detail:    savedSettings?.detail ?? state.detail,
        level:     savedSettings?.level ?? state.level,
        prevMode,
        playSpeed: savedSettings?.play_speed ?? state.playSpeed,
        status: "idle",
        statusMsg: "待機中",
        progress: 0,
        showProg: false,
        drawMode: false,
        drawSentId: null,
        drawKind: "marker",
        sessionId,
        baseline,
        projectMeta: action.d.project_meta ?? state.projectMeta ?? null,
        inputPdf: action.d.input_pdf ?? null,
        previewFrame,
        savedFingerprint,
        historyPast: [],
        historyFuture: [],
        opLogs:    nextOpLogs,
        studyEvents: nextStudyEvents,
      };
    }

    case "MERGE_SCRIPT_RESULT": {
      const data = action.d ?? {};
      const sents = normalizeSentencesForUi(data.sentences ?? []);
      const totDur = data.total_duration ?? deriveTotalDuration(sents, state.totDur);
      const appMode = data.mode ?? state.appMode;
      const slides = mergeSlidesWithPersistentImages(state.slides ?? [], data.slides ?? []);
      const highlights = reconcileHighlightsWithSentences(
        mergeScriptAssignmentsIntoCurrentLayout(state.hls, data.highlights ?? []),
        sents,
      );
      const previewFrame = state.previewFrame ?? derivePreviewFrame(slides);
      const generationRef = data.generation_ref ?? state.genRef ?? null;
      const nextOpLogs = appendLog(
        state.opLogs,
        `台本生成が完了しました（sentences=${sents.length}, mode=${appMode}）`,
        { type: "merge_script_result", mode: appMode, sentences: sents.length, generation_ref: generationRef },
      );
      const nextStudyEvents = appendStudyEvent(
        state.studyEvents,
        makeStudyEvent("script_generation_loaded", {
          session_id: state.sessionId,
          mode: appMode,
          sentence_count: sents.length,
          generation_ref: generationRef,
        }),
      );
      return {
        ...state,
        slides,
        sents,
        hls: highlights,
        totDur,
        genRef: generationRef,
        appMode,
        generated: true,
        previewFrame,
        previewAudioStale: true,
        opLogs: nextOpLogs,
        studyEvents: nextStudyEvents,
      };
    }

    case "RECONCILE_REVIEW_ASSIGNMENTS": {
      const beforeLinks = (state.hls ?? []).reduce((sum, hl) => sum + (hl.sentence_ids ?? []).length, 0);
      const highlights = reconcileHighlightsWithSentences(state.hls, state.sents);
      const afterLinks = highlights.reduce((sum, hl) => sum + (hl.sentence_ids ?? []).length, 0);
      const selectedExists = highlights.some((hl) => hl.id === state.selHl);
      return {
        ...state,
        hls: highlights,
        selHl: selectedExists ? state.selHl : null,
        drawMode: false,
        drawSentId: null,
        opLogs: appendLog(
          state.opLogs,
          "確認済み領域を基準に、台本との対応関係を再整合しました",
          { type: "review_assignment_reconcile", before_links: beforeLinks, after_links: afterLinks },
        ),
      };
    }

    case "APPLY_REVIEW_ASSIGNMENT": {
      const data = action.d ?? {};
      const sents = normalizeSentencesForUi(data.sentences?.length ? data.sentences : state.sents);
      const highlights = reconcileHighlightsWithSentences(data.highlights ?? state.hls, sents);
      const linkCount = highlights.reduce((sum, hl) => sum + (hl.sentence_ids ?? []).length, 0);
      const selectedExists = highlights.some((hl) => hl.id === state.selHl);
      const generationRef = data.generation_ref ?? state.genRef ?? null;
      return {
        ...state,
        sents,
        hls: highlights,
        genRef: generationRef,
        selHl: selectedExists ? state.selHl : null,
        drawMode: false,
        drawSentId: null,
        opLogs: appendLog(
          state.opLogs,
          `確認済み領域と確認済み台本から対応付けを生成しました（links=${linkCount}）`,
          { type: "review_assignment_generated", links: linkCount, generation_ref: generationRef },
        ),
        studyEvents: appendStudyEvent(
          state.studyEvents,
          makeStudyEvent("review_assignment_generated", {
            session_id: state.sessionId,
            link_count: linkCount,
            generation_ref: generationRef,
          }),
        ),
      };
    }

    // ── ナビゲーション ──
    case "SET_SL":
      return {
        ...state,
        curSl: clamp(action.v, 0, Math.max(0, state.slides.length - 1)),
        drawMode: false,
        drawSentId: null,
        drawKind: "marker",
        selHl: null,
        previewActiveSentenceId: null,
      };

    case "SEEK_SLIDE": {
      const slideIdx = clamp(action.v, 0, Math.max(0, state.slides.length - 1));
      const slideSents = state.sents
        .filter((sent) => sent.slide_idx === slideIdx)
        .sort((a, b) => Number(a.start_sec ?? 0) - Number(b.start_sec ?? 0));
      const t = slideSents.length ? Number(slideSents[0].start_sec ?? 0) || 0 : state.curT;
      return {
        ...state,
        curSl: slideIdx,
        curT: clamp(t, 0, Math.max(state.totDur, 0)),
        drawMode: false,
        drawSentId: null,
        drawKind: "marker",
        selHl: null,
        previewActiveSentenceId: null,
        seekSignal: state.seekSignal + 1,
      };
    }

    case "SEL_SENT":
      return { ...state, selSent: action.v };

    case "SEL_HL": {
      const h = state.hls.find((hl) => hl.id === action.v);
      return { ...state, selHl: action.v, selSent: h?.sentence_ids?.[0] ?? state.selSent };
    }

    // ── HL 操作 ──
    case "ADD_HL_BOX": {
      const sid = action.sid ? String(action.sid) : null;
      const sentence = sid ? state.sents.find((s) => s.id === sid) : null;
      const slide_idx = sentence?.slide_idx ?? action.slide_idx ?? state.curSl;
      const kind = action.kind ?? findHighlightForSentence(state.hls, sid)?.kind ?? "marker";
      let nextHighlights = state.hls.map((hl) => ({
        ...hl,
        sentence_ids: sid ? (hl.sentence_ids ?? []).filter((id) => id !== sid) : (hl.sentence_ids ?? []),
      }));
      const newHl = {
        id: `h_${Date.now()}`,
        slide_idx,
        sentence_ids: sid ? [sid] : [],
        kind,
        ...action.region,
      };
      nextHighlights = [...nextHighlights, newHl];
      return {
        ...state,
        hls: nextHighlights,
        selHl: newHl.id,
        selSent: sid ?? state.selSent,
        opLogs: appendLog(
          state.opLogs,
          `ハイライト枠を追加しました（slide=${slide_idx + 1}${sid ? ", 対応あり" : ", 未対応"}）`,
          { type: "highlight_add_box", slide_idx, sid },
        ),
        studyEvents: appendStudyEvent(
          state.studyEvents,
          makeStudyEvent("highlight_add", {
            sentence_id: sid,
            slide_idx,
            after: sanitizeHighlight(newHl),
          }),
        ),
      };
    }

    case "APPLY_REGION": {
      const sent = action.sid ? state.sents.find((s) => s.id === action.sid) : null;
      const targetId = action.id ?? null;
      const target = targetId ? state.hls.find((hl) => hl.id === targetId) : null;
      const sid = action.sid ? String(action.sid) : null;
      const kind = action.kind ?? target?.kind ?? findHighlightForSentence(state.hls, sid)?.kind ?? "marker";
      const slide_idx = sent?.slide_idx ?? target?.slide_idx ?? state.curSl;
      let nextHighlights = state.hls.map((hl) => ({ ...hl }));
      let before = null;
      let nextHl = null;

      if (target) {
        before = target;
        nextHighlights = nextHighlights.map((hl) => {
          if (hl.id !== target.id) {
            return sid ? { ...hl, sentence_ids: (hl.sentence_ids ?? []).filter((id) => id !== sid) } : hl;
          }
          const sentence_ids = sid
            ? [...new Set([...(hl.sentence_ids ?? []).filter(Boolean), sid])]
            : (hl.sentence_ids ?? []);
          nextHl = { ...hl, ...action.region, kind, sentence_ids };
          return nextHl;
        });
      } else {
        if (sid) {
          nextHighlights = nextHighlights.map((hl) => ({
            ...hl,
            sentence_ids: (hl.sentence_ids ?? []).filter((id) => id !== sid),
          }));
        }
        nextHl = {
          id: `h_${Date.now()}`,
          slide_idx,
          sentence_ids: sid ? [sid] : [],
          kind,
          ...action.region,
        };
        nextHighlights = [...nextHighlights, nextHl];
      }

      return {
        ...state,
        hls:     nextHighlights,
        selHl:   nextHl.id,
        selSent: sid ?? state.selSent,
        opLogs:  appendLog(
          state.opLogs,
          `ハイライトを設定しました（slide=${slide_idx + 1}, kind=${kind}）`,
          { type: "highlight_add", sid, kind, slide_idx },
        ),
        studyEvents: appendStudyEvent(
          state.studyEvents,
          makeStudyEvent("highlight_apply", {
            sentence_id: sid,
            slide_idx,
            before: before ? sanitizeHighlight(before) : null,
            after: sanitizeHighlight(nextHl),
          }),
        ),
      };
    }

    case "RM_HL_SID": {
      const sid = String(action.v);
      const removed = findHighlightForSentence(state.hls, sid);
      const nextHighlights = state.hls
        .map((hl) => ({
          ...hl,
          sentence_ids: (hl.sentence_ids ?? []).filter((id) => id !== sid),
        }))
        .filter((hl) => (hl.sentence_ids ?? []).length > 0 || hl.id !== removed?.id);
      return {
        ...state,
        hls:   nextHighlights,
        selHl: removed && state.selHl === removed.id ? null : state.selHl,
        opLogs: removed
          ? appendLog(
              state.opLogs,
              `ハイライトとの対応を解除しました（slide=${removed.slide_idx + 1}）`,
              { type: "highlight_unlink", sid, slide_idx: removed.slide_idx },
            )
          : state.opLogs,
        studyEvents: removed
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("highlight_remove", {
                sentence_id: sid,
                slide_idx: removed.slide_idx,
                before: sanitizeHighlight(removed),
              }),
            )
          : state.studyEvents,
      };
    }

    case "RM_HL_ID":
      {
        const removed = state.hls.find((h) => h.id === action.v);
      return {
        ...state,
        hls:   state.hls.filter((h) => h.id !== action.v),
        selHl: state.selHl === action.v ? null : state.selHl,
        opLogs: removed
          ? appendLog(
              state.opLogs,
              `ハイライト枠を削除しました（slide=${removed.slide_idx + 1}, 対応数=${(removed.sentence_ids ?? []).length}）`,
              { type: "highlight_remove", id: action.v, slide_idx: removed.slide_idx, links: (removed.sentence_ids ?? []).length },
            )
          : state.opLogs,
        studyEvents: removed
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("highlight_remove", {
                highlight_id: action.v,
                slide_idx: removed.slide_idx,
                before: sanitizeHighlight(removed),
              }),
            )
          : state.studyEvents,
      };
      }

    case "LINK_SENT_TO_HL": {
      const sid = String(action.sid);
      const highlight = state.hls.find((hl) => hl.id === action.id);
      if (!highlight) return state;
      const nextHighlights = state.hls.map((hl) => {
        const sentence_ids = (hl.sentence_ids ?? []).filter((id) => id !== sid);
        if (hl.id === action.id) {
          return { ...hl, sentence_ids: [...new Set([...sentence_ids, sid])] };
        }
        return { ...hl, sentence_ids };
      });
      return {
        ...state,
        hls: nextHighlights,
        selHl: action.id,
        selSent: sid,
        opLogs: appendLog(
          state.opLogs,
          `ハイライト枠を文に対応付けました（sentence=${sid}）`,
          { type: "highlight_link", id: action.id, sid },
        ),
      };
    }

    case "UNLINK_SENT_FROM_HL": {
      const sid = String(action.sid);
      const highlight = state.hls.find((hl) => hl.id === action.id);
      if (!highlight) return state;
      const nextHighlights = state.hls
        .map((hl) => hl.id === action.id
          ? { ...hl, sentence_ids: (hl.sentence_ids ?? []).filter((id) => id !== sid) }
          : hl)
        .filter((hl) => (hl.sentence_ids ?? []).length > 0 || hl.id !== action.id);
      return {
        ...state,
        hls: nextHighlights,
        selHl: state.selHl === action.id ? null : state.selHl,
        opLogs: appendLog(
          state.opLogs,
          `ハイライト枠との対応を解除しました（sentence=${sid}）`,
          { type: "highlight_unlink", id: action.id, sid },
        ),
      };
    }

    case "SET_HL_KIND": {
      const prev = state.hls.find((h) => h.id === action.id);
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === action.id ? { ...h, kind: action.kind } : h)),
        opLogs: appendLog(
          state.opLogs,
          `ハイライト種別を変更しました（kind=${action.kind}）`,
          { type: "highlight_kind", id: action.id, kind: action.kind },
        ),
        studyEvents: prev
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("highlight_kind", {
                highlight_id: action.id,
                slide_idx: prev.slide_idx,
                before: sanitizeHighlight(prev),
                after: sanitizeHighlight({ ...prev, kind: action.kind }),
              }),
            )
          : state.studyEvents,
      };
    }

    case "UPD_HL": {
      const { id, x, y, w, hv } = action;
      const prev = state.hls.find((h) => h.id === id);
      const nextHl = prev ? { ...prev, x, y, w, h: hv } : null;
      const shouldTrack = !action.transient;
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === id ? { ...h, x, y, w, h: hv } : h)),
        opLogs: shouldTrack
          ? appendLog(
              state.opLogs,
              "ハイライト位置を更新しました",
              { type: "highlight_update", id, x, y, w, h: hv },
            )
          : state.opLogs,
        studyEvents: shouldTrack && prev && nextHl
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("highlight_update", {
                highlight_id: id,
                slide_idx: prev.slide_idx,
                before: sanitizeHighlight(prev),
                after: sanitizeHighlight(nextHl),
              }),
            )
          : state.studyEvents,
      };
    }

    // ── 台本操作 ──
    case "ADD_SENT": {
      const id = `s_${Date.now()}`;
      const startSec = deriveTotalDuration(state.sents, state.totDur);
      const newSent = {
        id,
        slide_idx: state.appMode === "audio" ? 0 : state.curSl,
        text:      "（新しい文）",
        start_sec: startSec,
        end_sec:   startSec + 3,
      };
      return {
        ...state,
        sents: [...state.sents, newSent],
        totDur: startSec + 3,
        previewAudioStale: true,
        opLogs: appendLog(
          state.opLogs,
          `文を追加しました（slide=${(state.appMode === "audio" ? 1 : state.curSl + 1)}）`,
          { type: "sentence_add", slide_idx: state.appMode === "audio" ? 0 : state.curSl },
        ),
        studyEvents: appendStudyEvent(
          state.studyEvents,
          makeStudyEvent("sentence_add", {
            slide_idx: newSent.slide_idx,
            after: sanitizeSentence(newSent),
          }),
        ),
      };
    }

    case "DEL_SENT": {
      const removed = state.sents.find((s) => s.id === action.v);
      const nextSents = state.sents.filter((s) => s.id !== action.v);
      const nextTotDur = deriveTotalDuration(nextSents, 0);
      const nextCurT = clamp(state.curT, 0, nextTotDur);
      const nextHighlights = state.hls
        .map((hl) => ({
          ...hl,
          sentence_ids: (hl.sentence_ids ?? []).filter((id) => id !== String(action.v)),
        }))
        .filter((hl) => (hl.sentence_ids ?? []).length > 0);
      return {
        ...state,
        sents:   nextSents,
        hls:     nextHighlights,
        totDur:  nextTotDur,
        curT:    nextCurT,
        playing: state.playing && nextCurT < nextTotDur,
        previewAudioStale: true,
        selSent: state.selSent === action.v ? null : state.selSent,
        opLogs: removed
          ? appendLog(
              state.opLogs,
              `文を削除しました（slide=${removed.slide_idx + 1}, text=${shortText(removed.text)})`,
              { type: "sentence_delete", id: action.v, slide_idx: removed.slide_idx },
            )
          : state.opLogs,
        studyEvents: removed
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("sentence_delete", {
                sentence_id: action.v,
                slide_idx: removed.slide_idx,
                before: sanitizeSentence(removed),
              }),
            )
          : state.studyEvents,
      };
    }

    case "UPD_TXT": {
      const prev = state.sents.find((s) => s.id === action.id);
      return {
        ...state,
        sents: state.sents.map((s) => (s.id === action.id ? { ...s, text: action.text } : s)),
        previewAudioStale: prev && prev.text !== action.text ? true : state.previewAudioStale,
        opLogs: prev && prev.text !== action.text
          ? appendLog(
              state.opLogs,
              `文を編集しました（text=${shortText(action.text)})`,
              { type: "sentence_text", id: action.id, slide_idx: prev.slide_idx },
            )
          : state.opLogs,
        studyEvents: prev && prev.text !== action.text
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("sentence_text", {
                sentence_id: action.id,
                slide_idx: prev.slide_idx,
                before: sanitizeSentence(prev),
                after: sanitizeSentence({ ...prev, text: action.text }),
              }),
            )
          : state.studyEvents,
      };
    }

    case "UPD_SENT_TIME": {
      const prev = state.sents.find((s) => s.id === action.id);
      const nextSents = state.sents.map((s) =>
        s.id === action.id
          ? { ...s, start_sec: action.start_sec, end_sec: action.end_sec }
          : s
      );
      const nextTotDur = deriveTotalDuration(nextSents, 0);
      const nextCurT = clamp(state.curT, 0, nextTotDur);
      return {
        ...state,
        sents: nextSents,
        totDur: nextTotDur,
        curT: nextCurT,
        playing: state.playing && nextCurT < nextTotDur,
        previewAudioStale: true,
        opLogs: prev
          ? appendLog(
              state.opLogs,
              `文のタイミングを更新しました（${action.start_sec}s-${action.end_sec}s）`,
              { type: "sentence_time", id: action.id, slide_idx: prev.slide_idx, start_sec: action.start_sec, end_sec: action.end_sec },
            )
          : state.opLogs,
        studyEvents: prev
          ? appendStudyEvent(
              state.studyEvents,
              makeStudyEvent("sentence_time", {
                sentence_id: action.id,
                slide_idx: prev.slide_idx,
                before: sanitizeSentence(prev),
                after: sanitizeSentence({ ...prev, start_sec: action.start_sec, end_sec: action.end_sec }),
              }),
            )
          : state.studyEvents,
      };
    }

    case "APPLY_PREVIEW_TIMINGS": {
      return state;
    }


    // ── シーク（スライド連動 + 再生中リスタートトリガー）──
    case "SEEK": {
      const t = action.v;
      // 対応するスライドを特定
      const targetSent = state.sents.find((s) => s.start_sec <= t && t < s.end_sec);
      const newSl = targetSent ? targetSent.slide_idx : state.curSl;
      return {
        ...state,
        curT:       t,
        curSl:      newSl,
        previewActiveSentenceId: null,
        seekSignal: state.seekSignal + 1,
      };
    }

    case "PLAY_SENTENCE": {
      const sentence = state.sents.find((row) => String(row.id) === String(action.id));
      if (!sentence) return state;
      const startSec = Math.max(0, Number(sentence.start_sec ?? 0) || 0);
      return {
        ...state,
        curT: startSec,
        curSl: Number(sentence.slide_idx ?? state.curSl),
        selSent: sentence.id,
        previewActiveSentenceId: String(sentence.id),
        seekSignal: state.seekSignal + 1,
      };
    }

    case "SET_PREVIEW_TIME": {
      const maxT = Math.max(0, Number(action.totalDuration ?? state.totDur) || 0);
      const t = clamp(Number(action.v ?? 0) || 0, 0, maxT);
      const previewActiveSentenceId = action.sentenceId ? String(action.sentenceId) : null;
      const targetSent = previewActiveSentenceId
        ? state.sents.find((s) => String(s.id) === previewActiveSentenceId)
        : state.sents.find((s) => s.start_sec <= t && t < s.end_sec);
      return {
        ...state,
        curT: t,
        curSl: action.slideIdx ?? (targetSent ? targetSent.slide_idx : state.curSl),
        previewActiveSentenceId,
      };
    }

    case "SET_PREVIEW_AUDIO_STALE":
      return {
        ...state,
        previewAudioStale: Boolean(action.v),
      };

    // ── 汎用・リセット ──
    case "SET": {
      const next = { ...state, [action.k]: action.v };
      if (action.k === "detail") {
        next.opLogs = appendLog(state.opLogs, `詳細度を変更しました（value=${action.v}）`, { type: "setting_detail", value: action.v });
      } else if (action.k === "level") {
        next.opLogs = appendLog(state.opLogs, `難易度を変更しました（value=${action.v}）`, { type: "setting_level", value: action.v });
      } else if (action.k === "appMode") {
        next.opLogs = appendLog(state.opLogs, `提示形態を変更しました（mode=${action.v}）`, { type: "setting_mode", value: action.v });
      } else if (action.k === "prevMode") {
        next.opLogs = appendLog(state.opLogs, `プレビュー表示を切り替えました（mode=${action.v}）`, { type: "preview_mode", value: action.v });
      } else if (action.k === "playSpeed") {
        next.opLogs = appendLog(state.opLogs, `再生速度を変更しました（speed=${action.v}）`, { type: "play_speed", value: action.v });
      }
      return next;
    }
    case "APP_LOG":
      return {
        ...state,
        opLogs: appendLog(state.opLogs, action.message, action.meta),
      };
    case "RESET":
      return {
        ...INITIAL_STATE,
        historyPast: [],
        historyFuture: [],
      };
    default:      return state;
  }
}
