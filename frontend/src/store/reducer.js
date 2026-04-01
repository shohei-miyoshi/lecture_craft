/**
 * LectureCraft — アプリ全状態 Reducer
 *
 * appMode（提示形態）は生成後にロックされる。
 * 別のモードで再生成する場合はリセットが必要。
 */

export const INITIAL_STATE = {
  // データ
  slides:    [],
  sents:     [],
  hls:       [],
  totDur:    0,
  generated: false,
  genRef:    null,

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
};

const MAX_OP_LOGS = 300;

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

export function reducer(state, action) {
  switch (action.type) {

    // ── データロード（生成・インポート共通） ──
    case "LOAD": {
      const sents  = action.d.sentences ?? [];
      const totDur = action.d.total_duration
        ?? (sents.length ? Math.max(...sents.map((s) => s.end_sec ?? 0)) : 60);
      // ロードされたデータに mode が含まれていれば appMode も上書き
      const appMode = action.d.mode ?? state.appMode;
      const prevMode = appMode === "audio" ? "audio"
        : appMode === "video" ? "plain" : "hl";
      return {
        ...state,
        slides:    action.d.slides ?? [],
        sents,
        hls:       action.d.highlights ?? [],
        totDur,
        genRef:    action.d.generation_ref ?? null,
        appMode,
        curSl:     0,
        generated: true,
        selSent:   null,
        selHl:     null,
        curT:      0,
        playing:   false,
        prevMode,
        opLogs:    appendLog(
          state.opLogs,
          `講義データを読み込みました（slides=${(action.d.slides ?? []).length}, sentences=${sents.length}, mode=${appMode}）`,
          { type: "load", mode: appMode, slides: (action.d.slides ?? []).length, sentences: sents.length },
        ),
      };
    }

    // ── ナビゲーション ──
    case "SET_SL":
      return { ...state, curSl: action.v, drawMode: false, drawSentId: null, selHl: null };

    case "SEL_SENT":
      return { ...state, selSent: action.v };

    case "SEL_HL": {
      const h = state.hls.find((h) => h.id === action.v);
      return { ...state, selHl: action.v, selSent: h?.sid ?? state.selSent };
    }

    // ── HL 操作 ──
    case "APPLY_REGION": {
      const sent = state.sents.find((s) => s.id === action.sid);
      if (!sent) return state;
      const newHl = {
        id:         `h_${Date.now()}`,
        sid:        action.sid,
        slide_idx:  sent.slide_idx,
        kind:       action.kind,
        ...action.region,
      };
      return {
        ...state,
        hls:     [...state.hls.filter((h) => h.sid !== action.sid), newHl],
        selHl:   newHl.id,
        selSent: action.sid,
        opLogs:  appendLog(
          state.opLogs,
          `ハイライトを設定しました（slide=${sent.slide_idx + 1}, kind=${action.kind}）`,
          { type: "highlight_add", sid: action.sid, kind: action.kind, slide_idx: sent.slide_idx },
        ),
      };
    }

    case "RM_HL_SID": {
      const removed = state.hls.find((h) => h.sid === action.v);
      return {
        ...state,
        hls:   state.hls.filter((h) => h.sid !== action.v),
        selHl: removed && state.selHl === removed.id ? null : state.selHl,
        opLogs: removed
          ? appendLog(
              state.opLogs,
              `ハイライトを削除しました（slide=${removed.slide_idx + 1}）`,
              { type: "highlight_remove", sid: action.v, slide_idx: removed.slide_idx },
            )
          : state.opLogs,
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
              `ハイライトを削除しました（slide=${removed.slide_idx + 1}）`,
              { type: "highlight_remove", id: action.v, slide_idx: removed.slide_idx },
            )
          : state.opLogs,
      };
      }

    case "SET_HL_KIND":
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === action.id ? { ...h, kind: action.kind } : h)),
        opLogs: appendLog(
          state.opLogs,
          `ハイライト種別を変更しました（kind=${action.kind}）`,
          { type: "highlight_kind", id: action.id, kind: action.kind },
        ),
      };

    case "UPD_HL": {
      const { id, x, y, w, hv } = action;
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === id ? { ...h, x, y, w, h: hv } : h)),
        opLogs: appendLog(
          state.opLogs,
          "ハイライト位置を更新しました",
          { type: "highlight_update", id, x, y, w, h: hv },
        ),
      };
    }

    // ── 台本操作 ──
    case "ADD_SENT": {
      const id = `s_${Date.now()}`;
      return {
        ...state,
        sents: [...state.sents, {
          id,
          slide_idx: state.appMode === "audio" ? 0 : state.curSl,
          text:      "（新しい文）",
          start_sec: state.totDur,
          end_sec:   state.totDur + 3,
        }],
        totDur: state.totDur + 3,
        opLogs: appendLog(
          state.opLogs,
          `文を追加しました（slide=${(state.appMode === "audio" ? 1 : state.curSl + 1)}）`,
          { type: "sentence_add", slide_idx: state.appMode === "audio" ? 0 : state.curSl },
        ),
      };
    }

    case "DEL_SENT": {
      const removed = state.sents.find((s) => s.id === action.v);
      return {
        ...state,
        sents:   state.sents.filter((s) => s.id !== action.v),
        hls:     state.hls.filter((h) => h.sid !== action.v),
        selSent: state.selSent === action.v ? null : state.selSent,
        opLogs: removed
          ? appendLog(
              state.opLogs,
              `文を削除しました（slide=${removed.slide_idx + 1}, text=${shortText(removed.text)})`,
              { type: "sentence_delete", id: action.v, slide_idx: removed.slide_idx },
            )
          : state.opLogs,
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
      };
    default:      return state;
  }
}
