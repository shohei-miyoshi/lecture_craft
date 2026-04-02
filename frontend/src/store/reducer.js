/**
 * LectureCraft — アプリ全状態 Reducer
 *
 * appMode（提示形態）は生成後にロックされる。
 * 別のモードで再生成する場合はリセットが必要。
 */

import { findHighlightForSentence, mergeGeneratedHighlights, normalizeHighlight } from "../utils/highlights.js";

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

  // 再生
  curT:      0,
  playing:   false,
  playSpeed: 1.0,
  seekSignal: 0,   // シーク操作ごとにインクリメント（usePlaybackの再起動トリガー）

  // 操作ログ
  opLogs:    [],
  studyEvents: [],
  historyPast: [],
  historyFuture: [],
};

const MAX_OP_LOGS = 300;
const MAX_STUDY_EVENTS = 2000;
const MAX_HISTORY = 80;

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
    curT: state.curT,
    playing: state.playing,
    playSpeed: state.playSpeed,
    seekSignal: state.seekSignal,
    opLogs: state.opLogs,
    studyEvents: state.studyEvents,
  });
}

function restoreHistoryState(state, snapshot, past, future) {
  return {
    ...state,
    ...clonePlain(snapshot),
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
      const sents  = action.d.sentences ?? [];
      const totDur = action.d.total_duration
        ?? (sents.length ? Math.max(...sents.map((s) => s.end_sec ?? 0)) : 60);
      const normalizedHighlights = mergeGeneratedHighlights(action.d.highlights ?? []);
      const savedSettings = action.d.settings ?? null;
      // ロードされたデータに mode が含まれていれば appMode も上書き
      const appMode = action.d.mode ?? state.appMode;
      const previewFrame = savedSettings?.preview_frame ?? derivePreviewFrame(action.d.slides ?? []);
      const savedFingerprint = JSON.stringify({
        slides: action.d.slides ?? [],
        sentences: action.d.sentences ?? [],
        highlights: action.d.highlights ?? [],
        total_duration: action.d.total_duration ?? totDur,
        mode: appMode,
        generation_ref: action.d.generation_ref ?? null,
        settings: savedSettings
          ? { ...savedSettings, preview_frame: previewFrame }
          : {
              detail: state.detail,
              level: state.level,
              prev_mode: appMode === "audio" ? "audio" : appMode === "video" ? "plain" : "hl",
              play_speed: state.playSpeed,
              preview_frame: previewFrame,
            },
        project_meta: {
          id: action.d.project_meta?.id ?? null,
          name: action.d.project_meta?.name ?? null,
          created_at: action.d.project_meta?.created_at ?? null,
        },
      });
      const prevMode = savedSettings?.prev_mode
        ?? (appMode === "audio" ? "audio" : appMode === "video" ? "plain" : "hl");
      const baseline = buildBaseline(action.d, appMode);
      const sessionId = makeSessionId();
      return {
        ...state,
        slides:    action.d.slides ?? [],
        sents,
        hls:       normalizedHighlights,
        totDur,
        genRef:    action.d.generation_ref ?? null,
        appMode,
        curSl:     0,
        generated: true,
        selSent:   null,
        selHl:     null,
        curT:      0,
        playing:   false,
        detail:    savedSettings?.detail ?? state.detail,
        level:     savedSettings?.level ?? state.level,
        prevMode,
        playSpeed: savedSettings?.play_speed ?? state.playSpeed,
        sessionId,
        baseline,
        projectMeta: action.d.project_meta ?? state.projectMeta ?? null,
        previewFrame,
        savedFingerprint,
        historyPast: [],
        historyFuture: [],
        opLogs:    appendLog(
          action.d.operation_logs ?? [],
          `講義データを読み込みました（slides=${(action.d.slides ?? []).length}, sentences=${sents.length}, mode=${appMode}）`,
          { type: "load", mode: appMode, slides: (action.d.slides ?? []).length, sentences: sents.length },
        ),
        studyEvents: appendStudyEvent(
          action.d.study_events ?? [],
          makeStudyEvent("session_loaded", {
            session_id: sessionId,
            mode: appMode,
            slide_count: (action.d.slides ?? []).length,
            sentence_count: sents.length,
            highlight_count: normalizedHighlights.length,
            generation_ref: action.d.generation_ref ?? null,
          }),
        ),
      };
    }

    // ── ナビゲーション ──
    case "SET_SL":
      return { ...state, curSl: action.v, drawMode: false, drawSentId: null, selHl: null };

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
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === id ? { ...h, x, y, w, h: hv } : h)),
        opLogs: appendLog(
          state.opLogs,
          "ハイライト位置を更新しました",
          { type: "highlight_update", id, x, y, w, h: hv },
        ),
        studyEvents: prev && nextHl
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
      const newSent = {
        id,
        slide_idx: state.appMode === "audio" ? 0 : state.curSl,
        text:      "（新しい文）",
        start_sec: state.totDur,
        end_sec:   state.totDur + 3,
      };
      return {
        ...state,
        sents: [...state.sents, newSent],
        totDur: state.totDur + 3,
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
      const nextHighlights = state.hls
        .map((hl) => ({
          ...hl,
          sentence_ids: (hl.sentence_ids ?? []).filter((id) => id !== String(action.v)),
        }))
        .filter((hl) => (hl.sentence_ids ?? []).length > 0);
      return {
        ...state,
        sents:   state.sents.filter((s) => s.id !== action.v),
        hls:     nextHighlights,
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
      return {
        ...state,
        sents: state.sents.map((s) =>
          s.id === action.id
            ? { ...s, start_sec: action.start_sec, end_sec: action.end_sec }
            : s
        ),
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
        seekSignal: state.seekSignal + 1,
      };
    }

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
        opLogs: appendLog(state.opLogs, "講義データをリセットしました", { type: "reset" }),
        historyPast: [],
        historyFuture: [],
      };
    default:      return state;
  }
}
