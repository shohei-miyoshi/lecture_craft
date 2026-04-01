import { useRef } from "react";
import { KIND_COLOR, KIND_BG } from "../utils/constants.js";
import { rn } from "../utils/helpers.js";

/**
 * 右パネルのHL設定内で使う小さなスライドサムネイル
 * ドラッグで位置移動、右下ハンドルでリサイズ
 */
export default function MiniSlide({ hl, dispatch }) {
  const ref = useRef(null);
  const c = KIND_COLOR[hl.kind];
  const bg = KIND_BG[hl.kind];

  const onMoveStart = (e) => {
    if (e.target.dataset.rh) return;
    e.preventDefault(); e.stopPropagation();
    const wr = ref.current.getBoundingClientRect();
    const ox = e.clientX, oy = e.clientY, ox0 = hl.x, oy0 = hl.y;
    const mv = (ev) =>
      dispatch({ type: "UPD_HL", id: hl.id,
        x:  Math.max(0, Math.min(100 - hl.w, ox0 + (ev.clientX - ox) / wr.width  * 100 / 0.96)),
        y:  Math.max(0, Math.min(100 - hl.h, oy0 + (ev.clientY - oy) / wr.height * 100 / 0.96)),
        w: hl.w, hv: hl.h });
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  const onResizeStart = (e) => {
    e.preventDefault(); e.stopPropagation();
    const wr = ref.current.getBoundingClientRect();
    const ox = e.clientX, oy = e.clientY, ow = hl.w, oh = hl.h;
    const mv = (ev) =>
      dispatch({ type: "UPD_HL", id: hl.id, x: hl.x, y: hl.y,
        w:  Math.max(4, Math.min(100 - hl.x, ow + (ev.clientX - ox) / wr.width  * 100 / 0.96)),
        hv: Math.max(4, Math.min(100 - hl.y, oh + (ev.clientY - oy) / wr.height * 100 / 0.96)) });
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  return (
    <div style={{ flexShrink: 0 }}>
      <div ref={ref} onMouseDown={onMoveStart} style={{
        position: "relative", width: 120, height: 68,
        background: "var(--s3)", border: "1px solid var(--bd2)", borderRadius: 4,
        overflow: "hidden", cursor: "move",
      }}>
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, color: "var(--tm)", pointerEvents: "none", fontFamily: "var(--fm)" }}>
          スライド
        </div>
        {/* HL領域 */}
        <div onMouseDown={onResizeStart} style={{
          position: "absolute",
          left: rn(hl.x * 0.96) + "%", top: rn(hl.y * 0.96) + "%",
          width: rn(hl.w * 0.96) + "%", height: rn(hl.h * 0.96) + "%",
          border: `1.5px solid ${c}`, background: bg, borderRadius: 2, cursor: "move",
        }}>
          {/* リサイズハンドル */}
          <div data-rh="1" onMouseDown={(e) => { e.stopPropagation(); onResizeStart(e); }} style={{
            position: "absolute", bottom: -4, right: -4,
            width: 8, height: 8, background: c, border: "1.5px solid var(--sur)", borderRadius: "50%", cursor: "nwse-resize",
          }} />
        </div>
      </div>
      <div style={{ fontSize: 9, color: "var(--tm)", textAlign: "center", marginTop: 4, lineHeight: 1.4 }}>
        ドラッグで移動<br />右下で拡縮
      </div>
    </div>
  );
}
