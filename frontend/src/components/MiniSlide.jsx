import { useMemo, useRef } from "react";
import { getContainRect } from "../utils/imageFrame.js";
import { getHighlightRegionMeta } from "../utils/highlightPresentation.js";

export default function MiniSlide({ hl, slide, dispatch, slideHighlights = [] }) {
  const ref = useRef(null);
  const regionMeta = getHighlightRegionMeta(slideHighlights, hl?.id);
  const c = regionMeta.color;
  const bg = regionMeta.bg;
  const imageSize = {
    width: Number(slide?.width ?? 1600) || 1600,
    height: Number(slide?.height ?? 900) || 900,
  };
  const aspect = imageSize.width / imageSize.height;
  const size = useMemo(() => {
    const width = 144;
    return { width, height: Math.round(width / aspect) };
  }, [aspect]);
  const imageFrame = useMemo(
    () => getContainRect(size.width, size.height, imageSize.width, imageSize.height),
    [imageSize.height, imageSize.width, size.height, size.width],
  );

  const onMoveStart = (e) => {
    if (e.target.dataset.rh) return;
    e.preventDefault();
    e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    const ox = e.clientX;
    const oy = e.clientY;
    const ox0 = hl.x;
    const oy0 = hl.y;
    const mv = (ev) => dispatch({
      type: "UPD_HL",
      id: hl.id,
      x: Math.max(0, Math.min(100 - hl.w, ox0 + ((ev.clientX - ox) / imageFrame.width) * 100)),
      y: Math.max(0, Math.min(100 - hl.h, oy0 + ((ev.clientY - oy) / imageFrame.height) * 100)),
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
    const ox = e.clientX;
    const oy = e.clientY;
    const ow = hl.w;
    const oh = hl.h;
    const mv = (ev) => dispatch({
      type: "UPD_HL",
      id: hl.id,
      x: hl.x,
      y: hl.y,
      w: Math.max(4, Math.min(100 - hl.x, ow + ((ev.clientX - ox) / imageFrame.width) * 100)),
      hv: Math.max(4, Math.min(100 - hl.y, oh + ((ev.clientY - oy) / imageFrame.height) * 100)),
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
            key={slide?.id ?? "mini-slide"}
            src={`data:image/png;base64,${slide.image_base64}`}
            alt={slide.title ?? "slide"}
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
            left: imageFrame.left + (imageFrame.width * hl.x) / 100,
            top: imageFrame.top + (imageFrame.height * hl.y) / 100,
            width: (imageFrame.width * hl.w) / 100,
            height: (imageFrame.height * hl.h) / 100,
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
      <div style={{ textAlign: "center", marginTop: 4, lineHeight: 1.4 }}>
        <div style={{ fontSize: 10, color: c, fontFamily: "var(--fm)", marginBottom: 2 }}>
          {regionMeta.label}
        </div>
        <div style={{ fontSize: 9, color: "var(--tm)" }}>
          {imageSize.width > 0 && imageSize.height > 0
            ? `${imageSize.width}×${imageSize.height}`
            : "実スライド比率で表示"}
        </div>
      </div>
    </div>
  );
}
