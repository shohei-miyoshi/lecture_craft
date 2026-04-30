function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function hexToRgb(hex) {
  const raw = String(hex ?? "").trim();
  if (!raw.startsWith("#")) return null;

  let normalized = raw.slice(1);
  if (normalized.length === 3) {
    normalized = normalized.split("").map((char) => char + char).join("");
  }
  if (normalized.length !== 6) return null;

  const value = Number.parseInt(normalized, 16);
  if (Number.isNaN(value)) return null;

  return {
    r: (value >> 16) & 255,
    g: (value >> 8) & 255,
    b: value & 255,
  };
}

export function withAlpha(color, alpha) {
  const rgb = hexToRgb(color);
  if (!rgb) return color;
  return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
}

export function rgba(rgb, alpha = 1) {
  const { r = 255, g = 255, b = 255 } = rgb ?? {};
  return `rgba(${r}, ${g}, ${b}, ${clamp(alpha, 0, 1)})`;
}

export function easeInOutSine(x) {
  const clamped = clamp(Number(x) || 0, 0, 1);
  return 0.5 * (1 - Math.cos(Math.PI * clamped));
}

const BACKEND_KIND_CONFIG = {
  marker: {
    rgb: { r: 255, g: 247, b: 153 },
    durationSec: 1.2,
    alpha: 165 / 255,
    cornerRadiusPx: 8,
    featherRadiusPx: 1,
    blockHMarginPx: 8,
    blockVMarginPx: 6,
  },
  arrow: {
    rgb: { r: 0, g: 200, b: 255 },
    durationSec: 1.0,
    thicknessPx: 60,
    arrowLenPx: 30,
    headLenScale: 0.7,
    headWidthScale: 1.0,
    glowRadiusPx: 0,
    tipInsetPx: 3,
  },
  box: {
    rgb: { r: 255, g: 50, b: 50 },
    durationSec: 1.5,
    thicknessPx: 8,
    glowRadiusPx: 15,
    accHeadLen: 0.06,
  },
};

export function getHighlightVisualSpec(kind) {
  return BACKEND_KIND_CONFIG[kind] ?? BACKEND_KIND_CONFIG.marker;
}

export function getHighlightMotionDurationSec(kind) {
  return getHighlightVisualSpec(kind).durationSec;
}

export function getArrowAutoSide({ leftPx = 0, widthPx = 0, frameLeft = 0, frameWidth = 0 } = {}) {
  const centerX = leftPx + widthPx / 2;
  const frameCenterX = frameLeft + frameWidth / 2;
  return centerX < frameCenterX ? "right" : "left";
}
