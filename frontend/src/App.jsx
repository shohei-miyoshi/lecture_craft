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
import AuthScreen from "./components/AuthScreen.jsx";
import { buildProjectPayload, fingerprintProjectState, saveProject } from "./utils/projectStore.js";
import { fetchCurrentSession, logoutUser } from "./utils/sessionStore.js";

function parseRouteFromHash(hashValue) {
  if (hashValue === "#admin") {
    return { view: "admin", studioScreen: "home" };
  }
  if (hashValue === "#editor") {
    return { view: "studio", studioScreen: "editor" };
  }
  return { view: "studio", studioScreen: "home" };
}

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
  const initialRoute = parseRouteFromHash(window.location.hash);
  const [state, dispatch]         = useReducer(reducer, INITIAL_STATE);
  const [pdfFile, setPdfFile]     = useState(null);
  const [tab, setTab]             = useState("editor");
  const [view, setView]           = useState(initialRoute.view);
  const [studioScreen, setStudioScreen] = useState(initialRoute.studioScreen);
  const [authReady, setAuthReady] = useState(false);
  const [authSession, setAuthSession] = useState(null);
  const { toasts, addToast }      = useToast();
  const { confirmProps, requestConfirm, requestPrompt } = useConfirm();
  const { layout, startResizeLeft, startResizeRight, resizingLeft, resizingRight, resetLayout } = useResizableLayout();
  const isDirty = state.generated && (!state.savedFingerprint || fingerprintProjectState(state, state.projectMeta?.name) !== state.savedFingerprint);
  const currentWorkspace =
    state.generated || state.status === "proc" || Boolean(pdfFile) || Boolean(state.projectMeta?.name)
      ? {
          name: state.projectMeta?.name ?? pdfFile?.name?.replace(/\.pdf$/i, "") ?? "編集中のプロジェクト",
          data: {
            slides: state.slides,
            sentences: state.sents,
            highlights: state.hls,
            mode: state.appMode,
            status: state.status,
            status_message: state.statusMsg,
            pdf_name: pdfFile?.name ?? null,
          },
        }
      : null;
  const isAdmin = authSession?.user?.role === "admin";

  useEffect(() => {
    let active = true;
    fetchCurrentSession()
      .then((session) => {
        if (!active) return;
        setAuthSession(session);
        setAuthReady(true);
      })
      .catch(() => {
        if (!active) return;
        setAuthSession(null);
        setAuthReady(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const setStudioRoute = (nextScreen, historyMode = "push") => {
    const nextHash = nextScreen === "editor" ? "#editor" : "";
    setView("studio");
    setStudioScreen(nextScreen);
    if (historyMode === "replace") {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}${nextHash}`);
    } else if (window.location.hash !== nextHash) {
      window.history.pushState(null, "", `${window.location.pathname}${window.location.search}${nextHash}`);
    }
  };

  const setAdminRoute = (historyMode = "push") => {
    setView("admin");
    if (historyMode === "replace") {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}#admin`);
    } else if (window.location.hash !== "#admin") {
      window.history.pushState(null, "", `${window.location.pathname}${window.location.search}#admin`);
    }
  };

  const persistProject = async (forcedName = null) => {
    const name = forcedName ?? state.projectMeta?.name ?? pdfFile?.name?.replace(/\.pdf$/i, "") ?? "新しいプロジェクト";
    const payload = buildProjectPayload(state, name);
    try {
      const saved = await saveProject(payload);
      const nextMeta = saved?.data?.project_meta ?? payload.data.project_meta;
      dispatch({ type: "SET", k: "projectMeta", v: nextMeta });
      dispatch({ type: "SET", k: "savedFingerprint", v: fingerprintProjectState(state, nextMeta?.name ?? name) });
      addToast("ok", `プロジェクト「${name}」を保存しました`);
      return saved ?? payload;
    } catch (error) {
      console.warn("Project save failed:", error);
      addToast("er", "プロジェクト保存に失敗しました");
      throw error;
    }
  };

  const saveCurrentProject = (afterSave = null) => {
    if (state.projectMeta?.name) {
      persistProject(state.projectMeta.name)
        .then(() => afterSave?.())
        .catch(() => {});
      return;
    }
    const defaultName = pdfFile?.name?.replace(/\.pdf$/i, "") ?? "新しいプロジェクト";
    requestPrompt({
      title: "プロジェクトを保存",
      message: "保存するプロジェクト名を入力してください。",
      confirmLabel: "保存する",
      inputLabel: "プロジェクト名",
      inputInitialValue: defaultName,
      inputPlaceholder: "例: パターン認識の講義",
      onConfirm: async (value) => {
        const name = String(value ?? "").trim();
        if (!name) return;
        try {
          await persistProject(name);
          afterSave?.();
        } catch {
          // toast already shown in persistProject
        }
      },
    });
  };

  const confirmDirtyAction = (proceed, actionLabel) => {
    if (!isDirty) {
      proceed();
      return;
    }
    requestConfirm({
      title: "未保存の変更があります",
      message: `未保存の編集があります。\n${actionLabel}前に保存しますか？`,
      confirmLabel: "保存して続行",
      secondaryLabel: "保存せず続行",
      onSecondary: proceed,
      onConfirm: () => saveCurrentProject(proceed),
    });
  };

  // ── リセット確認 ──
  const handleReset = () => {
    if (!state.generated) {
      dispatch({ type: "RESET" });
      setPdfFile(null);
      setStudioRoute("home");
      return;
    }
    confirmDirtyAction(() => {
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
          setStudioRoute("home");
        },
      });
    }, "リセット");
  };

  const handleCreateProject = (nextPdfFile = null) => {
    confirmDirtyAction(() => {
      dispatch({ type: "RESET" });
      setPdfFile(nextPdfFile);
      setTab("editor");
      setStudioRoute("editor");
      if (nextPdfFile) {
        addToast("in", `📑 ${nextPdfFile.name}`);
      }
    }, "新規作成");
  };

  const handleOpenProject = (project) => {
    if (!project?.data) return;
    confirmDirtyAction(() => {
      dispatch({ type: "LOAD", d: project.data });
      setPdfFile(null);
      setTab("editor");
      setStudioRoute("editor");
      addToast("ok", `プロジェクト「${project.name}」を読み込みました`);
    }, "別のプロジェクトを開く");
  };

  const goHome = () => {
    setStudioRoute("home");
  };

  // ── キーボードショートカット ──
  useEffect(() => {
    const onHashChange = () => {
      const route = parseRouteFromHash(window.location.hash);
      setView(route.view);
      setStudioScreen(route.studioScreen);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    if (!isAdmin && view === "admin") {
      setStudioRoute("home", "replace");
    }
  }, [isAdmin, view]);

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
    if (nextView === "admin") {
      if (!isAdmin) return;
      setAdminRoute();
      return;
    }
    setStudioRoute(studioScreen === "editor" ? "editor" : "home");
  };

  const handleLogout = () => {
    const run = async () => {
      await logoutUser();
      setAuthSession(null);
      setView("studio");
      setStudioScreen("home");
      dispatch({ type: "RESET" });
      setPdfFile(null);
      addToast("ok", "ログアウトしました");
    };
    if (!isDirty) {
      run();
      return;
    }
    requestConfirm({
      title: "ログアウト",
      message: "未保存の変更があります。保存せずにログアウトしますか？",
      confirmLabel: "ログアウトする",
      onConfirm: run,
    });
  };

  if (!authReady) {
    return (
      <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", background: "var(--bg)", color: "var(--ts)" }}>
        認証状態を確認中...
      </div>
    );
  }

  if (!authSession) {
    return (
      <>
        <AuthScreen onAuthenticated={setAuthSession} addToast={addToast} />
        <ToastLayer toasts={toasts} />
      </>
    );
  }

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
            ...(isAdmin ? [["admin", "管理"]] : []),
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
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ fontSize: 10, color: "var(--tm)" }}>
            {authSession.user?.username}
          </div>
          <div style={{ padding: "3px 8px", borderRadius: 999, background: isAdmin ? "rgba(91,141,239,.16)" : "rgba(255,255,255,.05)", border: "1px solid var(--bd2)", fontSize: 9, color: isAdmin ? "var(--ac)" : "var(--ts)" }}>
            {isAdmin ? "管理者" : "ユーザ"}
          </div>
          <button onClick={handleLogout} style={{ padding: "5px 9px", border: "1px solid var(--bd2)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>
            ログアウト
          </button>
        </div>
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
          onResumeEditing={() => setStudioRoute("editor")}
          currentProject={currentWorkspace}
          requestConfirm={requestConfirm}
          requestPrompt={requestPrompt}
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
        <div style={{ width: layout.leftWidth, minWidth: layout.leftWidth, maxWidth: layout.leftWidth, overflow: "hidden", flexShrink: 0, minHeight: 0, display: "flex", position: "relative", zIndex: 1 }}>
          <LeftPanel
            state={state}
            dispatch={dispatch}
            pdfFile={pdfFile}
            setPdfFile={setPdfFile}
            addToast={addToast}
            requestConfirm={requestConfirm}
            handleReset={handleReset}
            saveProjectNow={saveCurrentProject}
            isDirty={isDirty}
          />
        </div>

        {/* 左ハンドル */}
        <ResizeHandle onMouseDown={startResizeLeft} resizing={resizingLeft} />

        {/* 中央パネル（残り幅を占有） */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", position: "relative", zIndex: 1 }}>
          <CenterPanel state={state} dispatch={dispatch} addToast={addToast} requestConfirm={requestConfirm} />
        </div>

        {/* 右ハンドル */}
        <ResizeHandle onMouseDown={startResizeRight} resizing={resizingRight} />

        {/* 右パネル（幅可変） — タブ付き */}
        <div style={{ width: layout.rightWidth, minWidth: layout.rightWidth, maxWidth: layout.rightWidth, overflow: "hidden", flexShrink: 0, minHeight: 0, display: "flex", position: "relative", zIndex: 1 }}>
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
