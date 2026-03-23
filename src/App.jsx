import { useState, useEffect, useReducer } from "react";
import "./index.css";

import { reducer, INITIAL_STATE } from "./store/reducer.js";
import { useToast }               from "./hooks/useToast.js";
import { useConfirm }             from "./hooks/useConfirm.js";

import ConfirmDialog from "./components/ConfirmDialog.jsx";
import ToastLayer    from "./components/ToastLayer.jsx";
import LeftPanel     from "./components/LeftPanel.jsx";
import CenterPanel   from "./components/CenterPanel.jsx";
import RightPanel    from "./components/RightPanel.jsx";
import ExportPanel   from "./components/ExportPanel.jsx";

export default function App() {
  const [state, dispatch]         = useReducer(reducer, INITIAL_STATE);
  const [pdfFile, setPdfFile]     = useState(null);
  const [tab, setTab]             = useState("editor");
  const { toasts, addToast }      = useToast();
  const { confirmProps, requestConfirm } = useConfirm();

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
      // ConfirmDialog表示中はショートカット無効（Escはダイアログ側で処理）
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

  const tabStyle = (on) => ({
    padding: "4px 11px", background: "none", fontFamily: "var(--fb)", fontSize: 11,
    border:     `1px solid ${on ? "rgba(91,141,239,.28)" : "transparent"}`,
    borderRadius: "var(--r)",
    color:      on ? "var(--ac)" : "var(--ts)",
    background: on ? "var(--adim)" : "none",
    cursor: "pointer",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", background: "var(--bg)" }}>

      {/* ── ヘッダー ── */}
      <header style={{ height: 46, display: "flex", alignItems: "center", padding: "0 16px", gap: 10, background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 15, fontWeight: 800, display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 22, height: 22, background: "var(--ac)", borderRadius: 5, display: "grid", placeItems: "center", fontSize: 11 }}>▶</div>
          Lecture<span style={{ color: "var(--ac)" }}>Craft</span>
        </div>
        <div style={{ width: 1, height: 18, background: "var(--bd)" }} />
        <div style={{ display: "flex", gap: 2, flex: 1 }}>
          <button onClick={() => setTab("editor")} style={tabStyle(tab === "editor")}>エディタ</button>
          <button onClick={() => setTab("export")} style={tabStyle(tab === "export")}>書き出し</button>
        </div>
        <button onClick={handleReset} style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>
          ↺ リセット
        </button>
      </header>

      {/* ── メイン3カラム ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", minHeight: 0 }}>
        <LeftPanel
          state={state}
          dispatch={dispatch}
          pdfFile={pdfFile}
          setPdfFile={setPdfFile}
          addToast={addToast}
          requestConfirm={requestConfirm}
        />
        <CenterPanel state={state} dispatch={dispatch} />
        {tab === "editor"
          ? <RightPanel  state={state} dispatch={dispatch} addToast={addToast} requestConfirm={requestConfirm} />
          : <ExportPanel state={state} addToast={addToast} />
        }
      </div>

      {/* ── カスタム確認ダイアログ ── */}
      <ConfirmDialog {...confirmProps} />

      {/* ── トースト通知 ── */}
      <ToastLayer toasts={toasts} />
    </div>
  );
}
