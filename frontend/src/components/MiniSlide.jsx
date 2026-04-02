import { useMemo, useRef, useState } from "react";
import { KIND_BG, KIND_COLOR } from "../utils/constants.js";

function slideAspect(slide) {
  const width = Number(slide?.width ?? 0);
  const height = Number(slide?.height ?? 0);
  if (width > 0 && height > 0) return width / height;
  if (Number(slide?.aspect_ratio ?? 0) > 0) return Number(slide.aspect_ratio);
  return 16 / 9;
}

export default function MiniSlide({ hl, slide, dispatch }) {
  const ref = useRef(null);
  const [naturalSize, setNaturalSize] = useState({ width: 0, height: 0 });
  const c = KIND_COLOR[hl.kind];
  const bg = KIND_BG[hl.kind];
  const aspect = naturalSize.width > 0 && naturalSize.height > 0
    ? naturalSize.width / naturalSize.height
    : slideAspect(slide);
  const size = useMemo(() => {
    const width = 144;
    return { width, height: Math.round(width / aspect) };
  }, [aspect]);

  const onMoveStart = (e) => {
    if (e.target.dataset.rh) return;
    e.preventDefault();
    e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    const wr = ref.current.getBoundingClientRect();
    const ox = e.clientX;
    const oy = e.clientY;
    const ox0 = hl.x;
    const oy0 = hl.y;
    const mv = (ev) => dispatch({
      type: "UPD_HL",
      id: hl.id,
      x: Math.max(0, Math.min(100 - hl.w, ox0 + ((ev.clientX - ox) / wr.width) * 100)),
      y: Math.max(0, Math.min(100 - hl.h, oy0 + ((ev.clientY - oy) / wr.height) * 100)),
      w: hl.w,
      hv: hl.h,
    });
    const up = () => {
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  const onResizeStart = (e) => {
    e.preventDefault();
    e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    const wr = ref.current.getBoundingClientRect();
    const ox = e.clientX;
    const oy = e.clientY;
    const ow = hl.w;
    const oh = hl.h;
    const mv = (ev) => dispatch({
      type: "UPD_HL",
      id: hl.id,
      x: hl.x,
      y: hl.y,
      w: Math.max(4, Math.min(100 - hl.x, ow + ((ev.clientX - ox) / wr.width) * 100)),
      hv: Math.max(4, Math.min(100 - hl.y, oh + ((ev.clientY - oy) / wr.height) * 100)),
    });
    const up = () => {
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  };

  return (
    <div style={{ flexShrink: 0 }}>
      <div
        ref={ref}
        onMouseDown={onMoveStart}
        style={{
          position: "relative",
          width: size.width,
          height: size.height,
          background: "#fff",
          border: "1px solid var(--bd2)",
          borderRadius: 4,
          overflow: "hidden",
          cursor: "move",
        }}
      >
        {slide?.image_base64 ? (
          <img
            src={`data:image/png;base64,${slide.image_base64}`}
            alt={slide.title ?? "slide"}
            onLoad={(e) => {
              if (e.currentTarget.naturalWidth > 0 && e.currentTarget.naturalHeight > 0) {
                setNaturalSize({ width: e.currentTarget.naturalWidth, height: e.currentTarget.naturalHeight });
              }
            }}
            style={{ width: "100%", height: "100%", display: "block", objectFit: "contain", pointerEvents: "none" }}
          />
        ) : (
          <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", fontSize: 10, color: "var(--tm)", pointerEvents: "none" }}>
            スライド
          </div>
        )}

        <div
          onMouseDown={onResizeStart}
          style={{
            position: "absolute",
            left: `${hl.x}%`,
            top: `${hl.y}%`,
            width: `${hl.w}%`,
            height: `${hl.h}%`,
            border: `1.5px solid ${c}`,
            background: bg,
            borderRadius: 2,
            cursor: "move",
          }}
        >
          <div
            data-rh="1"
            onMouseDown={(e) => { e.stopPropagation(); onResizeStart(e); }}
            style={{
              position: "absolute",
              bottom: -4,
              right: -4,
              width: 8,
              height: 8,
              background: c,
              border: "1.5px solid var(--sur)",
              borderRadius: "50%",
              cursor: "nwse-resize",
            }}
          />
        </div>
      </div>
      <div style={{ fontSize: 9, color: "var(--tm)", textAlign: "center", marginTop: 4, lineHeight: 1.4 }}>
        {naturalSize.width > 0 && naturalSize.height > 0
          ? `${naturalSize.width}×${naturalSize.height}`
          : "実スライド比率で表示"}
      </div>
    </div>
  );
}
