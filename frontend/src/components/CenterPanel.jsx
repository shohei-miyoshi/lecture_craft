import SlideCanvas from "./SlideCanvas.jsx";
import AudioView   from "./AudioView.jsx";
import Playbar     from "./Playbar.jsx";
import { usePlayback } from "../hooks/usePlayback.js";

/**
 * 中央パネル
 * - HLありモード（appMode==="hl"）のときのみ HL/plain 切替を表示
 * - タブ（エディタ/書き出し）は右パネル側に移動したため、ここでは持たない
 */
export default function CenterPanel({ state, dispatch, addToast, requestConfirm }) {
  usePlayback(state, dispatch);

  const isAudio = state.appMode === "audio";
  const isHl    = state.appMode === "hl";

  return (
    <main style={{ flex: 1, display: "flex", flexDirection: "column", background: "transparent", minWidth: 0, overflow: "hidden", position: "relative" }}>

      {/* ── ツールバー ── */}
      <div
        style={{
          minHeight: 46,
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 14px",
          background: "linear-gradient(180deg, rgba(19,21,26,.88), rgba(19,21,26,.74))",
          borderBottom: "1px solid rgba(255,255,255,.04)",
          flexShrink: 0,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.4px", textTransform: "uppercase", color: "var(--tm)", padding: "4px 8px", background: "rgba(255,255,255,.03)", borderLeft: "2px solid var(--ac)" }}>Preview</span>

        {isAudio ? (
          <span style={{ fontSize: 10, color: "var(--am)", background: "var(--amd)", border: "1px solid rgba(232,169,75,.3)", padding: "4px 8px", marginLeft: 4 }}>
            🔊 音声のみ
          </span>
        ) : (
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginLeft: 4, padding: "4px 8px", background: "rgba(255,255,255,.03)" }}>
            {state.slides.length ? `${state.curSl + 1} / ${state.slides.length}` : "— / —"}
          </span>
        )}

        <span style={{ marginLeft: 10, fontSize: 10, color: "var(--tm)", whiteSpace: "nowrap", padding: "4px 10px", background: "rgba(255,255,255,.025)" }}>
          <kbd style={{ background: "var(--s3)", padding: "1px 5px", borderRadius: 3, fontSize: 9 }}>Enter</kbd> 次
          {" / "}
          <kbd style={{ background: "var(--s3)", padding: "1px 5px", borderRadius: 3, fontSize: 9 }}>Backspace</kbd> 前
          {" / "}
          <kbd style={{ background: "var(--s3)", padding: "1px 5px", borderRadius: 3, fontSize: 9 }}>F5</kbd> 先頭から
          {" / "}
          <kbd style={{ background: "var(--s3)", padding: "1px 5px", borderRadius: 3, fontSize: 9 }}>Shift+F5</kbd> 現在から
        </span>

        {/* HL / 動画 切替 — HLありモード(appMode==="hl")のときだけ表示 */}
        {isHl && (
          <div style={{ marginLeft: "auto", display: "flex", gap: 3 }}>
            {[["hl", "🎬 HL表示"], ["plain", "📹 動画"]].map(([v, l]) => (
              <button key={v} onClick={() => dispatch({ type: "SET", k: "prevMode", v })} style={{
                padding: "3px 9px", border: "1px solid var(--bd2)", borderRadius: 20,
                background:  state.prevMode === v ? "var(--adim)" : "none",
                color:       state.prevMode === v ? "var(--ac)"   : "var(--ts)",
                borderColor: state.prevMode === v ? "var(--ac)"   : "var(--bd2)",
                fontSize: 10,
              }}>{l}</button>
            ))}
          </div>
        )}
      </div>

      {/* ── 描画モードヒントバー ── */}
      {!isAudio && (
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
      )}

      {/* ── メインビュー ── */}
      {isAudio ? (
        <AudioView state={state} />
      ) : (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 18,
            overflow: "hidden",
            position: "relative",
            background:
              "linear-gradient(180deg, rgba(255,255,255,.015), transparent 16%), radial-gradient(circle at 50% 20%, rgba(91,141,239,.08), transparent 36%)",
          }}
        >
          <SlideCanvas state={state} dispatch={dispatch} addToast={addToast} requestConfirm={requestConfirm} />
        </div>
      )}

      {/* ── 再生バー ── */}
      <Playbar state={state} dispatch={dispatch} hideSlideNav={isAudio} />
    </main>
  );
}
