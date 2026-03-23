import SlideCanvas from "./SlideCanvas.jsx";
import AudioView  from "./AudioView.jsx";
import Playbar    from "./Playbar.jsx";
import { usePlayback } from "../hooks/usePlayback.js";

/**
 * 中央パネル
 * - appMode === "audio" のとき AudioView を表示
 * - それ以外は SlideCanvas を表示
 * - Playbar（シーク・再生速度・スライドナビ）を共通で下部に配置
 */
export default function CenterPanel({ state, dispatch }) {
  // usePlayback に state 丸ごと渡す（自動スライド切替含む）
  usePlayback(state, dispatch);

  const isAudio = state.appMode === "audio";

  return (
    <main style={{ flex: 1, display: "flex", flexDirection: "column", background: "var(--bg)", minWidth: 0, overflow: "hidden" }}>

      {/* ── ツールバー ── */}
      <div style={{ height: 38, display: "flex", alignItems: "center", gap: 6, padding: "0 12px", background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <span style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.2px", textTransform: "uppercase", color: "var(--tm)" }}>Preview</span>

        {/* 音声モード表示 */}
        {isAudio ? (
          <span style={{ fontSize: 10, color: "var(--am)", background: "var(--amd)", border: "1px solid rgba(232,169,75,.3)", padding: "2px 8px", borderRadius: 20, marginLeft: 4 }}>
            🔊 音声のみ
          </span>
        ) : (
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginLeft: 4 }}>
            {state.slides.length ? `${state.curSl + 1} / ${state.slides.length}` : "— / —"}
          </span>
        )}

        {/* プレビューモード切替（動画モード時のみ） */}
        {!isAudio && (
          <div style={{ marginLeft: "auto", display: "flex", gap: 3 }}>
            {[["hl", "HL動画"], ["plain", "動画"]].map(([v, l]) => (
              <button key={v} onClick={() => dispatch({ type: "SET", k: "prevMode", v })} style={{
                padding: "3px 8px", border: "1px solid var(--bd2)", borderRadius: 20,
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
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 14, overflow: "hidden" }}>
          <SlideCanvas state={state} dispatch={dispatch} />
        </div>
      )}

      {/* ── 再生バー ── */}
      <Playbar state={state} dispatch={dispatch} hideSlideNav={isAudio} />
    </main>
  );
}
