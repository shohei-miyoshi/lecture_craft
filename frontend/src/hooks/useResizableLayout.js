import { useState, useEffect, useRef, useCallback } from "react";

const STORAGE_KEY = "lc_layout";

const DEFAULT_LAYOUT = {
  leftWidth:  250,
  rightWidth: 380,
};

const CLAMP = {
  leftWidth:  [160, 380],
  rightWidth: [280, 520],
};

function dynamicClamp(kind) {
  const width = typeof window === "undefined" ? 1200 : window.innerWidth;
  if (width < 760) {
    return kind === "leftWidth" ? [112, 260] : [180, 340];
  }
  if (width < 1040) {
    return kind === "leftWidth" ? [140, 320] : [220, 420];
  }
  return CLAMP[kind];
}

function fitLayoutToViewport(layout) {
  const width = typeof window === "undefined" ? 1200 : window.innerWidth;
  const minCenter = width < 760 ? 220 : 340;
  const chrome = 48;
  const maxSideTotal = Math.max(0, width - minCenter - chrome);
  const leftClamp = dynamicClamp("leftWidth");
  const rightClamp = dynamicClamp("rightWidth");
  let leftWidth = clamp(layout.leftWidth ?? DEFAULT_LAYOUT.leftWidth, ...leftClamp);
  let rightWidth = clamp(layout.rightWidth ?? DEFAULT_LAYOUT.rightWidth, ...rightClamp);

  if (leftWidth + rightWidth > maxSideTotal && maxSideTotal > 0) {
    const scale = maxSideTotal / (leftWidth + rightWidth);
    leftWidth = clamp(Math.floor(leftWidth * scale), ...leftClamp);
    rightWidth = clamp(Math.floor(rightWidth * scale), ...rightClamp);
  }

  return { leftWidth, rightWidth };
}

/**
 * リサイズ可能なレイアウト管理フック
 * - 左・右パネルの幅をドラッグで変更
 * - localStorage に永続化
 *
 * 返り値:
 *   layout          : { leftWidth, rightWidth }
 *   startResizeLeft : (mouseEvent) => void  左パネルの右端ハンドルのmousedown
 *   startResizeRight: (mouseEvent) => void  右パネルの左端ハンドルのmousedown
 *   resizingLeft    : boolean
 *   resizingRight   : boolean
 */
export function useResizableLayout() {
  const [layout, setLayout] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
      return fitLayoutToViewport(saved);
    } catch {
      return { ...DEFAULT_LAYOUT };
    }
  });

  const [resizingLeft,  setResizingLeft]  = useState(false);
  const [resizingRight, setResizingRight] = useState(false);

  // localStorage に保存
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(layout)); } catch {}
  }, [layout]);

  useEffect(() => {
    const onResize = () => {
      setLayout((current) => fitLayoutToViewport(current));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  // ── 左パネル右端ドラッグ ──
  const startResizeLeft = useCallback((e) => {
    e.preventDefault();
    setResizingLeft(true);
    const bounds = dynamicClamp("leftWidth");
    const startX = e.clientX;
    const startW = layout.leftWidth;
    const mv = (ev) => {
      const w = clamp(startW + (ev.clientX - startX), ...bounds);
      setLayout((l) => fitLayoutToViewport({ ...l, leftWidth: w }));
    };
    const up = () => {
      setResizingLeft(false);
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  }, [layout.leftWidth]);

  // ── 右パネル左端ドラッグ ──
  const startResizeRight = useCallback((e) => {
    e.preventDefault();
    setResizingRight(true);
    const bounds = dynamicClamp("rightWidth");
    const startX = e.clientX;
    const startW = layout.rightWidth;
    const mv = (ev) => {
      const w = clamp(startW - (ev.clientX - startX), ...bounds);
      setLayout((l) => fitLayoutToViewport({ ...l, rightWidth: w }));
    };
    const up = () => {
      setResizingRight(false);
      document.removeEventListener("mousemove", mv);
      document.removeEventListener("mouseup", up);
    };
    document.addEventListener("mousemove", mv);
    document.addEventListener("mouseup", up);
  }, [layout.rightWidth]);

  // リセット
  const resetLayout = useCallback(() => {
    setLayout(fitLayoutToViewport(DEFAULT_LAYOUT));
  }, []);

  return { layout, startResizeLeft, startResizeRight, resizingLeft, resizingRight, resetLayout };
}

function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
