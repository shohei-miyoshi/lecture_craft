import { useRef, useState } from "react";
import { fmt } from "../utils/helpers.js";

const SPEEDS = [0.5, 1.0, 1.5, 2.0];

/**
 * 再生コントロールバー（CenterPanel下部）
 * - 再生/停止
 * - シークバー（ドラッグ対応）
 * - 残り時間 / 総時間
 * - 再生速度
 * - スライドナビ（音声モード時は非表示）
 */
export default function Playbar({ state, dispatch, hideSlideNav = false }) {
  const { curT, totDur, playing, playSpeed, slides, curSl, hls, sents } = state;
  const pct     = totDur > 0 ? (curT / totDur) * 100 : 0;
  const remain  = Math.max(0, totDur - curT);
  const sc      = slides.length;
  const isDragging = useRef(false);
  const barRef  = useRef(null);

  // HL位置のティックマーク
  const ticks = hls.map((h) => {
    const s = sents.find((s) => s.id === h.sid);
    return s && totDur ? (s.start_sec / totDur) * 100 : null;
  }).filter((v) => v !== null);

  // 文の区切りをタイムライン上にセグメントとして表示
  const sentSegs = sents.map((s) => ({
    left: totDur > 0 ? (s.start_sec / totDur) * 100 : 0,
    width: totDur > 0 ? ((s.end_sec - s.start_sec) / totDur) * 100 : 0,
  }));

  const seekTo = (clientX) => {
    if (!barRef.current) return;
    const r = barRef.current.getBoundingClientRect();
    const t = Math.max(0, Math.min(totDur, ((clientX - r.left) / r.width) * totDur));
    dispatch({ type: "SET", k: "curT", v: t });
  };

  const onMouseDown = (e) => {
    isDragging.current = true;
    seekTo(e.clientX);
    const onMove = (ev) => { if (isDragging.current) seekTo(ev.clientX); };
    const onUp   = ()   => { isDragging.current = false; document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const nextSpeed = () => {
    const idx = SPEEDS.indexOf(playSpeed);
    const next = SPEEDS[(idx + 1) % SPEEDS.length];
    dispatch({ type: "SET", k: "playSpeed", v: next });
  };

  return (
    <div style={{ background: "var(--sur)", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>

      {/* スライドナビ（音声モード以外） */}
      {!hideSlideNav && sc > 0 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "6px 12px 0" }}>
          <button
            onClick={() => dispatch({ type: "SET_SL", v: Math.max(0, curSl - 1) })}
            style={{ width: 24, height: 24, border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontSize: 10, display: "grid", placeItems: "center" }}
          >◀</button>
          <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--ts)", minWidth: 46, textAlign: "center" }}>
            {sc ? `${curSl + 1} / ${sc}` : "— / —"}
          </span>
          <button
            onClick={() => dispatch({ type: "SET_SL", v: Math.min(sc - 1, curSl + 1) })}
            style={{ width: 24, height: 24, border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontSize: 10, display: "grid", placeItems: "center" }}
          >▶</button>
        </div>
      )}

      {/* 再生コントロール */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px" }}>

        {/* 再生/停止 */}
        <button
          onClick={() => dispatch({ type: "SET", k: "playing", v: !playing })}
          style={{ width: 32, height: 32, background: "var(--ac)", border: "none", borderRadius: "50%", color: "#fff", fontSize: 12, display: "grid", placeItems: "center", flexShrink: 0 }}
        >
          {playing ? "⏸" : "▶"}
        </button>

        {/* タイムライン */}
        <div style={{ flex: 1 }}>
          {/* 時刻表示 */}
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--fm)", fontSize: 9, color: "var(--ts)", marginBottom: 4 }}>
            <span>{fmt(curT)}</span>
            <span style={{ color: "var(--tm)" }}>-{fmt(remain)}</span>
            <span>{fmt(totDur)}</span>
          </div>

          {/* シークバー（ドラッグ対応） */}
          <div ref={barRef} onMouseDown={onMouseDown} style={{ height: 8, background: "var(--s2)", borderRadius: 4, position: "relative", cursor: "pointer" }}>

            {/* 文セグメント背景 */}
            {sentSegs.map((seg, i) => (
              <div key={i} style={{
                position: "absolute", top: 1, bottom: 1,
                left: seg.left + "%", width: seg.width + "%",
                background: "rgba(255,255,255,.04)",
                borderRight: "1px solid rgba(255,255,255,.06)",
                pointerEvents: "none",
              }} />
            ))}

            {/* 進捗 */}
            <div style={{ height: "100%", background: "var(--ac)", borderRadius: 4, width: pct + "%", position: "relative" }}>
              {/* シークヘッド */}
              <div style={{ position: "absolute", right: -7, top: "50%", transform: "translateY(-50%)", width: 14, height: 14, background: "var(--ac)", border: "2px solid var(--bg)", borderRadius: "50%", boxShadow: "0 0 0 2px rgba(91,141,239,.3)" }} />
            </div>

            {/* HL ティック */}
            {ticks.map((p, i) => (
              <div key={i} style={{ position: "absolute", top: -2, bottom: -2, left: p + "%", width: 2, background: "var(--ac)", opacity: 0.6, borderRadius: 1, pointerEvents: "none" }} />
            ))}
          </div>
        </div>

        {/* 再生速度 */}
        <button
          onClick={nextSpeed}
          title="再生速度を変更"
          style={{ padding: "3px 7px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontFamily: "var(--fm)", fontSize: 10, flexShrink: 0, minWidth: 36 }}
        >
          {playSpeed}x
        </button>
      </div>
    </div>
  );
}
