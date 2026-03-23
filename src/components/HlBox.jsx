import { KIND_COLOR, KIND_BG, KIND_BG_SEL, KIND_LABEL } from "../utils/constants.js";

const HANDLE_POS = {
  nw: { top: 0,     left: 0,     cursor: "nw-resize", transform: "translate(-50%,-50%)" },
  n:  { top: 0,     left: "50%", cursor: "n-resize",  transform: "translate(-50%,-50%)" },
  ne: { top: 0,     right: 0,    cursor: "ne-resize", transform: "translate(50%,-50%)"  },
  w:  { top: "50%", left: 0,     cursor: "w-resize",  transform: "translate(-50%,-50%)" },
  e:  { top: "50%", right: 0,    cursor: "e-resize",  transform: "translate(50%,-50%)"  },
  sw: { bottom: 0,  left: 0,     cursor: "sw-resize", transform: "translate(-50%,50%)"  },
  s:  { bottom: 0,  left: "50%", cursor: "s-resize",  transform: "translate(-50%,50%)"  },
  se: { bottom: 0,  right: 0,    cursor: "se-resize", transform: "translate(50%,50%)"   },
};

/**
 * スライドキャンバス上のハイライトボックス
 *
 * isPlay=true のとき:
 *   - バウンディングボックス（枠）は常に表示
 *   - 内部の塗りつぶしのみ pulse アニメーション
 *   → 「BB を残したままハイライトを再生する」仕様
 */
export default function HlBox({ hl, isSel, isPlay, wrapRef, dispatch }) {
  const c  = KIND_COLOR[hl.kind];
  const bg = isSel ? KIND_BG_SEL[hl.kind] : KIND_BG[hl.kind];

  // ── 移動 ──
  const onMoveStart = (e) => {
    if (e.target.dataset.rh) return;
    e.stopPropagation();
    dispatch({ type: "SEL_HL", v: hl.id });
    const wr = wrapRef.current.getBoundingClientRect();
    const ox = e.clientX, oy = e.clientY, ox0 = hl.x, oy0 = hl.y;
    const mv = (ev) =>
      dispatch({ type: "UPD_HL", id: hl.id,
        x:  Math.max(0, Math.min(100 - hl.w, ox0 + (ev.clientX - ox) / wr.width  * 100)),
        y:  Math.max(0, Math.min(100 - hl.h, oy0 + (ev.clientY - oy) / wr.height * 100)),
        w:  hl.w, hv: hl.h });
    const up = () => {
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  // ── リサイズ（8方向）──
  const onResizeStart = (e, dir) => {
    e.preventDefault(); e.stopPropagation();
    const wr = wrapRef.current.getBoundingClientRect();
    const ox = e.clientX, oy = e.clientY;
    const orig = { x: hl.x, y: hl.y, w: hl.w, h: hl.h };
    const mv = (ev) => {
      const dx = (ev.clientX - ox) / wr.width  * 100;
      const dy = (ev.clientY - oy) / wr.height * 100;
      let { x, y, w, h } = orig;
      if (dir.includes("e"))  w  = Math.max(4, orig.w + dx);
      if (dir.includes("s"))  h  = Math.max(4, orig.h + dy);
      if (dir.includes("w")) { x = Math.min(orig.x + orig.w - 4, orig.x + dx); w = Math.max(4, orig.w - dx); }
      if (dir.includes("n")) { y = Math.min(orig.y + orig.h - 4, orig.y + dy); h = Math.max(4, orig.h - dy); }
      if (x < 0) { w += x; x = 0; } if (y < 0) { h += y; y = 0; }
      if (x + w > 100) w = 100 - x; if (y + h > 100) h = 100 - y;
      dispatch({ type: "UPD_HL", id: hl.id, x, y, w, hv: h });
    };
    const up = () => {
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  return (
    <div onMouseDown={onMoveStart} style={{
      position: "absolute",
      left: hl.x + "%", top: hl.y + "%", width: hl.w + "%", height: hl.h + "%",
      // 枠は常に表示（isPlay でも消えない）
      border: `2px solid ${c}`,
      borderRadius: 3,
      cursor: "grab",
      zIndex: isSel ? 10 : 5,
      // 選択中は強調枠
      boxShadow: isSel ? `0 0 0 2px ${c}55` : "none",
      // 再生中のみ overflow:hidden で内側だけアニメーション
      overflow: "hidden",
    }}>

      {/* 塗りつぶし層 — 再生中は pulse アニメーション、それ以外は通常の半透明 */}
      <div style={{
        position: "absolute", inset: 0,
        background: bg,
        animation: isPlay ? "lc-hl-pulse 0.9s ease-in-out infinite alternate" : "none",
      }} />

      {/* 再生中インジケーター（左上の小さいドット） */}
      {isPlay && (
        <div style={{
          position: "absolute", top: 4, left: 4,
          width: 6, height: 6,
          background: c,
          borderRadius: "50%",
          animation: "lc-dot-blink 0.7s ease-in-out infinite alternate",
          boxShadow: `0 0 4px ${c}`,
        }} />
      )}

      {/* ラベル */}
      <div style={{
        position: "absolute", top: -16, left: 0,
        background: c, color: "#fff",
        fontFamily: "var(--fm)", fontSize: 8, padding: "1px 4px", borderRadius: 2,
        pointerEvents: "none", whiteSpace: "nowrap",
        // 再生中はラベルも点滅
        animation: isPlay ? "lc-dot-blink 0.7s ease-in-out infinite alternate" : "none",
      }}>
        {isPlay ? "▶ " : ""}{KIND_LABEL[hl.kind]}
      </div>

      {/* 削除ボタン（選択時のみ） */}
      {isSel && (
        <div onClick={(e) => { e.stopPropagation(); dispatch({ type: "RM_HL_ID", v: hl.id }); }}
          style={{
            position: "absolute", top: -16, right: 0,
            width: 16, height: 16,
            background: "var(--rdd)", border: "1px solid var(--rd)", borderRadius: 3,
            cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 9, color: "var(--rd)",
          }}>
          ×
        </div>
      )}

      {/* 8方向リサイズハンドル（選択時のみ） */}
      {isSel && Object.entries(HANDLE_POS).map(([dir, pos]) => (
        <div key={dir} data-rh={dir} onMouseDown={(e) => onResizeStart(e, dir)}
          style={{
            position: "absolute", width: 10, height: 10,
            background: "var(--sur)", border: `2px solid ${c}`, borderRadius: "50%",
            zIndex: 20, ...pos,
          }} />
      ))}
    </div>
  );
}
