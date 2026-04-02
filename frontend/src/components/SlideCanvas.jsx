import { useEffect, useMemo, useRef, useState } from "react";
import HlBox from "./HlBox.jsx";
import { rn } from "../utils/helpers.js";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function slideAspect(slide) {
  const width = Number(slide?.width ?? 0);
  const height = Number(slide?.height ?? 0);
  if (width > 0 && height > 0) return width / height;
  if (Number(slide?.aspect_ratio ?? 0) > 0) return Number(slide.aspect_ratio);
  return 16 / 9;
}

function clampPan(nextPan, zoom, baseSize) {
  const extraX = Math.max(0, (baseSize.width * zoom - baseSize.width) / 2);
  const extraY = Math.max(0, (baseSize.height * zoom - baseSize.height) / 2);
  return {
    x: clamp(nextPan.x, -extraX, extraX),
    y: clamp(nextPan.y, -extraY, extraY),
  };
}

export default function SlideCanvas({ state, dispatch }) {
  const viewportRef = useRef(null);
  const stageRef = useRef(null);
  const drawRef = useRef(null);
  const panRef = useRef(null);
  const [ghost, setGhost] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });

  const slide = state.slides[state.curSl];
  const curHls = state.hls.filter((h) => h.slide_idx === state.curSl);
  const actSent = state.sents.find((s) => s.start_sec <= state.curT && state.curT < s.end_sec);
  const showBB = state.appMode === "hl";
  const aspect = slideAspect(slide);

  useEffect(() => {
    if (!viewportRef.current) return undefined;
    const node = viewportRef.current;
    const update = () => {
      const rect = node.getBoundingClientRect();
      setViewportSize({ width: rect.width, height: rect.height });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const baseSize = useMemo(() => {
    const vw = viewportSize.width || 1;
    const vh = viewportSize.height || 1;
    let width = vw;
    let height = width / aspect;
    if (height > vh) {
      height = vh;
      width = height * aspect;
    }
    return {
      width: Math.max(120, width),
      height: Math.max(80, height),
    };
  }, [aspect, viewportSize.height, viewportSize.width]);

  useEffect(() => {
    setPan((prev) => clampPan(prev, zoom, baseSize));
  }, [zoom, baseSize.width, baseSize.height]);

  const setZoomSafe = (nextZoom) => {
    const clamped = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
    setZoom(clamped);
    setPan((prev) => clampPan(prev, clamped, baseSize));
  };

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  };

  const onWheel = (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.1 : -0.1;
    setZoomSafe(Number((zoom + delta).toFixed(2)));
  };

  const startPan = (e) => {
    if (state.drawMode) return;
    if (e.target.closest?.("[data-hl-interactive='1']")) return;
    e.preventDefault();
    panRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      origX: pan.x,
      origY: pan.y,
    };
  };

  useEffect(() => {
    const onMove = (e) => {
      if (!panRef.current) return;
      const dx = e.clientX - panRef.current.startX;
      const dy = e.clientY - panRef.current.startY;
      setPan(clampPan({ x: panRef.current.origX + dx, y: panRef.current.origY + dy }, zoom, baseSize));
    };
    const onUp = () => {
      panRef.current = null;
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [zoom, baseSize]);

  const onStageMouseDown = (e) => {
    if (!state.drawMode) {
      startPan(e);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    const rc = stageRef.current?.getBoundingClientRect();
    if (!rc) return;
    const sx = ((e.clientX - rc.left) / rc.width) * 100;
    const sy = ((e.clientY - rc.top) / rc.height) * 100;
    drawRef.current = { sx, sy };
    setGhost({ x: sx, y: sy, w: 0, h: 0 });
  };

  useEffect(() => {
    if (!state.drawMode) return undefined;
    const onMove = (e) => {
      if (!drawRef.current || !stageRef.current) return;
      const rc = stageRef.current.getBoundingClientRect();
      const cx = ((e.clientX - rc.left) / rc.width) * 100;
      const cy = ((e.clientY - rc.top) / rc.height) * 100;
      const { sx, sy } = drawRef.current;
      setGhost({
        x: Math.min(sx, cx),
        y: Math.min(sy, cy),
        w: Math.abs(cx - sx),
        h: Math.abs(cy - sy),
      });
    };
    const onUp = (e) => {
      if (!drawRef.current || !stageRef.current) return;
      const rc = stageRef.current.getBoundingClientRect();
      const cx = ((e.clientX - rc.left) / rc.width) * 100;
      const cy = ((e.clientY - rc.top) / rc.height) * 100;
      const { sx, sy } = drawRef.current;
      const region = {
        x: rn(Math.min(sx, cx)),
        y: rn(Math.min(sy, cy)),
        w: rn(Math.abs(cx - sx)),
        h: rn(Math.abs(cy - sy)),
      };
      drawRef.current = null;
      setGhost(null);
      dispatch({ type: "SET", k: "drawMode", v: false });
      dispatch({ type: "SET", k: "drawSentId", v: null });
      if (region.w < 2 || region.h < 2) return;
      if (state.drawSentId) {
        const kind = state.hls.find((h) => h.sid === state.drawSentId)?.kind ?? "marker";
        dispatch({ type: "APPLY_REGION", sid: state.drawSentId, region, kind });
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [state.drawMode, state.drawSentId, state.hls, dispatch]);

  const stageStyle = {
    position: "absolute",
    left: "50%",
    top: "50%",
    width: `${baseSize.width * zoom}px`,
    height: `${baseSize.height * zoom}px`,
    transform: `translate(calc(-50% + ${pan.x}px), calc(-50% + ${pan.y}px))`,
    borderRadius: 14,
    overflow: "hidden",
    boxShadow: "0 18px 45px rgba(0,0,0,.28)",
    background: slide?.color ?? "var(--s2)",
    border: "1px solid rgba(255,255,255,.08)",
    cursor: state.drawMode ? "crosshair" : zoom > 1 ? "grab" : "default",
  };

  return (
    <div
      ref={viewportRef}
      onWheel={onWheel}
      style={{
        position: "relative",
        width: "100%",
        height: "100%",
        minHeight: 280,
        border: "1px solid var(--bd)",
        borderRadius: "var(--rl)",
        overflow: "hidden",
        background: "radial-gradient(circle at top, rgba(255,255,255,.04), transparent 40%), var(--sur)",
      }}
    >
      <div style={{ position: "absolute", top: 12, left: 12, zIndex: 40, display: "flex", gap: 6 }}>
        {[
          ["-", () => setZoomSafe(zoom - 0.1)],
          ["100%", resetView],
          ["+", () => setZoomSafe(zoom + 0.1)],
        ].map(([label, onClick]) => (
          <button
            key={label}
            onClick={onClick}
            style={{
              padding: "5px 9px",
              borderRadius: 999,
              border: "1px solid var(--bd2)",
              background: "rgba(16,20,29,.74)",
              color: "var(--tp)",
              fontSize: 10,
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div style={{ position: "absolute", top: 14, right: 14, zIndex: 40, fontFamily: "var(--fm)", fontSize: 10, color: "var(--tm)" }}>
        Zoom {Math.round(zoom * 100)}%
      </div>

      <div
        ref={stageRef}
        onMouseDown={onStageMouseDown}
        style={stageStyle}
      >
        {slide?.image_base64 ? (
          <img
            src={`data:image/png;base64,${slide.image_base64}`}
            alt={slide.title ?? `slide ${state.curSl + 1}`}
            draggable={false}
            style={{ width: "100%", height: "100%", display: "block", userSelect: "none", pointerEvents: "none" }}
          />
        ) : slide ? (
          <div style={{ width: "100%", height: "100%", display: "grid", placeItems: "center", textAlign: "center", padding: 20 }}>
            <div>
              <div style={{ fontFamily: "var(--ff)", fontSize: 17, fontWeight: 700, color: "var(--tp)" }}>{slide.title}</div>
              <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginTop: 4 }}>スライド {state.curSl + 1}</div>
              <div style={{ fontSize: 9, color: "var(--tm)", opacity: 0.3, marginTop: 8 }}>※ 実際はスライド画像が表示されます</div>
            </div>
          </div>
        ) : (
          <div style={{ width: "100%", height: "100%", display: "grid", placeItems: "center", textAlign: "center", color: "var(--tm)" }}>
            <div>
              <div style={{ fontSize: 34, marginBottom: 8 }}>🎓</div>
              <p style={{ fontSize: 11, lineHeight: 1.55 }}>PDFをアップロードして<br />講義メディア生成をクリック</p>
            </div>
          </div>
        )}

        {showBB && curHls.map((hl) => (
          <HlBox
            key={hl.id}
            hl={hl}
            isSel={hl.id === state.selHl}
            isActive={!!(actSent && hl.sid === actSent.id)}
            isPlaying={state.playing}
            wrapRef={stageRef}
            dispatch={dispatch}
          />
        ))}

        {ghost && ghost.w > 0 && (
          <div
            style={{
              position: "absolute",
              left: `${ghost.x}%`,
              top: `${ghost.y}%`,
              width: `${ghost.w}%`,
              height: `${ghost.h}%`,
              border: "2px dashed var(--am)",
              background: "rgba(232,169,75,.08)",
              borderRadius: 3,
              pointerEvents: "none",
              zIndex: 30,
            }}
          />
        )}
      </div>
    </div>
  );
}
