import { useState, useEffect, useRef } from "react";
import HlBox from "./HlBox.jsx";
import { rn } from "../utils/helpers.js";

/**
 * スライドプレビューキャンバス
 * - HLボックスの表示・選択
 * - 描画モード時のドラッグ操作で新規HL領域を作成
 */
export default function SlideCanvas({ state, dispatch }) {
  const wrapRef = useRef(null);
  const drawRef = useRef(null);
  const [ghost, setGhost] = useState(null);

  const slide   = state.slides[state.curSl];
  const curHls  = state.hls.filter((h) => h.slide_idx === state.curSl);
  const actSent = state.sents.find((s) => s.start_sec <= state.curT && state.curT < s.end_sec);
  const showHl  = state.prevMode === "hl";

  // ── マウスダウン（描画開始） ──
  const onMouseDown = (e) => {
    if (!state.drawMode) return;
    e.preventDefault(); e.stopPropagation();
    const rc = e.currentTarget.getBoundingClientRect();
    const sx = (e.clientX - rc.left) / rc.width  * 100;
    const sy = (e.clientY - rc.top)  / rc.height * 100;
    drawRef.current = { sx, sy };
    setGhost({ x: sx, y: sy, w: 0, h: 0 });
  };

  // ── 描画モード中のマウス追跡 ──
  useEffect(() => {
    if (!state.drawMode) return;
    const mv = (e) => {
      if (!drawRef.current || !wrapRef.current) return;
      const rc = wrapRef.current.getBoundingClientRect();
      const cx = (e.clientX - rc.left) / rc.width  * 100;
      const cy = (e.clientY - rc.top)  / rc.height * 100;
      const { sx, sy } = drawRef.current;
      setGhost({ x: Math.min(sx, cx), y: Math.min(sy, cy), w: Math.abs(cx - sx), h: Math.abs(cy - sy) });
    };
    const up = (e) => {
      if (!drawRef.current || !wrapRef.current) return;
      const rc = wrapRef.current.getBoundingClientRect();
      const cx = (e.clientX - rc.left) / rc.width  * 100;
      const cy = (e.clientY - rc.top)  / rc.height * 100;
      const { sx, sy } = drawRef.current;
      const region = { x: rn(Math.min(sx, cx)), y: rn(Math.min(sy, cy)), w: rn(Math.abs(cx - sx)), h: rn(Math.abs(cy - sy)) };
      drawRef.current = null;
      setGhost(null);
      dispatch({ type: "SET", k: "drawMode",   v: false });
      dispatch({ type: "SET", k: "drawSentId", v: null  });
      if (region.w < 2 || region.h < 2) return;
      if (state.drawSentId) {
        const existKind = state.hls.find((h) => h.sid === state.drawSentId)?.kind ?? "marker";
        dispatch({ type: "APPLY_REGION", sid: state.drawSentId, region, kind: existKind });
      }
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
    return () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
  }, [state.drawMode, state.drawSentId, state.hls]);

  const bgStyle = slide?.image_base64
    ? { backgroundImage: `url(data:image/png;base64,${slide.image_base64})`, backgroundSize: "cover", backgroundPosition: "center" }
    : { background: slide?.color ?? "var(--s2)" };

  return (
    <div ref={wrapRef} onMouseDown={onMouseDown} style={{
      position: "relative", width: "100%", maxWidth: 660, aspectRatio: "16/9",
      background: "var(--sur)", border: "1px solid var(--bd)", borderRadius: "var(--rl)",
      overflow: "hidden", boxShadow: "0 12px 40px rgba(0,0,0,.5)",
      cursor: state.drawMode ? "crosshair" : "default",
    }}>
      <div style={{ width: "100%", height: "100%", position: "relative", display: "flex", alignItems: "center", justifyContent: "center", ...bgStyle }}>
        {/* プレースホルダー */}
        {!slide && (
          <div style={{ textAlign: "center", color: "var(--tm)", pointerEvents: "none" }}>
            <div style={{ fontSize: 34, marginBottom: 8 }}>🎓</div>
            <p style={{ fontSize: 11, lineHeight: 1.55 }}>PDFをアップロードして<br />講義メディア生成をクリック</p>
          </div>
        )}
        {slide && !slide.image_base64 && (
          <div style={{ textAlign: "center", padding: 20, zIndex: 1, pointerEvents: "none" }}>
            <div style={{ fontFamily: "var(--ff)", fontSize: 17, fontWeight: 700, color: "var(--tp)" }}>{slide.title}</div>
            <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginTop: 4 }}>スライド {state.curSl + 1}</div>
            <div style={{ fontSize: 9, color: "var(--tm)", opacity: 0.4, marginTop: 12 }}>※ 実際のシステムではスライド画像が表示されます</div>
          </div>
        )}
        {/* ハイライトボックス */}
        {showHl && curHls.map((hl) => (
          <HlBox key={hl.id} hl={hl}
            isSel={hl.id === state.selHl}
            isPlay={!!(actSent && hl.sid === actSent.id)}
            wrapRef={wrapRef}
            dispatch={dispatch} />
        ))}
        {/* 描画ゴースト */}
        {ghost && ghost.w > 0 && (
          <div style={{ position: "absolute", left: ghost.x + "%", top: ghost.y + "%", width: ghost.w + "%", height: ghost.h + "%", border: "2px dashed var(--am)", background: "rgba(232,169,75,.08)", borderRadius: 3, pointerEvents: "none", zIndex: 30 }} />
        )}
      </div>
    </div>
  );
}
