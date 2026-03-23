import SlideCanvas from "./SlideCanvas.jsx";
import { usePlayback } from "../hooks/usePlayback.js";
import { fmt } from "../utils/helpers.js";

/**
 * 中央パネル
 * - スライドプレビュー（SlideCanvas）
 * - スライドナビゲーション
 * - 再生タイムライン
 */
export default function CenterPanel({ state, dispatch }) {
  usePlayback(state.playing, state.curT, state.totDur, dispatch);

  const seek = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    dispatch({ type: "SET", k: "curT", v: ((e.clientX - r.left) / r.width) * state.totDur });
  };

  const sc  = state.slides.length;
  const pct = state.totDur > 0 ? (state.curT / state.totDur) * 100 : 0;

  // HL位置にタイムラインのティックマークを表示
  const ticks = state.hls
    .map((h) => {
      const s = state.sents.find((s) => s.id === h.sid);
      return s && state.totDur ? (s.start_sec / state.totDur) * 100 : null;
    })
    .filter((v) => v !== null);

  return (
    <main style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--bg)", minWidth: 0, overflow: "hidden" }}>

      {/* ── ツールバー ── */}
      <div style={{ height: 38, display: "flex", alignItems: "center", gap: 6, padding: "0 12px", background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <span style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.2px", textTransform: "uppercase", color: "var(--tm)" }}>Preview</span>
        <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginLeft: 4 }}>{sc ? `${state.curSl + 1} / ${sc}` : "— / —"}</span>
        {/* プレビューモード切替 */}
        <div style={{ marginLeft: "auto", display: "flex", gap: 3 }}>
          {[["hl", "HL動画"], ["plain", "動画"], ["audio", "音声"]].map(([v, l]) => (
            <button key={v} onClick={() => dispatch({ type: "SET", k: "prevMode", v })} style={{
              padding: "3px 8px", border: "1px solid var(--bd2)", borderRadius: 20,
              background:  state.prevMode === v ? "var(--adim)" : "none",
              color:       state.prevMode === v ? "var(--ac)"   : "var(--ts)",
              borderColor: state.prevMode === v ? "var(--ac)"   : "var(--bd2)",
              fontSize: 10,
            }}>{l}</button>
          ))}
        </div>
      </div>

      {/* ── 描画モードヒントバー ── */}
      <div style={{
        height: state.drawMode ? 30 : 0, overflow: "hidden",
        background: "rgba(232,169,75,.1)",
        borderBottom: state.drawMode ? "1px solid rgba(232,169,75,.22)" : "none",
        display: "flex", alignItems: "center", justifyContent: "center",
        gap: 8, fontSize: 11, color: "var(--am)",
        transition: "height .2s", flexShrink: 0,
      }}>
        ✏ ドラッグして領域を描く &nbsp;
        <kbd style={{ background: "var(--s3)", padding: "1px 5px", borderRadius: 3, fontSize: 9 }}>Esc</kbd>
        &nbsp; でキャンセル
      </div>

      {/* ── スライドキャンバス ── */}
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 14, overflow: "hidden" }}>
        <SlideCanvas state={state} dispatch={dispatch} />
      </div>

      {/* ── スライドナビ ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "7px 12px", background: "var(--sur)", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>
        <button onClick={() => dispatch({ type: "SET_SL", v: Math.max(0, state.curSl - 1) })}
          style={{ width: 26, height: 26, border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontSize: 11, display: "grid", placeItems: "center" }}>◀</button>
        <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--ts)", minWidth: 46, textAlign: "center" }}>
          {sc ? `${state.curSl + 1} / ${sc}` : "— / —"}
        </span>
        <button onClick={() => dispatch({ type: "SET_SL", v: Math.min(sc - 1, state.curSl + 1) })}
          style={{ width: 26, height: 26, border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontSize: 11, display: "grid", placeItems: "center" }}>▶</button>
      </div>

      {/* ── 再生バー ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 7, padding: "6px 12px", background: "var(--sur)", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>
        <button
          onClick={() => dispatch({ type: "SET", k: "playing", v: !state.playing })}
          style={{ width: 28, height: 28, background: "var(--ac)", border: "none", borderRadius: "50%", color: "#fff", fontSize: 11, display: "grid", placeItems: "center", flexShrink: 0 }}
        >
          {state.playing ? "⏸" : "▶"}
        </button>

        {/* タイムライン */}
        <div style={{ flex: 1, cursor: "pointer" }} onClick={seek}>
          <div style={{ height: 4, background: "var(--s2)", borderRadius: 2, position: "relative" }}>
            <div style={{ height: "100%", background: "var(--ac)", borderRadius: 2, width: pct + "%", position: "relative", transition: "width .1s linear" }}>
              <div style={{ position: "absolute", right: -5, top: -4, width: 12, height: 12, background: "var(--ac)", border: "2px solid var(--bg)", borderRadius: "50%" }} />
            </div>
            {ticks.map((p, i) => (
              <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: p + "%", width: 2, background: "rgba(91,141,239,.48)", borderRadius: 1, pointerEvents: "none" }} />
            ))}
          </div>
        </div>

        <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--ts)", minWidth: 68, textAlign: "right" }}>
          {fmt(state.curT)} / {fmt(state.totDur)}
        </div>
      </div>
    </main>
  );
}
