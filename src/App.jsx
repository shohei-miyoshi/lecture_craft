import { useState, useEffect, useReducer } from "react";
import "./index.css";

import { reducer, INITIAL_STATE } from "./store/reducer.js";
import { useToast }               from "./hooks/useToast.js";
import { useConfirm }             from "./hooks/useConfirm.js";
import { useResizableLayout }     from "./hooks/useResizableLayout.js";

import ConfirmDialog from "./components/ConfirmDialog.jsx";
import ToastLayer    from "./components/ToastLayer.jsx";
import LeftPanel     from "./components/LeftPanel.jsx";
import CenterPanel   from "./components/CenterPanel.jsx";
import RightPanel    from "./components/RightPanel.jsx";
import ExportPanel   from "./components/ExportPanel.jsx";

/** リサイズハンドル（縦線） */
function ResizeHandle({ onMouseDown, resizing }) {
  return (
    <div
      onMouseDown={onMouseDown}
      style={{
        width: 4,
        flexShrink: 0,
        cursor: "col-resize",
        background: resizing ? "var(--ac)" : "transparent",
        borderLeft: "1px solid var(--bd)",
        transition: "background .1s",
        position: "relative",
        zIndex: 10,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bd2)"; }}
      onMouseLeave={(e) => { if (!resizing) e.currentTarget.style.background = "transparent"; }}
    />
  );
}

export default function App() {
  const [state, dispatch]         = useReducer(reducer, INITIAL_STATE);
  const [pdfFile, setPdfFile]     = useState(null);
  const [tab, setTab]             = useState("editor");
  const { toasts, addToast }      = useToast();
  const { confirmProps, requestConfirm } = useConfirm();
  const { layout, startResizeLeft, startResizeRight, resizingLeft, resizingRight, resetLayout } = useResizableLayout();

  // ── リセット確認 ──
  const handleReset = () => {
    if (!state.generated) {
      dispatch({ type: "RESET" });
      setPdfFile(null);
      return;
    }
    requestConfirm({
      title:        "リセット",
      message:      "現在の講義データをすべて削除します。\n保存が必要な場合は「書き出し」からJSONをエクスポートしてください。",
      confirmLabel: "リセット",
      confirmColor: "var(--am)",
      confirmBg:    "var(--amd)",
      confirmBorder:"rgba(232,169,75,.35)",
      onConfirm: () => {
        dispatch({ type: "RESET" });
        setPdfFile(null);
      },
    });
  };

  // ── キーボードショートカット ──
  useEffect(() => {
    const handler = (e) => {
      if (["INPUT", "TEXTAREA"].includes(e.target.tagName) || e.target.contentEditable === "true") return;
      if (confirmProps.open) return;
      switch (e.code) {
        case "Space":
          e.preventDefault();
          dispatch({ type: "SET", k: "playing", v: !state.playing });
          break;
        case "ArrowRight":
          dispatch({ type: "SET_SL", v: Math.min(state.slides.length - 1, state.curSl + 1) });
          break;
        case "ArrowLeft":
          dispatch({ type: "SET_SL", v: Math.max(0, state.curSl - 1) });
          break;
        case "Escape":
          dispatch({ type: "SET", k: "drawMode",   v: false });
          dispatch({ type: "SET", k: "drawSentId", v: null  });
          break;
        case "Delete":
        case "Backspace":
          if (state.selHl) dispatch({ type: "RM_HL_ID", v: state.selHl });
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [state.playing, state.curSl, state.slides.length, state.selHl, confirmProps.open]);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", background: "var(--bg)", cursor: resizingLeft || resizingRight ? "col-resize" : "default" }}>

      {/* ── ヘッダー ── */}
      <header style={{ height: 46, display: "flex", alignItems: "center", padding: "0 16px", gap: 10, background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 15, fontWeight: 800, display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 22, height: 22, background: "var(--ac)", borderRadius: 5, display: "grid", placeItems: "center", fontSize: 11 }}>▶</div>
          Lecture<span style={{ color: "var(--ac)" }}>Craft</span>
        </div>
        <div style={{ width: 1, height: 18, background: "var(--bd)" }} />
        <div style={{ flex: 1 }} />
        {/* レイアウトリセット */}
        <button
          onClick={resetLayout}
          title="レイアウトをリセット"
          style={{ padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "none", color: "var(--tm)", fontSize: 10 }}
        >
          ⊡
        </button>
        <button onClick={handleReset} style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>
          ↺ リセット
        </button>
      </header>

      {/* ── メイン3カラム + リサイズハンドル ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", minHeight: 0 }}>

        {/* 左パネル（幅可変） */}
        <div style={{ width: layout.leftWidth, minWidth: layout.leftWidth, maxWidth: layout.leftWidth, overflow: "hidden", flexShrink: 0 }}>
          <LeftPanel
            state={state}
            dispatch={dispatch}
            pdfFile={pdfFile}
            setPdfFile={setPdfFile}
            addToast={addToast}
            requestConfirm={requestConfirm}
          />
        </div>

        {/* 左ハンドル */}
        <ResizeHandle onMouseDown={startResizeLeft} resizing={resizingLeft} />

        {/* 中央パネル（残り幅を占有） */}
        <CenterPanel state={state} dispatch={dispatch} />

        {/* 右ハンドル */}
        <ResizeHandle onMouseDown={startResizeRight} resizing={resizingRight} />

        {/* 右パネル（幅可変） — タブ付き */}
        <div style={{ width: layout.rightWidth, minWidth: layout.rightWidth, maxWidth: layout.rightWidth, overflow: "hidden", flexShrink: 0 }}>
          <RightPanel
            state={state}
            dispatch={dispatch}
            addToast={addToast}
            requestConfirm={requestConfirm}
            tab={tab}
            setTab={setTab}
            rightContent={<ExportPanel state={state} addToast={addToast} />}
          />
        </div>
      </div>

      {/* ── カスタム確認ダイアログ ── */}
      <ConfirmDialog {...confirmProps} />

      {/* ── トースト通知 ── */}
      <ToastLayer toasts={toasts} />
    </div>
  );
}
