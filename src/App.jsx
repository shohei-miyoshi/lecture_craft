import { useState, useEffect, useReducer } from "react";
import "./index.css";

import { reducer, INITIAL_STATE } from "./store/reducer.js";
import { useToast }               from "./hooks/useToast.js";

import ToastLayer  from "./components/ToastLayer.jsx";
import LeftPanel   from "./components/LeftPanel.jsx";
import CenterPanel from "./components/CenterPanel.jsx";
import RightPanel  from "./components/RightPanel.jsx";
import ExportPanel from "./components/ExportPanel.jsx";

export default function App() {
  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const [pdfFile, setPdfFile] = useState(null);
  const [tab, setTab]         = useState("editor"); // "editor" | "export"
  const { toasts, addToast }  = useToast();

  // ── キーボードショートカット ──
  useEffect(() => {
    const handler = (e) => {
      // テキスト入力中は無効
      if (["INPUT", "TEXTAREA"].includes(e.target.tagName) || e.target.contentEditable === "true") return;
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
  }, [state.playing, state.curSl, state.slides.length, state.selHl]);

  const tabStyle = (on) => ({
    padding: "4px 11px", background: "none", fontFamily: "var(--fb)", fontSize: 11,
    border:      `1px solid ${on ? "rgba(91,141,239,.28)" : "transparent"}`,
    borderRadius: "var(--r)",
    color:       on ? "var(--ac)" : "var(--ts)",
    background:  on ? "var(--adim)" : "none",
    cursor: "pointer",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden", background: "var(--bg)" }}>

      {/* ── ヘッダー ── */}
      <header style={{ height: 46, display: "flex", alignItems: "center", padding: "0 16px", gap: 10, background: "var(--sur)", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        {/* ロゴ */}
        <div style={{ fontFamily: "var(--ff)", fontSize: 15, fontWeight: 800, display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 22, height: 22, background: "var(--ac)", borderRadius: 5, display: "grid", placeItems: "center", fontSize: 11 }}>▶</div>
          Lecture<span style={{ color: "var(--ac)" }}>Craft</span>
        </div>
        <div style={{ width: 1, height: 18, background: "var(--bd)" }} />

        {/* タブ */}
        <div style={{ display: "flex", gap: 2, flex: 1 }}>
          <button onClick={() => setTab("editor")} style={tabStyle(tab === "editor")}>エディタ</button>
          <button onClick={() => setTab("export")} style={tabStyle(tab === "export")}>書き出し</button>
        </div>

        {/* リセット */}
        <button
          onClick={() => {
            if (!state.generated || confirm("全データをリセットしますか？")) {
              dispatch({ type: "RESET" });
              setPdfFile(null);
            }
          }}
          style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}
        >
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
        />
        <CenterPanel state={state} dispatch={dispatch} />
        {tab === "editor"
          ? <RightPanel  state={state} dispatch={dispatch} addToast={addToast} />
          : <ExportPanel state={state} addToast={addToast} />
        }
      </div>

      {/* ── トースト通知 ── */}
      <ToastLayer toasts={toasts} />
    </div>
  );
}
