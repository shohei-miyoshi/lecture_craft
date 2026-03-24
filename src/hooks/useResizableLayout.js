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
      return {
        leftWidth:  clamp(saved.leftWidth  ?? DEFAULT_LAYOUT.leftWidth,  ...CLAMP.leftWidth),
        rightWidth: clamp(saved.rightWidth ?? DEFAULT_LAYOUT.rightWidth, ...CLAMP.rightWidth),
      };
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

  // ── 左パネル右端ドラッグ ──
  const startResizeLeft = useCallback((e) => {
    e.preventDefault();
    setResizingLeft(true);
    const startX = e.clientX;
    const startW = layout.leftWidth;
    const mv = (ev) => {
      const w = clamp(startW + (ev.clientX - startX), ...CLAMP.leftWidth);
      setLayout((l) => ({ ...l, leftWidth: w }));
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
    const startX = e.clientX;
    const startW = layout.rightWidth;
    const mv = (ev) => {
      const w = clamp(startW - (ev.clientX - startX), ...CLAMP.rightWidth);
      setLayout((l) => ({ ...l, rightWidth: w }));
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
    setLayout({ ...DEFAULT_LAYOUT });
  }, []);

  return { layout, startResizeLeft, startResizeRight, resizingLeft, resizingRight, resetLayout };
}

function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }
