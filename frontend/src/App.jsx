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
import AdminDashboard from "./components/AdminDashboard.jsx";
import ProjectHome from "./components/ProjectHome.jsx";

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
  const [view, setView]           = useState(() => (window.location.hash === "#admin" ? "admin" : "studio"));
  const [studioScreen, setStudioScreen] = useState("home");
  const { toasts, addToast }      = useToast();
  const { confirmProps, requestConfirm, requestPrompt } = useConfirm();
  const { layout, startResizeLeft, startResizeRight, resizingLeft, resizingRight, resetLayout } = useResizableLayout();

  // ── リセット確認 ──
  const handleReset = () => {
    if (!state.generated) {
      dispatch({ type: "RESET" });
      setPdfFile(null);
      setStudioScreen("home");
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
        setStudioScreen("home");
      },
    });
  };

  const handleCreateProject = (nextPdfFile = null) => {
    dispatch({ type: "RESET" });
    setPdfFile(nextPdfFile);
    setTab("editor");
    setStudioScreen("editor");
    if (nextPdfFile) {
      addToast("in", `📑 ${nextPdfFile.name}`);
    }
  };

  const handleOpenProject = (project) => {
    if (!project?.data) return;
    dispatch({ type: "LOAD", d: project.data });
    setPdfFile(null);
    setTab("editor");
    setStudioScreen("editor");
    addToast("ok", `プロジェクト「${project.name}」を読み込みました`);
  };

  const goHome = () => {
    setView("studio");
    window.location.hash = "";
    setStudioScreen("home");
  };

  // ── キーボードショートカット ──
  useEffect(() => {
    const onHashChange = () => setView(window.location.hash === "#admin" ? "admin" : "studio");
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    const onMouseSide = (e) => {
      if (view === "admin" || studioScreen === "home") return;
      if (e.button === 3) {
        e.preventDefault();
        e.stopPropagation();
        dispatch({ type: "UNDO" });
      } else if (e.button === 4) {
        e.preventDefault();
        e.stopPropagation();
        dispatch({ type: "REDO" });
      }
    };
    window.addEventListener("mousedown", onMouseSide, true);
    window.addEventListener("mouseup", onMouseSide, true);
    window.addEventListener("click", onMouseSide, true);
    window.addEventListener("auxclick", onMouseSide, true);
    return () => {
      window.removeEventListener("mousedown", onMouseSide, true);
      window.removeEventListener("mouseup", onMouseSide, true);
      window.removeEventListener("click", onMouseSide, true);
      window.removeEventListener("auxclick", onMouseSide, true);
    };
  }, [view, studioScreen]);

  useEffect(() => {
    const handler = (e) => {
      if (view === "admin" || studioScreen === "home") return;
      if (["INPUT", "TEXTAREA"].includes(e.target.tagName) || e.target.contentEditable === "true") return;
      if (confirmProps.open) return;
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyZ" && !e.shiftKey) {
        e.preventDefault();
        dispatch({ type: "UNDO" });
        return;
      }
      if (
        ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === "KeyZ")
        || ((e.ctrlKey || e.metaKey) && e.code === "KeyY")
      ) {
        e.preventDefault();
        dispatch({ type: "REDO" });
        return;
      }
      const currentSlideStart = (() => {
        const targets = state.sents.filter((s) => s.slide_idx === state.curSl);
        if (!targets.length) return 0;
        return Math.min(...targets.map((s) => Number(s.start_sec ?? 0)));
      })();
      switch (e.code) {
        case "Space":
        case "Enter":
        case "KeyN":
        case "PageDown":
        case "ArrowRight":
        case "ArrowDown":
          e.preventDefault();
          dispatch({ type: "SET_SL", v: Math.min(state.slides.length - 1, state.curSl + 1) });
          break;
        case "KeyP":
        case "PageUp":
        case "ArrowLeft":
        case "ArrowUp":
        case "Backspace":
          e.preventDefault();
          dispatch({ type: "SET_SL", v: Math.max(0, state.curSl - 1) });
          break;
        case "Home":
          e.preventDefault();
          dispatch({ type: "SET_SL", v: 0 });
          break;
        case "End":
          e.preventDefault();
          dispatch({ type: "SET_SL", v: Math.max(0, state.slides.length - 1) });
          break;
        case "F5":
          e.preventDefault();
          if (e.shiftKey) {
            dispatch({ type: "SEEK", v: currentSlideStart });
          } else {
            dispatch({ type: "SET_SL", v: 0 });
            dispatch({ type: "SEEK", v: 0 });
          }
          dispatch({ type: "SET", k: "playing", v: true });
          break;
        case "Escape":
          e.preventDefault();
          dispatch({ type: "SET", k: "drawMode",   v: false });
          dispatch({ type: "SET", k: "drawSentId", v: null  });
          dispatch({ type: "SET", k: "playing", v: false });
          break;
        case "Delete":
          if (state.selHl) {
            const target = state.hls.find((hl) => hl.id === state.selHl);
            const run = () => {
              dispatch({ type: "PUSH_HISTORY" });
              dispatch({ type: "RM_HL_ID", v: state.selHl });
            };
            if (target && (target.sentence_ids ?? []).length > 1) {
              requestConfirm({
                title: "共有ハイライト枠を削除",
                message: `この枠は ${(target.sentence_ids ?? []).length} 個の台本と対応しています。\n削除すると関連する対応も一緒に消えますが、大丈夫ですか？`,
                confirmLabel: "削除する",
                onConfirm: run,
              });
            } else {
              run();
            }
          }
          break;
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [state.playing, state.curSl, state.slides.length, state.selHl, confirmProps.open, view, studioScreen]);

  const switchView = (nextView) => {
    setView(nextView);
    window.location.hash = nextView === "admin" ? "admin" : "";
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        overflow: "hidden",
        background:
          "radial-gradient(circle at top left, rgba(91,141,239,.12), transparent 24%), radial-gradient(circle at bottom right, rgba(110,193,255,.08), transparent 18%), var(--bg)",
        cursor: resizingLeft || resizingRight ? "col-resize" : "default",
      }}
    >

      {/* ── ヘッダー ── */}
      <header
        style={{
          height: 58,
          display: "flex",
          alignItems: "center",
          padding: "0 18px",
          gap: 12,
          background: "linear-gradient(180deg, rgba(19,21,26,.96), rgba(19,21,26,.82))",
          borderBottom: "1px solid rgba(255,255,255,.05)",
          flexShrink: 0,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(91,141,239,.14), transparent 20%, transparent 78%, rgba(110,193,255,.08))", pointerEvents: "none" }} />
        <button
          onClick={goHome}
          style={{
            fontFamily: "var(--ff)",
            fontSize: 15,
            fontWeight: 800,
            display: "flex",
            alignItems: "center",
            gap: 8,
            position: "relative",
            zIndex: 1,
            border: "none",
            background: "none",
            color: "inherit",
            padding: 0,
            textAlign: "left",
          }}
        >
          <div style={{ width: 24, height: 24, background: "linear-gradient(135deg, var(--ac), #7aa7ff)", borderRadius: 7, display: "grid", placeItems: "center", fontSize: 11, boxShadow: "0 10px 24px rgba(91,141,239,.28)" }}>▶</div>
          <div>
            <div style={{ lineHeight: 1 }}>Lecture<span style={{ color: "var(--ac)" }}>Craft</span></div>
            <div style={{ fontFamily: "var(--fm)", fontSize: 8, color: "var(--tm)", marginTop: 2 }}>
              {view === "admin"
                ? "ADMIN OVERVIEW"
                : studioScreen === "home"
                  ? "PROJECT INDEX"
                  : state.projectMeta?.name ?? "EDITOR"}
            </div>
          </div>
        </button>
        <div style={{ width: 1, height: 24, background: "linear-gradient(180deg, transparent, var(--bd2), transparent)", position: "relative", zIndex: 1 }} />
        <div style={{ display: "inline-flex", padding: 3, borderRadius: 999, background: "var(--s2)", border: "1px solid var(--bd)" }}>
          {[
            ["studio", "編集"],
            ["admin", "管理"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => switchView(key)}
              style={{
                padding: "4px 10px",
                border: "none",
                borderRadius: 999,
                background: view === key ? "var(--ac)" : "transparent",
                color: view === key ? "#fff" : "var(--ts)",
                fontSize: 10,
                fontWeight: 600,
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        {/* レイアウトリセット */}
        {view === "studio" && studioScreen === "editor" && (
          <>
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
          </>
        )}
      </header>

      {/* ── メイン3カラム + リサイズハンドル ── */}
      {view === "admin" ? (
        <div style={{ flex: 1, minHeight: 0 }}>
          <AdminDashboard addToast={addToast} />
        </div>
      ) : view === "studio" && studioScreen === "home" ? (
        <ProjectHome
          onCreateProject={handleCreateProject}
          onOpenProject={handleOpenProject}
          onResumeEditing={() => setStudioScreen("editor")}
          currentProject={state.generated ? { name: state.projectMeta?.name ?? "編集中のプロジェクト", data: { slides: state.slides, sentences: state.sents, highlights: state.hls, mode: state.appMode } } : null}
          requestConfirm={requestConfirm}
          addToast={addToast}
        />
      ) : (
      <div style={{ flex: 1, minHeight: 0, padding: 12, overflow: "hidden" }}>
        <div
          style={{
            position: "relative",
            display: "flex",
            flex: 1,
            height: "100%",
            overflow: "hidden",
            minHeight: 0,
            border: "1px solid rgba(255,255,255,.05)",
            background: "linear-gradient(180deg, rgba(19,21,26,.92), rgba(19,21,26,.82))",
            boxShadow: "0 24px 60px rgba(0,0,0,.22)",
          }}
        >
          <div style={{ position: "absolute", top: 0, left: 0, width: 132, height: 18, background: "linear-gradient(90deg, var(--ac), transparent)", opacity: 0.55, pointerEvents: "none" }} />
          <div style={{ position: "absolute", bottom: 0, right: 0, width: 140, height: 18, background: "linear-gradient(270deg, rgba(110,193,255,.32), transparent)", opacity: 0.35, pointerEvents: "none" }} />
          <div style={{ position: "absolute", inset: 0, background: "linear-gradient(90deg, rgba(255,255,255,.02) 1px, transparent 1px), linear-gradient(180deg, rgba(255,255,255,.015) 1px, transparent 1px)", backgroundSize: "32px 32px", opacity: 0.12, pointerEvents: "none" }} />

        {/* 左パネル（幅可変） */}
        <div style={{ width: layout.leftWidth, minWidth: layout.leftWidth, maxWidth: layout.leftWidth, overflow: "hidden", flexShrink: 0 }}>
          <LeftPanel
            state={state}
            dispatch={dispatch}
            pdfFile={pdfFile}
            setPdfFile={setPdfFile}
            addToast={addToast}
            requestConfirm={requestConfirm}
            requestPrompt={requestPrompt}
            handleReset={handleReset}
          />
        </div>

        {/* 左ハンドル */}
        <ResizeHandle onMouseDown={startResizeLeft} resizing={resizingLeft} />

        {/* 中央パネル（残り幅を占有） */}
        <CenterPanel state={state} dispatch={dispatch} addToast={addToast} requestConfirm={requestConfirm} />

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
            rightContent={<ExportPanel state={state} dispatch={dispatch} addToast={addToast} />}
          />
        </div>
      </div>
      </div>
      )}

      {/* ── カスタム確認ダイアログ ── */}
      <ConfirmDialog {...confirmProps} />

      {/* ── トースト通知 ── */}
      <ToastLayer toasts={toasts} />
    </div>
  );
}
