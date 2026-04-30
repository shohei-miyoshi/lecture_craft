import { getHighlightRegionMeta } from "../utils/highlightPresentation.js";
import {
  easeInOutSine,
  getArrowAutoSide,
  getHighlightMotionDurationSec,
  getHighlightVisualSpec,
  rgba,
  withAlpha,
} from "../utils/highlightOverlay.js";

const HANDLE_POS = {
  nw: { top: 0, left: 0, cursor: "nw-resize", transform: "translate(-50%,-50%)" },
  n: { top: 0, left: "50%", cursor: "n-resize", transform: "translate(-50%,-50%)" },
  ne: { top: 0, right: 0, cursor: "ne-resize", transform: "translate(50%,-50%)" },
  w: { top: "50%", left: 0, cursor: "w-resize", transform: "translate(-50%,-50%)" },
  e: { top: "50%", right: 0, cursor: "e-resize", transform: "translate(50%,-50%)" },
  sw: { bottom: 0, left: 0, cursor: "sw-resize", transform: "translate(-50%,50%)" },
  s: { bottom: 0, left: "50%", cursor: "s-resize", transform: "translate(-50%,50%)" },
  se: { bottom: 0, right: 0, cursor: "se-resize", transform: "translate(50%,50%)" },
};

export const HL_PULSE_CSS = `
@keyframes hlpulse_ac{0%{box-shadow:0 0 0 0 rgba(91,141,239,.6)}70%{box-shadow:0 0 0 8px rgba(91,141,239,0)}100%{box-shadow:0 0 0 0 rgba(91,141,239,0)}}
`;
const PULSE_ANIM = "hlpulse_ac";

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function scalePx(value, renderScale, floor = 0.5) {
  return Math.max(floor, (Number(value) || 0) * Math.max(Number(renderScale) || 1, 0.01));
}

function buildMotionProgress({ kind, isPlaying, isActive, activeElapsedSec, activeSentenceDurationSec }) {
  if (!isPlaying) return 1;
  if (!isActive) return 0;
  const defaultDuration = getHighlightMotionDurationSec(kind);
  const sentenceDuration = Math.max(Number(activeSentenceDurationSec) || 0, 0.05);
  const motionDuration = Math.max(0.05, Math.min(defaultDuration, sentenceDuration));
  const rawProgress = clamp((Number(activeElapsedSec) || 0) / motionDuration, 0, 1);
  return easeInOutSine(rawProgress);
}

function MarkerMaterial({ widthPx, heightPx, renderScale, progress, visible, isPlaying }) {
  const spec = getHighlightVisualSpec("marker");
  const innerLeft = Math.min(widthPx * 0.24, scalePx(spec.blockHMarginPx, renderScale, 2));
  const innerTop = Math.min(heightPx * 0.24, scalePx(spec.blockVMarginPx, renderScale, 2));
  const innerWidth = Math.max(2, widthPx - innerLeft * 2);
  const innerHeight = Math.max(2, heightPx - innerTop * 2);
  const revealWidth = Math.max(0, innerWidth * progress);
  const radius = Math.min(innerHeight / 2, scalePx(spec.cornerRadiusPx, renderScale, 3));
  const blurPx = scalePx(spec.featherRadiusPx, renderScale, 0.65);
  const fillAlpha = visible ? spec.alpha : 0;
  const glowAlpha = visible ? 0.22 : 0;

  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        opacity: visible ? 1 : 0,
        transition: isPlaying ? "opacity .08s linear" : "opacity .16s ease",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: innerLeft,
          top: innerTop,
          width: revealWidth,
          height: innerHeight,
          borderRadius: radius,
          background: rgba(spec.rgb, glowAlpha),
          filter: `blur(${blurPx * 2}px)`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: innerLeft,
          top: innerTop,
          width: revealWidth,
          height: innerHeight,
          borderRadius: radius,
          background: `linear-gradient(180deg, ${rgba(spec.rgb, fillAlpha)} 0%, ${rgba(spec.rgb, fillAlpha * 0.78)} 100%)`,
          boxShadow: `0 0 ${Math.max(2, blurPx * 4)}px ${rgba(spec.rgb, 0.16)}`,
        }}
      />
    </div>
  );
}

function LaserMaterial({ widthPx, heightPx, renderScale, progress, visible, isPlaying }) {
  const spec = getHighlightVisualSpec("box");
  const strokeWidth = scalePx(spec.thicknessPx, renderScale, 2);
  const glowRadius = scalePx(spec.glowRadiusPx, renderScale, 4);
  const pad = Math.ceil(strokeWidth / 2 + glowRadius);
  const svgWidth = widthPx + pad * 2;
  const svgHeight = heightPx + pad * 2;
  const dashProgress = clamp(progress * 100, 0, 100);
  const headLen = Math.max(3, spec.accHeadLen * 100);
  const headDash = Math.min(headLen, dashProgress);
  const strokeOpacity = visible ? 0.72 : 0;

  return (
    <svg
      style={{
        position: "absolute",
        left: -pad,
        top: -pad,
        width: svgWidth,
        height: svgHeight,
        overflow: "visible",
        pointerEvents: "none",
        opacity: visible ? 1 : 0,
        transition: isPlaying ? "opacity .08s linear" : "opacity .16s ease",
      }}
      viewBox={`0 0 ${svgWidth} ${svgHeight}`}
    >
      <ellipse
        cx={pad + widthPx / 2}
        cy={pad + heightPx / 2}
        rx={Math.max(1, widthPx / 2)}
        ry={Math.max(1, heightPx / 2)}
        fill="none"
        stroke={rgba(spec.rgb, strokeOpacity)}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        pathLength="100"
        strokeDasharray={`${dashProgress} 100`}
        style={{
          filter: `drop-shadow(0 0 ${glowRadius}px ${rgba(spec.rgb, 0.34)})`,
        }}
      />
      {visible && headDash > 0.1 && (
        <ellipse
          cx={pad + widthPx / 2}
          cy={pad + heightPx / 2}
          rx={Math.max(1, widthPx / 2)}
          ry={Math.max(1, heightPx / 2)}
          fill="none"
          stroke={rgba(spec.rgb, 1)}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          pathLength="100"
          strokeDasharray={`${headDash} 100`}
          strokeDashoffset={100 - dashProgress}
        />
      )}
    </svg>
  );
}

function buildArrowGeometry({ widthPx, heightPx, renderScale, side }) {
  const spec = getHighlightVisualSpec("arrow");
  const thickness = scalePx(spec.thicknessPx, renderScale, 9);
  const arrowLen = scalePx(spec.arrowLenPx, renderScale, 8);
  const headLen = Math.max(scalePx(8, renderScale, 6), thickness * spec.headLenScale);
  const headWidth = Math.max(scalePx(6, renderScale, 5), thickness * spec.headWidthScale);
  const tipInset = scalePx(spec.tipInsetPx, renderScale, 1.5);

  const tip = side === "left"
    ? { x: tipInset, y: heightPx / 2 }
    : side === "right"
      ? { x: widthPx - tipInset, y: heightPx / 2 }
      : side === "top"
        ? { x: widthPx / 2, y: tipInset }
        : { x: widthPx / 2, y: heightPx - tipInset };

  const dir = side === "left"
    ? { x: 1, y: 0 }
    : side === "right"
      ? { x: -1, y: 0 }
      : side === "top"
        ? { x: 0, y: 1 }
        : { x: 0, y: -1 };
  const normal = { x: -dir.y, y: dir.x };
  const half = thickness / 2;
  const base = {
    x: tip.x - dir.x * headLen,
    y: tip.y - dir.y * headLen,
  };
  const shaftStart = {
    x: base.x - dir.x * arrowLen,
    y: base.y - dir.y * arrowLen,
  };
  const epsilonBase = {
    x: base.x + dir.x,
    y: base.y + dir.y,
  };

  const shaft = [
    { x: shaftStart.x + normal.x * half, y: shaftStart.y + normal.y * half },
    { x: epsilonBase.x + normal.x * half, y: epsilonBase.y + normal.y * half },
    { x: epsilonBase.x - normal.x * half, y: epsilonBase.y - normal.y * half },
    { x: shaftStart.x - normal.x * half, y: shaftStart.y - normal.y * half },
  ];
  const head = [
    { x: tip.x, y: tip.y },
    { x: base.x + normal.x * headWidth, y: base.y + normal.y * headWidth },
    { x: base.x - normal.x * headWidth, y: base.y - normal.y * headWidth },
  ];
  return { shaft, head, thickness };
}

function ArrowMaterial({ widthPx, heightPx, renderScale, side, progress, visible, isPlaying }) {
  const spec = getHighlightVisualSpec("arrow");
  const geometry = buildArrowGeometry({ widthPx, heightPx, renderScale, side });
  const allPoints = [...geometry.shaft, ...geometry.head];
  const pad = Math.max(2, geometry.thickness * 0.45);
  const minX = Math.min(...allPoints.map((point) => point.x)) - pad;
  const maxX = Math.max(...allPoints.map((point) => point.x)) + pad;
  const minY = Math.min(...allPoints.map((point) => point.y)) - pad;
  const maxY = Math.max(...allPoints.map((point) => point.y)) + pad;
  const svgWidth = maxX - minX;
  const svgHeight = maxY - minY;
  const opacity = visible ? progress : 0;
  const shiftPoint = (point) => `${point.x - minX},${point.y - minY}`;

  return (
    <svg
      style={{
        position: "absolute",
        left: minX,
        top: minY,
        width: svgWidth,
        height: svgHeight,
        overflow: "visible",
        pointerEvents: "none",
        opacity,
        transition: isPlaying ? "opacity .06s linear" : "opacity .16s ease",
      }}
      viewBox={`0 0 ${svgWidth} ${svgHeight}`}
    >
      <g style={{ filter: `drop-shadow(0 0 ${Math.max(2, geometry.thickness * 0.16)}px ${rgba(spec.rgb, 0.26)})` }}>
        <polygon
          points={geometry.shaft.map(shiftPoint).join(" ")}
          fill={rgba(spec.rgb, 0.96)}
        />
        <polygon
          points={geometry.head.map(shiftPoint).join(" ")}
          fill={rgba(spec.rgb, 0.96)}
        />
      </g>
    </svg>
  );
}

function HighlightMaterial({ kind, widthPx, heightPx, renderScale, progress, visible, isPlaying, arrowSide }) {
  if (kind === "arrow") {
    return (
      <ArrowMaterial
        widthPx={widthPx}
        heightPx={heightPx}
        renderScale={renderScale}
        side={arrowSide}
        progress={progress}
        visible={visible}
        isPlaying={isPlaying}
      />
    );
  }
  if (kind === "box") {
    return (
      <LaserMaterial
        widthPx={widthPx}
        heightPx={heightPx}
        renderScale={renderScale}
        progress={progress}
        visible={visible}
        isPlaying={isPlaying}
      />
    );
  }
  return (
    <MarkerMaterial
      widthPx={widthPx}
      heightPx={heightPx}
      renderScale={renderScale}
      progress={progress}
      visible={visible}
      isPlaying={isPlaying}
    />
  );
}

export default function HlBox({
  hl,
  isSel,
  isActive,
  isPlaying,
  showPreviewOverlay = true,
  frame,
  dispatch,
  requestConfirm,
  slideHighlights = [],
  renderScale = 1,
  activeElapsedSec = 0,
  activeSentenceDurationSec = 0,
}) {
  const regionMeta = getHighlightRegionMeta(slideHighlights, hl?.id);
  const c = regionMeta.color;
  const leftPx = frame.left + (frame.width * hl.x) / 100;
  const topPx = frame.top + (frame.height * hl.y) / 100;
  const widthPx = (frame.width * hl.w) / 100;
  const heightPx = (frame.height * hl.h) / 100;
  const motionProgress = buildMotionProgress({
    kind: hl.kind,
    isPlaying,
    isActive,
    activeElapsedSec,
    activeSentenceDurationSec,
  });
  const showMaterial = showPreviewOverlay && isPlaying && isActive;
  const arrowSide = getArrowAutoSide({
    leftPx,
    widthPx,
    frameLeft: frame.left,
    frameWidth: frame.width,
  });

  const animation = isActive && isPlaying ? `${PULSE_ANIM} 1.4s ease-in-out infinite` : "none";
  const outlineBorderWidth = isSel ? 2 : (isActive && isPlaying ? 1.8 : 1.2);
  const outlineBorderColor = isSel
    ? c
    : isPlaying
      ? withAlpha(c, isActive ? 0.22 : 0.08)
      : withAlpha(c, 0.42);
  const outlineBackground = isPlaying
    ? "transparent"
    : (isSel ? withAlpha(c, 0.06) : withAlpha(c, 0.025));

  const onMoveStart = (e) => {
    if (isPlaying || e.target.dataset.rh) return;
    e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "SEL_HL", v: hl.id });
    const ox = e.clientX;
    const oy = e.clientY;
    const ox0 = hl.x;
    const oy0 = hl.y;
    const mv = (ev) => dispatch({
      type: "UPD_HL",
      id: hl.id,
      x: Math.max(0, Math.min(100 - hl.w, ox0 + ((ev.clientX - ox) / frame.width) * 100)),
      y: Math.max(0, Math.min(100 - hl.h, oy0 + ((ev.clientY - oy) / frame.height) * 100)),
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

  const onResizeStart = (e, dir) => {
    if (isPlaying) return;
    e.preventDefault();
    e.stopPropagation();
    dispatch({ type: "PUSH_HISTORY" });
    const ox = e.clientX;
    const oy = e.clientY;
    const orig = { x: hl.x, y: hl.y, w: hl.w, h: hl.h };
    const mv = (ev) => {
      const dx = ((ev.clientX - ox) / frame.width) * 100;
      const dy = ((ev.clientY - oy) / frame.height) * 100;
      let { x, y, w, h } = orig;
      if (dir.includes("e")) w = Math.max(4, orig.w + dx);
      if (dir.includes("s")) h = Math.max(4, orig.h + dy);
      if (dir.includes("w")) {
        x = Math.min(orig.x + orig.w - 4, orig.x + dx);
        w = Math.max(4, orig.w - dx);
      }
      if (dir.includes("n")) {
        y = Math.min(orig.y + orig.h - 4, orig.y + dy);
        h = Math.max(4, orig.h - dy);
      }
      if (x < 0) {
        w += x;
        x = 0;
      }
      if (y < 0) {
        h += y;
        y = 0;
      }
      if (x + w > 100) w = 100 - x;
      if (y + h > 100) h = 100 - y;
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
    <div
      data-hl-interactive="1"
      onMouseDown={onMoveStart}
      style={{
        position: "absolute",
        left: leftPx,
        top: topPx,
        width: widthPx,
        height: heightPx,
        borderRadius: 5,
        cursor: isPlaying ? "default" : "grab",
        zIndex: isActive ? 10 : 5,
        transition: "opacity .12s linear, transform .18s ease",
        animation,
      }}
    >
      <div
        style={{
          position: "absolute",
          inset: 0,
          border: `${outlineBorderWidth}px solid ${outlineBorderColor}`,
          background: outlineBackground,
          borderRadius: 5,
          pointerEvents: "none",
        }}
      />

      <HighlightMaterial
        kind={hl.kind}
        widthPx={widthPx}
        heightPx={heightPx}
        renderScale={renderScale}
        progress={motionProgress}
        visible={showMaterial}
        isPlaying={isPlaying}
        arrowSide={arrowSide}
      />

      {(isActive || isSel) && (
        <div
          style={{
            position: "absolute",
            top: -17,
            left: 0,
            background: c,
            color: "#fff",
            fontFamily: "var(--fm)",
            fontSize: 8,
            padding: "1px 5px",
            borderRadius: 2,
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {regionMeta.label}
        </div>
      )}

      {isSel && !isPlaying && (
        <div
          data-hl-interactive="1"
          onClick={(e) => {
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
          style={{
            position: "absolute",
            top: -17,
            right: 0,
            width: 16,
            height: 16,
            background: "var(--rdd)",
            border: "1px solid var(--rd)",
            borderRadius: 3,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 9,
            color: "var(--rd)",
            cursor: "pointer",
          }}
        >
          ×
        </div>
      )}

      {isSel && !isPlaying && Object.entries(HANDLE_POS).map(([dir, pos]) => (
        <div
          key={dir}
          data-hl-interactive="1"
          data-rh={dir}
          onMouseDown={(e) => onResizeStart(e, dir)}
          style={{
            position: "absolute",
            width: 10,
            height: 10,
            background: "var(--sur)",
            border: `2px solid ${c}`,
            borderRadius: "50%",
            zIndex: 20,
            ...pos,
          }}
        />
      ))}
    </div>
  );
}
