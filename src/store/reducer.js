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
};

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
        appMode,
        curSl:     0,
        generated: true,
        selSent:   null,
        selHl:     null,
        curT:      0,
        playing:   false,
        prevMode,
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
      };
    }

    case "RM_HL_SID": {
      const removed = state.hls.find((h) => h.sid === action.v);
      return {
        ...state,
        hls:   state.hls.filter((h) => h.sid !== action.v),
        selHl: removed && state.selHl === removed.id ? null : state.selHl,
      };
    }

    case "RM_HL_ID":
      return {
        ...state,
        hls:   state.hls.filter((h) => h.id !== action.v),
        selHl: state.selHl === action.v ? null : state.selHl,
      };

    case "SET_HL_KIND":
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === action.id ? { ...h, kind: action.kind } : h)),
      };

    case "UPD_HL": {
      const { id, x, y, w, hv } = action;
      return {
        ...state,
        hls: state.hls.map((h) => (h.id === id ? { ...h, x, y, w, h: hv } : h)),
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
      };
    }

    case "DEL_SENT":
      return {
        ...state,
        sents:   state.sents.filter((s) => s.id !== action.v),
        hls:     state.hls.filter((h) => h.sid !== action.v),
        selSent: state.selSent === action.v ? null : state.selSent,
      };

    case "UPD_TXT":
      return {
        ...state,
        sents: state.sents.map((s) => (s.id === action.id ? { ...s, text: action.text } : s)),
      };

    case "UPD_SENT_TIME":
      return {
        ...state,
        sents: state.sents.map((s) =>
          s.id === action.id
            ? { ...s, start_sec: action.start_sec, end_sec: action.end_sec }
            : s
        ),
      };


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
    case "SET":   return { ...state, [action.k]: action.v };
    case "RESET": return { ...INITIAL_STATE };
    default:      return state;
  }
}
