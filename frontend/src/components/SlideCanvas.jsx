import { useEffect, useMemo, useRef, useState } from "react";
import HlBox from "./HlBox.jsx";
import { rn } from "../utils/helpers.js";
import { findHighlightForSentence } from "../utils/highlights.js";
import { getContainRect } from "../utils/imageFrame.js";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

const CHROME_INSETS = { top: 46, right: 18, bottom: 26, left: 18 };

function clampPan(nextPan, zoom, baseSize) {
  const extraX = Math.max(0, (baseSize.width * zoom - baseSize.width) / 2);
  const extraY = Math.max(0, (baseSize.height * zoom - baseSize.height) / 2);
  return {
    x: clamp(nextPan.x, -extraX, extraX),
    y: clamp(nextPan.y, -extraY, extraY),
  };
}

export default function SlideCanvas({ state, dispatch, addToast, requestConfirm }) {
  const viewportRef = useRef(null);
  const stageRef = useRef(null);
  const drawRef = useRef(null);
  const panRef = useRef(null);
  const wheelSwitchRef = useRef(0);
  const [ghost, setGhost] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });

  const slide = state.slides[state.curSl];
  const curHls = state.hls.filter((h) => h.slide_idx === state.curSl);
  const actSent = state.sents.find((s) => s.start_sec <= state.curT && state.curT < s.end_sec);
  const showBB = state.appMode === "hl";
  const previewFrame = state.previewFrame ?? { width: 1600, height: 900, aspect_ratio: 16 / 9 };
  const imageSize = {
    width: Number(previewFrame.width ?? slide?.width ?? 1600) || 1600,
    height: Number(previewFrame.height ?? slide?.height ?? 900) || 900,
  };
  const aspect = Number(previewFrame.aspect_ratio ?? 0) > 0
    ? Number(previewFrame.aspect_ratio)
    : imageSize.width / imageSize.height;
  const imageReady = Boolean(slide);

  useEffect(() => {
    resetView();
  }, [state.curSl]);

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
    const vw = Math.max(1, (viewportSize.width || 1) - CHROME_INSETS.left - CHROME_INSETS.right);
    const vh = Math.max(1, (viewportSize.height || 1) - CHROME_INSETS.top - CHROME_INSETS.bottom);
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

  const stageArea = useMemo(() => ({
    left: CHROME_INSETS.left,
    top: CHROME_INSETS.top,
    width: Math.max(1, (viewportSize.width || 1) - CHROME_INSETS.left - CHROME_INSETS.right),
    height: Math.max(1, (viewportSize.height || 1) - CHROME_INSETS.top - CHROME_INSETS.bottom),
  }), [viewportSize.height, viewportSize.width]);

  const stageSize = useMemo(() => ({
    width: baseSize.width * zoom,
    height: baseSize.height * zoom,
  }), [baseSize.height, baseSize.width, zoom]);

  const imageFrame = useMemo(
    () => getContainRect(stageSize.width, stageSize.height, imageSize.width, imageSize.height),
    [imageSize.height, imageSize.width, stageSize.height, stageSize.width],
  );

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
    if (e.ctrlKey || e.metaKey) {
      const delta = e.deltaY < 0 ? 0.1 : -0.1;
      setZoomSafe(Number((zoom + delta).toFixed(2)));
      return;
    }
    const now = Date.now();
    if (now - wheelSwitchRef.current < 180) return;
    wheelSwitchRef.current = now;
    const nextSlide = e.deltaY > 0
      ? Math.min(state.slides.length - 1, state.curSl + 1)
      : Math.max(0, state.curSl - 1);
    if (nextSlide !== state.curSl) {
      dispatch({ type: "SET_SL", v: nextSlide });
    }
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

  const getImagePercentPoint = (clientX, clientY) => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect || imageFrame.width <= 0 || imageFrame.height <= 0) return null;
    const imageLeft = rect.left + imageFrame.left;
    const imageTop = rect.top + imageFrame.top;
    return {
      x: clamp(((clientX - imageLeft) / imageFrame.width) * 100, 0, 100),
      y: clamp(((clientY - imageTop) / imageFrame.height) * 100, 0, 100),
    };
  };

  const onStageMouseDown = (e) => {
    if (!state.drawMode) {
      startPan(e);
      return;
    }
    e.preventDefault();
    e.stopPropagation();
    const point = getImagePercentPoint(e.clientX, e.clientY);
    if (!point) return;
    drawRef.current = { sx: point.x, sy: point.y };
    setGhost({ x: point.x, y: point.y, w: 0, h: 0 });
  };

  const onStageDoubleClick = (e) => {
    if (state.drawMode || !showBB) return;
    const selectedSentence = state.sents.find((s) => s.id === state.selSent);
    const point = getImagePercentPoint(e.clientX, e.clientY);
    if (!point) return;
    const region = {
      x: rn(clamp(point.x - 8, 0, 84)),
      y: rn(clamp(point.y - 6, 0, 88)),
      w: 16,
      h: 12,
    };
    const sid = selectedSentence && selectedSentence.slide_idx === state.curSl ? selectedSentence.id : null;
    const kind = sid ? findHighlightForSentence(state.hls, sid)?.kind ?? "marker" : "marker";
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "ADD_HL_BOX", sid, slide_idx: state.curSl, region, kind });
    addToast?.("ok", sid ? "選択中の文にハイライト枠を追加しました" : "未対応のハイライト枠を追加しました");
  };

  useEffect(() => {
    if (!state.drawMode) return undefined;
    const onMove = (e) => {
      if (!drawRef.current) return;
      const point = getImagePercentPoint(e.clientX, e.clientY);
      if (!point) return;
      const { sx, sy } = drawRef.current;
      setGhost({
        x: Math.min(sx, point.x),
        y: Math.min(sy, point.y),
        w: Math.abs(point.x - sx),
        h: Math.abs(point.y - sy),
      });
    };
    const onUp = (e) => {
      if (!drawRef.current) return;
      const point = getImagePercentPoint(e.clientX, e.clientY);
      if (!point) return;
      const { sx, sy } = drawRef.current;
      const region = {
        x: rn(Math.min(sx, point.x)),
        y: rn(Math.min(sy, point.y)),
        w: rn(Math.abs(point.x - sx)),
        h: rn(Math.abs(point.y - sy)),
      };
      drawRef.current = null;
      setGhost(null);
      dispatch({ type: "SET", k: "drawMode", v: false });
      dispatch({ type: "SET", k: "drawSentId", v: null });
      if (region.w < 2 || region.h < 2) return;
      if (state.drawSentId) {
        const kind = findHighlightForSentence(state.hls, state.drawSentId)?.kind ?? "marker";
        dispatch({ type: "ADD_HL_BOX", sid: state.drawSentId, slide_idx: state.curSl, region, kind });
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [state.drawMode, state.drawSentId, state.hls, dispatch, imageFrame.height, imageFrame.left, imageFrame.top, imageFrame.width]);

  const stageStyle = {
    position: "absolute",
    left: stageArea.left + stageArea.width / 2,
    top: stageArea.top + stageArea.height / 2,
    width: `${stageSize.width}px`,
    height: `${stageSize.height}px`,
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
        {imageSize.width > 0 && imageSize.height > 0
          ? `${imageSize.width}×${imageSize.height} | `
          : ""}
        拡大率 {Math.round(zoom * 100)}%
      </div>

      <div
        ref={stageRef}
        onMouseDown={onStageMouseDown}
        onDoubleClick={onStageDoubleClick}
        style={stageStyle}
      >
        {slide?.image_base64 ? (
          <img
            key={slide?.id ?? `slide-${state.curSl}`}
            src={`data:image/png;base64,${slide.image_base64}`}
            alt={slide.title ?? `slide ${state.curSl + 1}`}
            draggable={false}
            style={{ width: "100%", height: "100%", display: "block", objectFit: "contain", background: "#fff", userSelect: "none", pointerEvents: "none" }}
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

        {showBB && imageReady && curHls.map((hl) => (
          <HlBox
            key={hl.id}
            hl={hl}
            isSel={hl.id === state.selHl}
            isActive={!!(actSent && (hl.sentence_ids ?? []).includes(actSent.id))}
            isPlaying={state.playing}
            frame={imageFrame}
            dispatch={dispatch}
            requestConfirm={requestConfirm}
          />
        ))}

        {ghost && ghost.w > 0 && (
          <div
            style={{
              position: "absolute",
              left: imageFrame.left + (imageFrame.width * ghost.x) / 100,
              top: imageFrame.top + (imageFrame.height * ghost.y) / 100,
              width: (imageFrame.width * ghost.w) / 100,
              height: (imageFrame.height * ghost.h) / 100,
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
