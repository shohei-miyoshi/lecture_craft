import { getHighlightRegionMeta } from "../utils/highlightPresentation.js";

/**
 * HlBox — スライドキャンバス上のハイライトボックス
 *
 * 再生中の挙動：
 *   - 全BBは常時表示（薄く残す）
 *   - アクティブ（再生中の文に紐づく）BBは強調パルスアニメーション
 *   - 再生中はドラッグ/リサイズ無効
 *
 * 停止中の挙動：
 *   - 選択中のBBは8方向リサイズハンドル + 削除ボタンを表示
 */

const HANDLE_POS = {
  nw:{top:0,left:0,cursor:"nw-resize",transform:"translate(-50%,-50%)"},
  n:{top:0,left:"50%",cursor:"n-resize",transform:"translate(-50%,-50%)"},
  ne:{top:0,right:0,cursor:"ne-resize",transform:"translate(50%,-50%)"},
  w:{top:"50%",left:0,cursor:"w-resize",transform:"translate(-50%,-50%)"},
  e:{top:"50%",right:0,cursor:"e-resize",transform:"translate(50%,-50%)"},
  sw:{bottom:0,left:0,cursor:"sw-resize",transform:"translate(-50%,50%)"},
  s:{bottom:0,left:"50%",cursor:"s-resize",transform:"translate(-50%,50%)"},
  se:{bottom:0,right:0,cursor:"se-resize",transform:"translate(50%,50%)"},
};

// 種別ごとのパルスアニメーション用CSS（index.cssに追加）
export const HL_PULSE_CSS = `
@keyframes hlpulse_ac{0%{box-shadow:0 0 0 0 rgba(91,141,239,.6)}70%{box-shadow:0 0 0 8px rgba(91,141,239,0)}100%{box-shadow:0 0 0 0 rgba(91,141,239,0)}}
`;
const PULSE_ANIM = "hlpulse_ac";

export default function HlBox({ hl, isSel, isActive, isPlaying, frame, dispatch, requestConfirm, slideHighlights = [] }) {
  const regionMeta = getHighlightRegionMeta(slideHighlights, hl?.id);
  const c   = regionMeta.color;
  const bg  = isActive ? regionMeta.bgStrong : regionMeta.bg;
  const leftPx = frame.left + (frame.width * hl.x) / 100;
  const topPx = frame.top + (frame.height * hl.y) / 100;
  const widthPx = (frame.width * hl.w) / 100;
  const heightPx = (frame.height * hl.h) / 100;

  // 再生中：アクティブBB=不透明、非アクティブBB=薄く
  const opacity  = isPlaying ? (isActive ? 1 : 0.28) : 1;
  const animation = isActive && isPlaying
    ? `${PULSE_ANIM} 1.4s ease-in-out infinite`
    : "none";
  const borderWidth = isActive && isPlaying ? 3 : 2;

  // ── 移動 ──
  const onMoveStart = (e) => {
    if (isPlaying || e.target.dataset.rh) return;
    e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "SEL_HL", v: hl.id });
    const ox = e.clientX, oy = e.clientY, ox0 = hl.x, oy0 = hl.y;
    const mv = (ev) => dispatch({ type: "UPD_HL", id: hl.id,
      x: Math.max(0, Math.min(100 - hl.w, ox0 + (ev.clientX - ox) / frame.width  * 100)),
      y: Math.max(0, Math.min(100 - hl.h, oy0 + (ev.clientY - oy) / frame.height * 100)),
      w: hl.w, hv: hl.h });
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  // ── リサイズ ──
  const onResizeStart = (e, dir) => {
    if (isPlaying) return;
    e.preventDefault(); e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    const ox = e.clientX, oy = e.clientY;
    const orig = { x: hl.x, y: hl.y, w: hl.w, h: hl.h };
    const mv = (ev) => {
      const dx = (ev.clientX - ox) / frame.width  * 100;
      const dy = (ev.clientY - oy) / frame.height * 100;
      let { x, y, w, h } = orig;
      if (dir.includes("e"))  w  = Math.max(4, orig.w + dx);
      if (dir.includes("s"))  h  = Math.max(4, orig.h + dy);
      if (dir.includes("w")) { x = Math.min(orig.x + orig.w - 4, orig.x + dx); w = Math.max(4, orig.w - dx); }
      if (dir.includes("n")) { y = Math.min(orig.y + orig.h - 4, orig.y + dy); h = Math.max(4, orig.h - dy); }
      if (x < 0) { w += x; x = 0; } if (y < 0) { h += y; y = 0; }
      if (x + w > 100) w = 100 - x; if (y + h > 100) h = 100 - y;
      dispatch({ type: "UPD_HL", id: hl.id, x, y, w, hv: h });
    };
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  return (
    <div data-hl-interactive="1" onMouseDown={onMoveStart} style={{
      position: "absolute",
      left: leftPx,
      top: topPx,
      width: widthPx,
      height: heightPx,
      border: `${borderWidth}px solid ${c}`,
      background: bg,
      borderRadius: 3,
      cursor: isPlaying ? "default" : "grab",
      zIndex: isActive ? 10 : 5,
      opacity,
      transition: "opacity .4s",
      animation,
    }}>
      {/* ラベル（アクティブか選択時のみ） */}
      {(isActive || isSel) && (
        <div style={{ position: "absolute", top: -17, left: 0, background: c, color: "#fff", fontFamily: "var(--fm)", fontSize: 8, padding: "1px 5px", borderRadius: 2, pointerEvents: "none", whiteSpace: "nowrap" }}>
          {regionMeta.label}
        </div>
      )}
      {/* 削除ボタン（停止中・選択時のみ） */}
      {isSel && !isPlaying && (
        <div data-hl-interactive="1" onClick={(e) => {
          e.stopPropagation();
          const run = () => {
            dispatch({ type: "PUSH_HISTORY" });
            dispatch({ type: "RM_HL_ID", v: hl.id });
          };
          if ((hl.sentence_ids ?? []).length > 1) {
            requestConfirm?.({
              title: "共有ハイライト枠を削除",
              message: `この枠は ${(hl.sentence_ids ?? []).length} 個の台本と対応しています。\n削除すると関連する対応も一緒に消えますが、大丈夫ですか？`,
              confirmLabel: "削除する",
              onConfirm: run,
            });
            return;
          }
          run();
        }}
          style={{ position: "absolute", top: -17, right: 0, width: 16, height: 16, background: "var(--rdd)", border: "1px solid var(--rd)", borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, color: "var(--rd)", cursor: "pointer" }}>
          ×
        </div>
      )}
      {/* 8方向リサイズハンドル（停止中・選択時のみ） */}
      {isSel && !isPlaying && Object.entries(HANDLE_POS).map(([dir, pos]) => (
        <div key={dir} data-hl-interactive="1" data-rh={dir} onMouseDown={(e) => onResizeStart(e, dir)}
          style={{ position: "absolute", width: 10, height: 10, background: "var(--sur)", border: `2px solid ${c}`, borderRadius: "50%", zIndex: 20, ...pos }} />
      ))}
    </div>
  );
}
