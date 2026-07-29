import { useState, useEffect, useReducer, useRef } from "react";
import "./index.css";

import { reducer, INITIAL_STATE } from "./store/reducer.js";
import { useToast }               from "./hooks/useToast.js";
import { useConfirm }             from "./hooks/useConfirm.js";
import { useResizableLayout }     from "./hooks/useResizableLayout.js";
import { usePreviewPlayback }     from "./hooks/usePreviewPlayback.js";

import ConfirmDialog from "./components/ConfirmDialog.jsx";
import ToastLayer    from "./components/ToastLayer.jsx";
import LeftPanel     from "./components/LeftPanel.jsx";
import CenterPanel   from "./components/CenterPanel.jsx";
import RightPanel    from "./components/RightPanel.jsx";
import ExportPanel   from "./components/ExportPanel.jsx";
import AdminDashboard from "./components/AdminDashboard.jsx";
import ProjectHome from "./components/ProjectHome.jsx";
import AuthScreen from "./components/AuthScreen.jsx";
import { DETAIL_VALS, DIFF_VALS } from "./utils/constants.js";
import {
  buildProjectData,
  buildProjectPayload,
  checkpointProject,
  createProject,
  fingerprintProjectData,
  fingerprintProjectState,
  loadProject,
  saveProject,
  saveProjectDraft,
  uploadProjectPdf,
} from "./utils/projectStore.js";
import { buildResearchSnapshot } from "./utils/research.js";
import { authFetch, fetchCurrentSession, logoutUser } from "./utils/sessionStore.js";
import { submitPreviewAudio } from "./utils/jobClient.js";

function parseRouteFromHash(hashValue) {
  if (hashValue === "#admin") {
    return { view: "admin", studioScreen: "home" };
  }
  if (hashValue === "#editor") {
    return { view: "studio", studioScreen: "editor" };
  }
  return { view: "studio", studioScreen: "home" };
}

const DEFAULT_REVIEW_SETTINGS = Object.freeze({
  layout_review_mode: "off",
  script_review_mode: "off",
});

const DEFAULT_REVIEW_FLOW = Object.freeze({
  active: false,
  stage: "editor",
  layoutEnabled: false,
  scriptEnabled: false,
});
const CURRENT_JOB_STORAGE_KEY = "lecture_craft_current_job_id_v1";
const ACTIVE_PROJECT_STORAGE_KEY_BASE = "lecture_craft_active_project_id_v1";

function isReviewEnabled(mode) {
  return mode === "human";
}

function buildLayoutReviewRecords(research) {
  const feedback = research?.feedback?.highlights ?? {};
  const now = new Date().toISOString();
  const rows = [];
  for (const row of feedback.accepted ?? []) {
    rows.push({
      slide_idx: row.value?.slide_idx ?? null,
      highlight_id: row.id ?? row.value?.id ?? null,
      review_source: "human",
      decision: "accepted",
      before: row.value ?? null,
      after: row.value ?? null,
      created_at: now,
    });
  }
  for (const row of feedback.modified ?? []) {
    rows.push({
      slide_idx: row.after?.slide_idx ?? row.before?.slide_idx ?? null,
      highlight_id: row.id ?? row.after?.id ?? row.before?.id ?? null,
      review_source: "human",
      decision: "modified",
      before: row.before ?? null,
      after: row.after ?? null,
      created_at: now,
    });
  }
  for (const row of feedback.removed ?? []) {
    rows.push({
      slide_idx: row.before?.slide_idx ?? null,
      highlight_id: row.id ?? row.before?.id ?? null,
      review_source: "human",
      decision: "removed",
      before: row.before ?? null,
      after: null,
      created_at: now,
    });
  }
  for (const row of feedback.added ?? []) {
    rows.push({
      slide_idx: row.after?.slide_idx ?? null,
      highlight_id: row.id ?? row.after?.id ?? null,
      review_source: "human",
      decision: "added",
      before: null,
      after: row.after ?? null,
      created_at: now,
    });
  }
  return rows;
}

function buildScriptReviewRecords(research) {
  const feedback = research?.feedback?.sentences ?? {};
  const now = new Date().toISOString();
  const rows = [];
  for (const row of feedback.accepted ?? []) {
    rows.push({
      slide_idx: row.value?.slide_idx ?? null,
      sentence_id: row.id ?? row.value?.id ?? null,
      review_step: "script_review",
      before_text: row.value?.text ?? null,
      after_text: row.value?.text ?? null,
      changed_fields: [],
      created_at: now,
    });
  }
  for (const row of feedback.modified ?? []) {
    rows.push({
      slide_idx: row.after?.slide_idx ?? row.before?.slide_idx ?? null,
      sentence_id: row.id ?? row.after?.id ?? row.before?.id ?? null,
      review_step: "script_review",
      before_text: row.before?.text ?? null,
      after_text: row.after?.text ?? null,
      changed_fields: row.changed_fields ?? [],
      created_at: now,
    });
  }
  for (const row of feedback.removed ?? []) {
    rows.push({
      slide_idx: row.before?.slide_idx ?? null,
      sentence_id: row.id ?? row.before?.id ?? null,
      review_step: "script_review",
      before_text: row.before?.text ?? null,
      after_text: null,
      changed_fields: ["removed"],
      created_at: now,
    });
  }
  for (const row of feedback.added ?? []) {
    rows.push({
      slide_idx: row.after?.slide_idx ?? null,
      sentence_id: row.id ?? row.after?.id ?? null,
      review_step: "script_review",
      before_text: null,
      after_text: row.after?.text ?? null,
      changed_fields: ["added"],
      created_at: now,
    });
  }
  return rows;
}

function buildReviewStageSnapshot(state, stage) {
  return {
    stage,
    saved_at: new Date().toISOString(),
    slides: (state.slides ?? []).map((slide, idx) => ({
      id: slide.id ?? `sl${idx}`,
      title: slide.title ?? "",
      width: slide.width ?? null,
      height: slide.height ?? null,
      aspect_ratio: slide.aspect_ratio ?? null,
    })),
    sentences: state.sents ?? [],
    highlights: state.hls ?? [],
    total_duration: state.totDur ?? 0,
    mode: state.appMode,
    settings: {
      detail: DETAIL_VALS[state.detail],
      difficulty: DIFF_VALS[state.level],
      preview_mode: state.prevMode,
      play_speed: state.playSpeed,
    },
  };
}

function buildReviewFlow(state, settings) {
  const layoutEnabled = state.appMode === "hl" && isReviewEnabled(settings?.layout_review_mode);
  const scriptEnabled = isReviewEnabled(settings?.script_review_mode);
  if (!layoutEnabled && !scriptEnabled) {
    return { ...DEFAULT_REVIEW_FLOW };
  }
  return {
    active: true,
    stage: layoutEnabled ? "layout" : "script",
    layoutEnabled,
    scriptEnabled,
  };
}

function reviewStageCopy(stage, appMode = "hl") {
  switch (stage) {
    case "layout":
      return {
        title: "領域確認ステップ",
        description: "まずは LP が生成した領域だけを確認します。枠の追加・移動・削除・種類変更をここで済ませます。",
        actionLabel: "領域確認を完了",
      };
    case "layout_waiting_script":
      return {
        title: "台本生成待ち",
        description: "領域確認は完了しています。裏で進んでいる台本生成が終わると、自動で次の確認ステップへ進みます。",
        actionLabel: "台本生成を待機中...",
      };
    case "script":
      return {
        title: "台本確認ステップ",
        description: appMode === "hl"
          ? "次に台本だけを確認します。文章やタイミングの調整に集中し、領域の操作はここでは固定します。"
          : "台本の文章とタイミングを確認します。完了後に確認済み台本の音声付きプレビューを準備します。",
        actionLabel: "台本確認を完了",
      };
    case "assignment_generating":
      return {
        title: "対応付け生成中",
        description: "確認済みの領域と台本を使って、バックエンドで対応関係を生成しています。",
        actionLabel: "対応付け生成中...",
      };
    case "assignment":
      return {
        title: "対応確認ステップ",
        description: "領域確認で確定した枠を基準に、台本との対応だけを確認します。領域の位置や種類はここでは固定します。",
        actionLabel: "対応確認を完了",
      };
    default:
      return null;
  }
}

function reviewTransitionStatusMessage(fromStage, toStage) {
  if (fromStage === "layout" && toStage === "layout_waiting_script") {
    return "領域確認が完了しました。台本生成が終わるまで待機しています";
  }
  if (fromStage === "layout" && toStage === "script") {
    return "領域確認が完了しました。台本確認ステップに進みました";
  }
  if (fromStage === "layout" && toStage === "assignment") {
    return "領域確認が完了しました。対応確認ステップに進みました";
  }
  if (fromStage === "script" && toStage === "assignment") {
    return "台本確認が完了しました。領域と台本の対応確認ステップに進みました";
  }
  if (fromStage === "layout_waiting_script" && toStage === "assignment") {
    return "台本生成が完了しました。確認済み領域と台本から対応確認ステップに進みました";
  }
  if (toStage === "assignment_generating") {
    return "確認済みの領域と台本を使って、対応付けを生成しています";
  }
  if (toStage === "completed") {
    return "確認フローが完了しました。必要に応じて編集・書き出しできます";
  }
  return "生成完了";
}

function deriveProjectName(state, pdfFile, fallback = "編集中のプロジェクト") {
  return state.projectMeta?.name ?? pdfFile?.name?.replace(/\.pdf$/i, "") ?? state.inputPdf?.name?.replace(/\.pdf$/i, "") ?? fallback;
}

function hasProjectWorkspace(state, pdfFile) {
  return Boolean(
    state.generated
    || state.status === "proc"
    || pdfFile
    || state.inputPdf
    || state.projectMeta?.id
    || state.projectMeta?.name
    || state.slides.length
    || state.sents.length
    || state.hls.length
  );
}

function projectRecordId(project) {
  return project?.id ?? project?.data?.project_meta?.id ?? null;
}

function compactErrorMessage(error, fallback = "原因を特定できませんでした") {
  const raw = String(error?.message || error?.responseText || fallback).replace(/\s+/g, " ").trim();
  if (!raw) return fallback;
  return raw.length > 120 ? `${raw.slice(0, 120)}...` : raw;
}

function activeProjectStorageKey(userId) {
  return `${ACTIVE_PROJECT_STORAGE_KEY_BASE}_${userId ?? "anonymous"}`;
}

function rememberActiveProjectId(userId, projectId) {
  if (!userId || !projectId) return;
  try {
    localStorage.setItem(activeProjectStorageKey(userId), projectId);
  } catch {
    // localStorage が使えない環境でも保存処理自体は継続する。
  }
}

function readActiveProjectId(userId) {
  if (!userId) return null;
  try {
    return localStorage.getItem(activeProjectStorageKey(userId));
  } catch {
    return null;
  }
}

function forgetActiveProjectId(userId, projectId = null) {
  if (!userId) return;
  try {
    const key = activeProjectStorageKey(userId);
    if (projectId && localStorage.getItem(key) !== projectId) return;
    localStorage.removeItem(key);
  } catch {
    // localStorage が使えない環境でも編集機能は継続する。
  }
}

function inputPdfMetaFromFile(file, extra = {}) {
  if (!file) return null;
  return {
    name: file.name,
    type: file.type || "application/pdf",
    size: file.size,
    last_modified: file.lastModified ? new Date(file.lastModified).toISOString() : null,
    available: Boolean(extra.available),
    sha256: extra.sha256 ?? null,
    storage_key: extra.storage_key ?? extra.sha256 ?? null,
    artifact_kind: "input_pdf",
    download_url: extra.download_url ?? null,
    local_unsaved: !extra.available,
  };
}

function normalizeInputPdfMeta(meta) {
  if (!meta || typeof meta !== "object") return null;
  return {
    name: meta.name ?? "slides.pdf",
    type: meta.type ?? "application/pdf",
    size: meta.size ?? null,
    last_modified: meta.last_modified ?? null,
    available: Boolean(meta.available),
    sha256: meta.sha256 ?? meta.storage_key ?? null,
    storage_key: meta.storage_key ?? meta.sha256 ?? null,
    artifact_id: meta.artifact_id ?? meta.storage_key ?? null,
    artifact_kind: meta.artifact_kind ?? "input_pdf",
    download_url: meta.download_url ?? null,
  };
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    };
    reader.onerror = () => reject(reader.error || new Error("blob read failed"));
    reader.readAsDataURL(blob);
  });
}

function renameSavedFingerprint(fingerprint, nextMeta) {
  if (!fingerprint) return null;
  try {
    const parsed = JSON.parse(fingerprint);
    parsed.project_meta = {
      ...(parsed.project_meta ?? {}),
      id: nextMeta?.id ?? parsed.project_meta?.id ?? null,
      name: nextMeta?.name ?? parsed.project_meta?.name ?? null,
      created_at: nextMeta?.created_at ?? parsed.project_meta?.created_at ?? null,
    };
    return JSON.stringify(parsed);
  } catch {
    return null;
  }
}

function normalizedProjectStateForFingerprint(state, inputPdf = state.inputPdf) {
  return {
    ...state,
    inputPdf: normalizeInputPdfMeta(inputPdf),
  };
}

function fingerprintSyncedProjectState(state, name, inputPdf = state.inputPdf) {
  return fingerprintProjectState(normalizedProjectStateForFingerprint(state, inputPdf), name);
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
  const latestStateRef = useRef(state);
  latestStateRef.current = state;
  const [pdfFile, setPdfFile]     = useState(null);
  const [tab, setTab]             = useState("editor");
  const [view, setView]           = useState(initialRoute.view);
  const [studioScreen, setStudioScreen] = useState(initialRoute.studioScreen);
  const [authReady, setAuthReady] = useState(false);
  const [authSession, setAuthSession] = useState(null);
  const [reviewSettings, setReviewSettings] = useState(DEFAULT_REVIEW_SETTINGS);
  const [experimentCondition, setExperimentCondition] = useState(null);
  const [reviewFlow, setReviewFlow] = useState(DEFAULT_REVIEW_FLOW);
  const [reviewSavingStage, setReviewSavingStage] = useState(null);
  const [currentJobId, setCurrentJobId] = useState(() => {
    try {
      return sessionStorage.getItem(CURRENT_JOB_STORAGE_KEY) || null;
    } catch {
      return null;
    }
  });
  const [openingProjectId, setOpeningProjectId] = useState(null);
  const hashRestoreAttemptedRef = useRef(false);
  const saveInFlightRef = useRef(null);
  const autosaveInFlightRef = useRef(null);
  const automaticAssignmentStartRef = useRef(null);
  const { toasts, addToast }      = useToast();
  const { confirmProps, requestConfirm, requestPrompt } = useConfirm();
  const { layout, startResizeLeft, startResizeRight, resizingLeft, resizingRight, resetLayout } = useResizableLayout();
  const hasWorkspace = hasProjectWorkspace(state, pdfFile);
  const currentProjectName = deriveProjectName(state, pdfFile, "編集中のプロジェクト");
  const currentProjectFingerprint = hasWorkspace
    ? fingerprintSyncedProjectState(state, currentProjectName)
    : null;
  const hasPersistedSnapshot = Boolean(state.savedFingerprint);
  const isDirty = hasWorkspace && (
    !state.savedFingerprint
    || currentProjectFingerprint !== state.savedFingerprint
  );
  const currentWorkspace =
    hasWorkspace
      ? {
          id: state.projectMeta?.id ?? null,
          name: currentProjectName,
          data: {
            project_meta: state.projectMeta ?? null,
            slides: state.slides,
            sentences: state.sents,
            highlights: state.hls,
            mode: state.appMode,
            status: state.status,
            status_message: state.statusMsg,
            is_dirty: isDirty,
            pdf_name: state.inputPdf?.name ?? pdfFile?.name ?? null,
            input_pdf: state.inputPdf ?? null,
          },
        }
      : null;
  const isAdmin = authSession?.user?.role === "admin";
  const authUserId = authSession?.user?.id ?? null;
  const activeView = view === "admin" && isAdmin ? "admin" : "studio";
  const activeStudioScreen = activeView === "studio" ? studioScreen : "home";
  const reviewBanner = reviewFlow.active ? reviewStageCopy(reviewFlow.stage, state.appMode) : null;
  const scriptReadyForReview = Boolean(
    state.sents.length > 0
    && state.genRef?.partial_stage !== "layout_ready"
  );
  const reviewActionDisabled = Boolean(
    reviewSavingStage
    || reviewFlow.stage === "layout_waiting_script"
    || reviewFlow.stage === "assignment_generating"
  );
  const reviewActionLabel = reviewBanner?.actionLabel ?? "";

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

  useEffect(() => {
    try {
      if (currentJobId) {
        sessionStorage.setItem(CURRENT_JOB_STORAGE_KEY, currentJobId);
      } else {
        sessionStorage.removeItem(CURRENT_JOB_STORAGE_KEY);
      }
    } catch {
      // sessionStorage が使えない環境でも編集機能は継続する。
    }
  }, [currentJobId]);

  const fetchEffectiveReviewSettings = async () => {
    const res = await authFetch("/api/review-settings/current", { method: "GET" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    return payload?.effective ?? DEFAULT_REVIEW_SETTINGS;
  };

  useEffect(() => {
    let active = true;
    if (!authSession?.session_id) {
      setReviewSettings(DEFAULT_REVIEW_SETTINGS);
      setExperimentCondition(null);
      return () => {
        active = false;
      };
    }
    Promise.all([
      fetchEffectiveReviewSettings(),
      authFetch("/api/experiments/current-condition", { method: "GET" })
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        }),
    ])
      .then(([effective, conditionPayload]) => {
        if (!active) return;
        setReviewSettings(effective);
        setExperimentCondition(conditionPayload?.effective ?? null);
      })
      .catch(() => {
        if (!active) return;
        setReviewSettings(DEFAULT_REVIEW_SETTINGS);
        setExperimentCondition(null);
      });
    return () => {
      active = false;
    };
  }, [authSession?.session_id, authSession?.experiment_id]);

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

  const guardGeneratingWorkspace = (message = "生成中はこの操作を実行できません。生成停止または完了後に続けてください") => {
    if (state.status !== "proc") return false;
    addToast("er", message);
    return true;
  };

  const persistProject = async (forcedName = null) => {
    if (autosaveInFlightRef.current) {
      await autosaveInFlightRef.current;
    }
    if (saveInFlightRef.current) {
      addToast("in", "プロジェクトを保存中です");
      return saveInFlightRef.current;
    }
    const savePromise = (async () => {
    const name = forcedName ?? deriveProjectName(state, pdfFile, "新しいプロジェクト");
    let payload = null;
    let stateForSave = { ...state };
    try {
      if (pdfFile) {
        const currentMeta = normalizeInputPdfMeta(state.inputPdf) ?? inputPdfMetaFromFile(pdfFile);
        stateForSave = { ...stateForSave, inputPdf: currentMeta };
      } else {
        stateForSave = { ...stateForSave, inputPdf: normalizeInputPdfMeta(state.inputPdf) };
      }
      payload = buildProjectPayload(stateForSave, name);
      const saved = await saveProject(payload, { pdfFile, checkpoint: true });
      const savedData = saved?.data ?? payload.data;
      const nextMeta = savedData.project_meta ?? payload.data.project_meta;
      const nextInputPdf = normalizeInputPdfMeta(savedData.input_pdf ?? stateForSave.inputPdf);
      try {
        const research = buildResearchSnapshot(state, "project_save", {
          project: nextMeta,
          extensions: {
            save_origin: "project_save",
          },
        });
        const res = await authFetch("/api/research/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: state.sessionId,
            trigger: "project_save",
            mode: state.appMode,
            generation_ref: state.genRef ?? {},
            operation_logs: state.opLogs,
            research,
            settings: {
              detail: DETAIL_VALS[state.detail],
              difficulty: DIFF_VALS[state.level],
              level_index: state.level,
              preview_mode: state.prevMode,
              play_speed: state.playSpeed,
            },
          }),
        });
        if (!res.ok) {
          console.warn("Project research snapshot save failed:", res.status);
        }
      } catch (researchError) {
        console.warn("Project research snapshot save failed:", researchError);
      }
      const committedState = { ...stateForSave, projectMeta: nextMeta, inputPdf: nextInputPdf };
      dispatch({ type: "SET", k: "projectMeta", v: nextMeta });
      dispatch({ type: "SET", k: "inputPdf", v: nextInputPdf });
      dispatch({ type: "SET", k: "savedFingerprint", v: fingerprintSyncedProjectState(committedState, nextMeta?.name ?? name, nextInputPdf) });
      rememberActiveProjectId(authUserId, nextMeta?.id);
      addToast("ok", `プロジェクト「${name}」を保存しました`);
      return saved ?? payload;
    } catch (error) {
      console.warn("Project save failed:", error);
      addToast("er", `プロジェクト保存に失敗しました: ${compactErrorMessage(error)}`);
      throw error;
    }
    })();
    saveInFlightRef.current = savePromise;
    try {
      return await savePromise;
    } finally {
      if (saveInFlightRef.current === savePromise) {
        saveInFlightRef.current = null;
      }
    }
  };

  const ensureLatestDraftSaved = async () => {
    if (saveInFlightRef.current) {
      await saveInFlightRef.current;
    }
    if (autosaveInFlightRef.current) {
      await autosaveInFlightRef.current;
    }
    const currentState = latestStateRef.current;
    const projectId = currentState.projectMeta?.id;
    const baseVersion = Number(currentState.projectMeta?.version_number ?? 0);
    if (!projectId || baseVersion < 1) {
      throw new Error("音声プレビューには保存済みプロジェクトが必要です");
    }
    const name = deriveProjectName(currentState, pdfFile, "編集中のプロジェクト");
    const fingerprint = fingerprintSyncedProjectState(currentState, name);
    if (currentState.savedFingerprint === fingerprint) return null;

    const data = buildProjectData(currentState, name, projectId);
    dispatch({ type: "SET", k: "syncStatus", v: "saving" });
    const syncPromise = saveProjectDraft(projectId, baseVersion, name, data);
    autosaveInFlightRef.current = syncPromise;
    try {
      const saved = await syncPromise;
      const nextMeta = saved.data?.project_meta ?? currentState.projectMeta;
      const nextInputPdf = normalizeInputPdfMeta(saved.data?.input_pdf ?? currentState.inputPdf);
      const committedState = {
        ...currentState,
        projectMeta: nextMeta,
        inputPdf: nextInputPdf,
      };
      dispatch({ type: "SET", k: "projectMeta", v: nextMeta });
      dispatch({ type: "SET", k: "inputPdf", v: nextInputPdf });
      dispatch({
        type: "SET",
        k: "savedFingerprint",
        v: fingerprintSyncedProjectState(committedState, name, nextInputPdf),
      });
      dispatch({ type: "SET", k: "syncStatus", v: "saved" });
      return saved;
    } catch (error) {
      dispatch({ type: "SET", k: "syncStatus", v: error?.status === 409 ? "conflict" : "error" });
      throw error;
    } finally {
      if (autosaveInFlightRef.current === syncPromise) {
        autosaveInFlightRef.current = null;
      }
    }
  };
  const previewPlayback = usePreviewPlayback(state, dispatch, addToast, {
    reviewStage: reviewFlow.active ? reviewFlow.stage : "editor",
    ensureLatestDraftSaved,
  });

  useEffect(() => {
    const projectId = state.projectMeta?.id;
    const baseVersion = Number(state.projectMeta?.version_number ?? 0);
    if (!authSession?.session_id || !projectId || baseVersion < 1 || !isDirty) {
      return undefined;
    }
    const timer = window.setTimeout(async () => {
      if (saveInFlightRef.current || autosaveInFlightRef.current) return;
      const name = deriveProjectName(state, pdfFile, "新しいプロジェクト");
      const data = buildProjectData(state, name, projectId);
      dispatch({ type: "SET", k: "syncStatus", v: "saving" });
      const syncPromise = saveProjectDraft(projectId, baseVersion, name, data);
      autosaveInFlightRef.current = syncPromise;
      try {
        const saved = await syncPromise;
        const nextMeta = saved.data?.project_meta ?? state.projectMeta;
        const nextInputPdf = normalizeInputPdfMeta(saved.data?.input_pdf ?? state.inputPdf);
        const committedState = { ...state, projectMeta: nextMeta, inputPdf: nextInputPdf };
        dispatch({ type: "SET", k: "projectMeta", v: nextMeta });
        dispatch({ type: "SET", k: "inputPdf", v: nextInputPdf });
        dispatch({
          type: "SET",
          k: "savedFingerprint",
          v: fingerprintSyncedProjectState(committedState, name, nextInputPdf),
        });
        dispatch({ type: "SET", k: "syncStatus", v: "saved" });
      } catch (error) {
        console.warn("Project autosave failed:", error);
        dispatch({ type: "SET", k: "syncStatus", v: error?.status === 409 ? "conflict" : "error" });
        addToast(
          "er",
          error?.status === 409
            ? "別画面の保存と競合しました．再読み込みして内容を確認してください"
            : "自動保存に失敗しました．編集内容は保存されていません",
        );
      } finally {
        if (autosaveInFlightRef.current === syncPromise) {
          autosaveInFlightRef.current = null;
        }
      }
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [
    authSession?.session_id,
    currentProjectFingerprint,
    isDirty,
    state.projectMeta?.id,
    state.projectMeta?.version_number,
    state.status,
  ]);

  const clearReviewFlow = () => {
    setReviewFlow(DEFAULT_REVIEW_FLOW);
  };

  const closeWorkspace = (historyMode = "replace") => {
    forgetActiveProjectId(authUserId, state.projectMeta?.id);
    dispatch({ type: "RESET" });
    setCurrentJobId(null);
    setPdfFile(null);
    clearReviewFlow();
    setTab("editor");
    setStudioRoute("home", historyMode);
  };

  const startReviewFlow = (generatedData = null, settingsOverride = null) => {
    if (experimentCondition?.review_flow_enabled === false) {
      setReviewFlow(DEFAULT_REVIEW_FLOW);
      return;
    }
    const nextState = generatedData
      ? {
          ...state,
          appMode: generatedData.mode ?? state.appMode,
          hls: generatedData.highlights ?? [],
          sents: generatedData.sentences ?? [],
          generated: true,
          genRef: generatedData.generation_ref ?? state.genRef,
        }
      : state;
    const next = buildReviewFlow(nextState, settingsOverride ?? reviewSettings);
    setReviewFlow(next);
    if (generatedData?.generation_ref) {
      dispatch({ type: "SET", k: "genRef", v: generatedData.generation_ref });
    }
    dispatch({ type: "SET", k: "drawMode", v: false });
    dispatch({ type: "SET", k: "drawSentId", v: null });
    if (next.stage === "script") {
      dispatch({ type: "SET", k: "selHl", v: null });
    }
  };

  const ensureProjectMetaForReview = async () => {
    let projectMeta = state.projectMeta;
    if (!projectMeta?.id) {
      const saved = await persistProject(deriveProjectName(state, pdfFile, "確認済みプロジェクト"));
      projectMeta = saved?.data?.project_meta ?? saved?.project_meta ?? projectMeta;
    }
    if (!projectMeta?.id) {
      throw new Error("確認結果を保存するプロジェクトIDがありません");
    }
    return projectMeta;
  };

  const persistReviewStage = async (stage) => {
    if (stage !== "layout" && stage !== "script" && stage !== "assignment") return;
    const projectMeta = await ensureProjectMetaForReview();
    if (saveInFlightRef.current) {
      await saveInFlightRef.current;
    }
    if (autosaveInFlightRef.current) {
      await autosaveInFlightRef.current;
    }
    const currentState = latestStateRef.current;
    const currentName = deriveProjectName(currentState, pdfFile, "確認済みプロジェクト");
    const synced = await saveProjectDraft(
      projectMeta.id,
      Number(currentState.projectMeta?.version_number ?? projectMeta.version_number ?? 1),
      currentName,
      buildProjectData(currentState, currentName, projectMeta.id),
    );
    const syncedMeta = synced.data?.project_meta ?? currentState.projectMeta;
    dispatch({ type: "SET", k: "projectMeta", v: syncedMeta });
    dispatch({
      type: "SET",
      k: "savedFingerprint",
      v: fingerprintProjectData(synced.data ?? {}),
    });
    const runId = synced.active_run_id
      ?? currentState.genRef?.run_id
      ?? state.genRef?.run_id;
    if (!runId) {
      throw new Error("確認対象の生成runがありません");
    }

    const trigger = stage === "layout"
      ? "layout_review_complete"
      : stage === "script"
        ? "script_review_complete"
        : "assignment_review_complete";
    const research = buildResearchSnapshot(state, trigger, { project: projectMeta });
    const stageRes = await authFetch(`/api/projects/${projectMeta.id}/review-stages/${stage}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: runId,
        draft_version: synced.draft_version,
      }),
    });
    if (!stageRes.ok) {
      throw new Error(`HTTP ${stageRes.status}`);
    }
    if (stage === "script") {
      dispatch({ type: "SET_PREVIEW_AUDIO_STALE", v: true });
      submitPreviewAudio({
          project_id: projectMeta.id,
          run_id: runId,
          scope: "all",
          sentences: currentState.sents,
          generation_ref: { ...(currentState.genRef ?? {}), run_id: runId },
          settings: {
            detail: DETAIL_VALS[currentState.detail],
            difficulty: DIFF_VALS[currentState.level],
            preview_mode: currentState.prevMode,
            play_speed: currentState.playSpeed,
          },
      })
        .then(() => addToast("in", "確認済み台本の音声を先行生成しています"))
        .catch((error) => {
          console.warn("Preview audio warmup failed:", error);
          addToast("in", "音声プレビューは再生時に準備します");
        });
    }
    if (stage === "assignment") return;

    const records = stage === "layout"
      ? buildLayoutReviewRecords(research)
      : buildScriptReviewRecords(research);
    if (!records.length) return;
    const endpoint = stage === "layout"
      ? `/api/projects/${projectMeta.id}/layout-review`
      : `/api/projects/${projectMeta.id}/script-review`;
    const res = await authFetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records }),
    });
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
  };

  const generateReviewAssignment = async () => {
    const projectMeta = await ensureProjectMetaForReview();
    const runId = latestStateRef.current.genRef?.run_id ?? state.genRef?.run_id;
    if (!runId) throw new Error("対応付け対象の生成runがありません");
    const res = await authFetch(`/api/projects/${projectMeta.id}/review-assignment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      let detail = text;
      try {
        const payload = JSON.parse(text);
        detail = payload?.error?.message || payload?.detail?.message || payload?.detail || payload?.error?.code || text;
      } catch {
        detail = text;
      }
      throw new Error(`HTTP ${res.status}${detail ? `: ${String(detail).slice(0, 240)}` : ""}`);
    }
    const submitted = await res.json();
    if (!submitted?.job_id) {
      return submitted;
    }

    let job = submitted;
    while (job?.status === "queued" || job?.status === "running") {
      dispatch({
        type: "SET",
        k: "statusMsg",
        v: job.message || "対応付け生成中...",
      });
      await new Promise((resolve) => setTimeout(resolve, 2000));
      const jobRes = await authFetch(`/api/jobs/${submitted.job_id}`);
      if (!jobRes.ok) {
        const text = await jobRes.text().catch(() => "");
        throw new Error(`HTTP ${jobRes.status}${text ? `: ${text.slice(0, 240)}` : ""}`);
      }
      job = await jobRes.json();
    }

    if (job?.status === "completed" && job.result) {
      return job.result;
    }
    throw new Error(job?.error?.message || job?.message || "対応付け生成ジョブが失敗しました");
  };

  const startReviewAssignmentGeneration = async (fromStage) => {
    dispatch({ type: "SET", k: "drawMode", v: false });
    dispatch({ type: "SET", k: "drawSentId", v: null });
    dispatch({ type: "SET", k: "selHl", v: null });
    dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage(fromStage, "assignment_generating") });
    dispatch({
      type: "APP_LOG",
      message: "確認済み領域と確認済み台本を使って、バックエンドで対応付け生成を開始しました",
      meta: { type: "review_assignment_generation_started", from_stage: fromStage, generation_ref: state.genRef },
    });
    setReviewFlow((current) => (
      current.active
        ? { ...current, stage: "assignment_generating" }
        : current
    ));
    setReviewSavingStage("assignment_generating");
    try {
      const assignment = await generateReviewAssignment();
      dispatch({ type: "APPLY_REVIEW_ASSIGNMENT", d: assignment });
      if (Number(assignment.draft_version) > 0) {
        dispatch({
          type: "SET",
          k: "projectMeta",
          v: {
            ...(latestStateRef.current.projectMeta ?? {}),
            version_number: Number(assignment.draft_version),
          },
        });
      }
      dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage(fromStage, "assignment") });
      setReviewFlow((current) => (
        current.active && current.stage === "assignment_generating"
          ? { ...current, stage: "assignment" }
          : current
      ));
      addToast("ok", "確認済みの領域と台本で対応付けを生成しました");
    } catch (error) {
      console.error("Review assignment generation failed:", error);
      setReviewFlow((current) => (
        current.active && current.stage === "assignment_generating"
          ? { ...current, stage: fromStage === "layout_waiting_script" ? "layout_waiting_script" : fromStage }
          : current
      ));
      addToast("er", `対応付け生成に失敗しました: ${compactErrorMessage(error)}。確認済みデータは残っています`);
    } finally {
      setReviewSavingStage(null);
    }
  };

  const advanceReviewFlow = async () => {
    if (!reviewFlow.active || reviewSavingStage) return;
    if (reviewFlow.stage === "layout_waiting_script" || reviewFlow.stage === "assignment_generating") return;
    if (reviewFlow.stage === "layout" || reviewFlow.stage === "script" || reviewFlow.stage === "assignment") {
      setReviewSavingStage(reviewFlow.stage);
      try {
        await persistReviewStage(reviewFlow.stage);
      } catch (error) {
        console.warn("Review stage save failed:", error);
        addToast("er", "確認結果の保存に失敗したため，次の工程には進みません．保存状態を確認して再実行してください");
        return;
      } finally {
        setReviewSavingStage(null);
      }
    }
    if (reviewFlow.stage === "layout") {
      const nextStage = reviewFlow.scriptEnabled ? "script" : "assignment";
      if (!scriptReadyForReview) {
        dispatch({ type: "SET", k: "drawMode", v: false });
        dispatch({ type: "SET", k: "drawSentId", v: null });
        dispatch({ type: "SET", k: "selHl", v: null });
        dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage("layout", "layout_waiting_script") });
        dispatch({
          type: "APP_LOG",
          message: "領域確認が完了しました。台本生成完了後に次の確認ステップへ進みます",
          meta: { type: "layout_review_completed_waiting_script", generation_ref: state.genRef },
        });
        setReviewFlow({ ...reviewFlow, stage: "layout_waiting_script" });
        addToast("ok", "領域確認を完了しました。台本生成が終わったら自動で進みます");
        return;
      }
      dispatch({
        type: "APP_LOG",
        message: "領域確認中に生成済みの台本を使って次の確認ステップへ進みました",
        meta: { type: "script_background_result_used", generation_ref: state.genRef },
      });
      dispatch({ type: "SET", k: "drawMode", v: false });
      dispatch({ type: "SET", k: "drawSentId", v: null });
      if (nextStage === "script") {
        dispatch({ type: "SET", k: "selHl", v: null });
        dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage("layout", nextStage) });
        setReviewFlow({ ...reviewFlow, stage: nextStage });
      } else {
        await persistReviewStage("script");
        await startReviewAssignmentGeneration("layout");
      }
      return;
    }
    if (reviewFlow.stage === "script") {
      if (state.appMode === "hl") {
        await startReviewAssignmentGeneration("script");
        return;
      }
      dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage("script", "completed") });
      setReviewFlow(DEFAULT_REVIEW_FLOW);
      addToast("ok", "台本確認を完了しました．音声付きプレビューを準備しています");
      return;
    }
    dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage(reviewFlow.stage, "completed") });
    setReviewFlow(DEFAULT_REVIEW_FLOW);
  };

  useEffect(() => {
    if (!reviewFlow.active || reviewFlow.stage !== "layout_waiting_script") return;
    if (!scriptReadyForReview) return;
    const nextStage = reviewFlow.scriptEnabled ? "script" : "assignment";
    dispatch({
      type: "APP_LOG",
      message: "待機していた台本生成結果を使って次の確認ステップへ進みました",
      meta: { type: "script_background_result_used_after_layout_wait", generation_ref: state.genRef },
    });
    dispatch({ type: "SET", k: "drawMode", v: false });
    dispatch({ type: "SET", k: "drawSentId", v: null });
    if (nextStage === "script") {
      dispatch({ type: "SET", k: "selHl", v: null });
      dispatch({ type: "SET", k: "statusMsg", v: reviewTransitionStatusMessage("layout", nextStage) });
      setReviewFlow((current) => (
        current.active && current.stage === "layout_waiting_script"
          ? { ...current, stage: nextStage }
          : current
      ));
      addToast("ok", "台本確認ステップに進みました");
    } else {
      const transitionKey = `${state.genRef?.run_id ?? "unknown"}:layout_waiting_script`;
      if (automaticAssignmentStartRef.current === transitionKey) return;
      automaticAssignmentStartRef.current = transitionKey;
      setReviewSavingStage("script");
      (async () => {
        try {
          await persistReviewStage("script");
          await startReviewAssignmentGeneration("layout_waiting_script");
        } catch (error) {
          automaticAssignmentStartRef.current = null;
          setReviewSavingStage(null);
          console.warn("Automatic script checkpoint failed:", error);
          addToast("er", "台本の自動確定に失敗しました．もう一度確認操作を行ってください");
        }
      })();
    }
  }, [reviewFlow.active, reviewFlow.stage, reviewFlow.scriptEnabled, scriptReadyForReview, state.genRef]);

  const saveCurrentProject = (afterSave = null) => {
    if (state.projectMeta?.name) {
      persistProject(state.projectMeta.name)
        .then(() => afterSave?.())
        .catch(() => {});
      return;
    }
    const defaultName = pdfFile?.name?.replace(/\.pdf$/i, "") ?? state.inputPdf?.name?.replace(/\.pdf$/i, "") ?? "新しいプロジェクト";
    requestPrompt({
      title: "プロジェクトを保存",
      message: "保存するプロジェクト名を入力してください。",
      confirmLabel: "保存する",
      inputLabel: "プロジェクト名",
      inputInitialValue: defaultName,
      inputPlaceholder: "例: パターン認識の講義",
      onConfirm: async (value) => {
        const name = String(value ?? "").trim();
        if (!name) {
          addToast("er", "プロジェクト名を入力してください");
          return false;
        }
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
    if (saveInFlightRef.current) {
      addToast("in", "保存完了後に続けます");
      saveInFlightRef.current
        .then(() => proceed())
        .catch(() => {});
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
    if (guardGeneratingWorkspace("生成中はリセットできません。先に生成を停止してください")) return;
    if (!hasWorkspace) {
      dispatch({ type: "RESET" });
      setCurrentJobId(null);
      setPdfFile(null);
      clearReviewFlow();
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
          closeWorkspace("replace");
        },
      });
    }, "リセット");
  };

  const initializeServerProject = async (nextPdfFile = null) => {
    const projectName = nextPdfFile?.name?.replace(/\.pdf$/i, "") ?? "新しいプロジェクト";
    const created = await createProject(projectName, authSession?.experiment_id ? "research" : "general");
    let project = created;
    if (nextPdfFile) {
      await uploadProjectPdf(created.id, nextPdfFile);
      project = await loadProject(created.id);
    }
    dispatch({ type: "RESET" });
    setCurrentJobId(null);
    setPdfFile(nextPdfFile);
    dispatch({ type: "SET", k: "projectMeta", v: project.data?.project_meta ?? {
      id: project.id,
      name: project.name,
      created_at: project.created_at,
      updated_at: project.updated_at,
      version_number: project.draft_version,
    } });
    dispatch({ type: "SET", k: "inputPdf", v: normalizeInputPdfMeta(project.data?.input_pdf) });
    dispatch({ type: "SET", k: "savedFingerprint", v: fingerprintProjectData(project.data ?? {}) });
    rememberActiveProjectId(authUserId, project.id);
    clearReviewFlow();
    setTab("editor");
    setStudioRoute("editor");
    addToast("ok", nextPdfFile
      ? `プロジェクトを作成し，PDF「${nextPdfFile.name}」を保存しました`
      : "空のプロジェクトを作成しました");
    return project;
  };

  const handleCreateProject = (nextPdfFile = null) => {
    if (guardGeneratingWorkspace("生成中は新しいプロジェクトを開始できません。先に生成を停止してください")) return;
    confirmDirtyAction(() => {
      initializeServerProject(nextPdfFile).catch((error) => {
        console.warn("Project initialization failed:", error);
        addToast("er", error.message || "プロジェクトを作成できませんでした");
      });
    }, "新規作成");
  };

  const restoreProjectPdfFile = async (project) => {
    const inputPdf = normalizeInputPdfMeta(project?.data?.input_pdf);
    if (!inputPdf?.available || !inputPdf?.download_url) {
      return { inputPdf, file: null, restored: false };
    }
    const res = await authFetch(inputPdf.download_url, { method: "GET" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const parsedLastModified = inputPdf?.last_modified ? Date.parse(inputPdf.last_modified) : NaN;
    const file = new File(
      [blob],
      inputPdf.name || `${project.name ?? "slides"}.pdf`,
      {
        type: inputPdf?.type || "application/pdf",
        lastModified: Number.isFinite(parsedLastModified) ? parsedLastModified : Date.now(),
      },
    );
    return { inputPdf: inputPdf ?? inputPdfMetaFromFile(file, { available: true }), file, restored: true };
  };

  const hydrateProjectSlideImages = async (project) => {
    const projectId = projectRecordId(project);
    const slides = Array.isArray(project?.data?.slides) ? project.data.slides : [];
    if (!projectId || slides.length === 0) return project;

    let restoredCount = 0;
    const hydratedSlides = await Promise.all(slides.map(async (slide, idx) => {
      if (!slide || typeof slide !== "object" || slide.image_base64) return slide;
      try {
        if (!slide.image_url) return slide;
        const res = await authFetch(slide.image_url, { method: "GET" });
        if (!res.ok) return slide;
        const imageBase64 = await blobToBase64(await res.blob());
        if (!imageBase64) return slide;
        restoredCount += 1;
        return {
          ...slide,
          image_base64: imageBase64,
          image_available: true,
          image_url: slide.image_url,
        };
      } catch (error) {
        console.warn(`Project slide image restore failed: slide=${idx + 1}`, error);
        return slide;
      }
    }));

    if (restoredCount === 0) return project;
    return {
      ...project,
      data: {
        ...project.data,
        slides: hydratedSlides,
      },
    };
  };

  const openProjectRecord = async (project, { silent = false, preserveJob = false } = {}) => {
    if (!project?.data) {
      throw new Error("プロジェクト本体を読み込めませんでした");
    }
    const projectId = project.id ?? project.data?.project_meta?.id ?? null;
    setOpeningProjectId(projectId ?? "opening");
    try {
      let projectToOpen = project;
      let restored = { inputPdf: normalizeInputPdfMeta(project.data.input_pdf), file: null, restored: false };
      try {
        restored = await restoreProjectPdfFile(project);
      } catch (error) {
        console.warn("Project PDF restore failed:", error);
        addToast("er", "保存済みPDFの復元に失敗しました。プロジェクトは開きますが，PDFは再選択してください");
      }
      projectToOpen = await hydrateProjectSlideImages(projectToOpen);
      const restoredInputPdf = restored.inputPdf ?? normalizeInputPdfMeta(projectToOpen.data.input_pdf);
      dispatch({ type: "LOAD", d: projectToOpen.data, markSaved: true });
      if (!preserveJob) setCurrentJobId(null);
      setPdfFile(restored.file);
      dispatch({ type: "SET", k: "inputPdf", v: restoredInputPdf });
      dispatch({
        type: "SET",
        k: "savedFingerprint",
        v: fingerprintProjectData({
          ...projectToOpen.data,
          input_pdf: restoredInputPdf,
        }),
      });
      clearReviewFlow();
      setTab("editor");
      setStudioRoute("editor", silent ? "replace" : "push");
      rememberActiveProjectId(authUserId, projectId);
      if (!silent) {
        addToast("ok", restored.file
          ? `プロジェクト「${project.name}」とPDFを読み込みました`
          : `プロジェクト「${project.name}」を読み込みました`);
      }
    } finally {
      setOpeningProjectId(null);
    }
  };

  const handleOpenProject = (project) => {
    if (!project?.data) return;
    const nextProjectId = projectRecordId(project);
    const currentProjectId = state.projectMeta?.id ?? null;
    const openingCurrentProject = Boolean(nextProjectId && currentProjectId && nextProjectId === currentProjectId);
    if (openingCurrentProject) {
      setStudioRoute("editor");
      return;
    }
    if (guardGeneratingWorkspace("生成中は別のプロジェクトを開けません。先に生成を停止してください")) return;
    confirmDirtyAction(() => {
      openProjectRecord(project).catch((error) => {
        console.warn("Project open failed:", error);
        addToast("er", error.message || "プロジェクトを開けませんでした");
      });
    }, "別のプロジェクトを開く");
  };

  const handleSelectPdf = (nextPdfFile) => {
    if (guardGeneratingWorkspace("生成中は PDF を変更できません。先に生成を停止してください")) return;
    if (!nextPdfFile) {
      setPdfFile(null);
      dispatch({ type: "SET", k: "inputPdf", v: null });
      return;
    }
    if (!hasWorkspace) {
      initializeServerProject(nextPdfFile).catch((error) => {
        console.warn("PDF project initialization failed:", error);
        addToast("er", error.message || "PDFを保存できませんでした");
      });
      return;
    }
    confirmDirtyAction(() => {
      initializeServerProject(nextPdfFile).catch((error) => {
        console.warn("PDF project initialization failed:", error);
        addToast("er", error.message || "PDFを保存できませんでした");
      });
    }, "別の PDF を選択");
  };

  useEffect(() => {
    if (!authSession?.session_id || !authUserId) return undefined;
    if (activeStudioScreen !== "editor" || hasWorkspace || currentJobId) return undefined;
    if (hashRestoreAttemptedRef.current) return undefined;
    hashRestoreAttemptedRef.current = true;

    const projectId = readActiveProjectId(authUserId);
    if (!projectId) {
      addToast("in", "開いていた保存済みプロジェクトが見つからないため，ホームに戻しました");
      setStudioRoute("home", "replace");
      return undefined;
    }

    let active = true;
    setOpeningProjectId(projectId);
    loadProject(projectId)
      .then((project) => {
        if (!active) return;
        if (!project) {
          forgetActiveProjectId(authUserId, projectId);
          setOpeningProjectId(null);
          addToast("er", "前回のプロジェクトを読み込めませんでした。ホームから開き直してください");
          setStudioRoute("home", "replace");
          return;
        }
        openProjectRecord(project, { silent: true }).catch((error) => {
          if (!active) return;
          forgetActiveProjectId(authUserId, projectId);
          console.warn("Initial project restore failed:", error);
          addToast("er", error.message || "前回のプロジェクトを復元できませんでした");
          setStudioRoute("home", "replace");
        });
      })
      .catch((error) => {
        if (!active) return;
        setOpeningProjectId(null);
        forgetActiveProjectId(authUserId, projectId);
        console.warn("Initial project load failed:", error);
        addToast("er", error.message || "前回のプロジェクトを読み込めませんでした");
        setStudioRoute("home", "replace");
      });

    return () => {
      active = false;
    };
  }, [authSession?.session_id, authUserId, activeStudioScreen, hasWorkspace, currentJobId]);

  useEffect(() => {
    if (!authSession?.session_id || !currentJobId || state.status === "proc") return undefined;
    let active = true;
    const resumeJob = async () => {
      try {
        addToast("in", "中断された生成ジョブを確認しています...");
        let job = null;
        let restoredProjectId = null;
        dispatch({ type: "SET", k: "status", v: "proc" });
        dispatch({ type: "SET", k: "showProg", v: true });
        dispatch({ type: "SET", k: "statusMsg", v: "生成ジョブを復帰中..." });
        while (active) {
          const res = await authFetch(`/api/jobs/${currentJobId}`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          job = await res.json();
          const jobProjectId = job?.payload?.project_id ?? null;
          if (jobProjectId && restoredProjectId !== jobProjectId) {
            const project = await loadProject(jobProjectId);
            await openProjectRecord(project, { silent: true, preserveJob: true });
            restoredProjectId = jobProjectId;
            dispatch({ type: "SET", k: "status", v: "proc" });
            dispatch({ type: "SET", k: "showProg", v: true });
          }
          dispatch({ type: "SET", k: "progress", v: Math.max(20, Number(job.progress ?? 20)) });
          dispatch({ type: "SET", k: "statusMsg", v: job.message || "バックエンドで生成中..." });
          if (job.status !== "queued" && job.status !== "running") break;
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
        if (!active || !job) return;
        if (job.status === "completed" && job.result) {
          const completedProjectId = job?.payload?.project_id ?? restoredProjectId;
          let restoredData = job.result;
          if (completedProjectId) {
            const project = await loadProject(completedProjectId);
            await openProjectRecord(project, { silent: true });
            restoredData = project.data;
          } else {
            dispatch({ type: "LOAD", d: job.result });
          }
          dispatch({ type: "SET", k: "progress", v: 100 });
          dispatch({ type: "SET", k: "status", v: "done" });
          dispatch({ type: "SET", k: "statusMsg", v: "生成完了" });
          setCurrentJobId(null);
          addToast("ok", "中断された生成結果を復帰しました");
          let effectiveReviewSettings = reviewSettings;
          try {
            effectiveReviewSettings = await fetchEffectiveReviewSettings();
            setReviewSettings(effectiveReviewSettings);
          } catch {
            // 設定取得に失敗した場合は、現在保持している設定で判定する。
          }
          if (isReviewEnabled(effectiveReviewSettings?.layout_review_mode) || isReviewEnabled(effectiveReviewSettings?.script_review_mode)) {
            startReviewFlow(restoredData, effectiveReviewSettings);
          }
          return;
        }
        dispatch({ type: "SET", k: "status", v: job.status === "cancelled" ? "stop" : "err" });
        dispatch({ type: "SET", k: "statusMsg", v: job.error?.message || job.message || "生成ジョブを復帰できませんでした" });
        setCurrentJobId(null);
      } catch (error) {
        if (!active) return;
        dispatch({ type: "SET", k: "status", v: "err" });
        dispatch({ type: "SET", k: "statusMsg", v: error.message || "生成ジョブの復帰に失敗しました" });
        setCurrentJobId(null);
        addToast("er", error.message || "生成ジョブの復帰に失敗しました");
      } finally {
        if (active) {
          setTimeout(() => dispatch({ type: "SET", k: "showProg", v: false }), 800);
        }
      }
    };
    resumeJob();
    return () => {
      active = false;
    };
  }, [authSession?.session_id, currentJobId]);

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
      if (activeView === "admin" || activeStudioScreen === "home") return;
      if (["INPUT", "TEXTAREA"].includes(e.target.tagName) || e.target.contentEditable === "true") return;
      if (confirmProps.open) return;
      const editorLockedByGeneration = state.status === "proc" && !reviewFlow.active;
      if ((e.metaKey || e.ctrlKey) && e.code === "KeyZ" && !e.shiftKey) {
        e.preventDefault();
        if (editorLockedByGeneration) return;
        dispatch({ type: "UNDO" });
        return;
      }
      if (
        ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === "KeyZ")
        || ((e.ctrlKey || e.metaKey) && e.code === "KeyY")
      ) {
        e.preventDefault();
        if (editorLockedByGeneration) return;
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
          dispatch({ type: "SEEK_SLIDE", v: Math.min(state.slides.length - 1, state.curSl + 1) });
          break;
        case "KeyP":
        case "PageUp":
        case "ArrowLeft":
        case "ArrowUp":
        case "Backspace":
          e.preventDefault();
          dispatch({ type: "SEEK_SLIDE", v: Math.max(0, state.curSl - 1) });
          break;
        case "Home":
          e.preventDefault();
          dispatch({ type: "SEEK_SLIDE", v: 0 });
          break;
        case "End":
          e.preventDefault();
          dispatch({ type: "SEEK_SLIDE", v: Math.max(0, state.slides.length - 1) });
          break;
        case "F5":
          e.preventDefault();
          if (e.shiftKey) {
            dispatch({ type: "SEEK", v: currentSlideStart });
          } else {
            dispatch({ type: "SEEK_SLIDE", v: 0 });
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
          if (editorLockedByGeneration) {
            e.preventDefault();
            return;
          }
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
  }, [state.playing, state.curSl, state.slides.length, state.selHl, state.status, reviewFlow.active, confirmProps.open, activeView, activeStudioScreen]);

  const switchView = (nextView) => {
    if (nextView === "admin") {
      if (!isAdmin) return;
      setAdminRoute();
      return;
    }
    setStudioRoute(hasWorkspace ? "editor" : "home");
  };

  const handleLogout = () => {
    if (guardGeneratingWorkspace("生成中はログアウトできません。先に生成を停止してください")) return;
    const run = async () => {
      try {
        await logoutUser();
        setAuthSession(null);
        setReviewSettings(DEFAULT_REVIEW_SETTINGS);
        clearReviewFlow();
        setView("studio");
        setStudioScreen("home");
        setCurrentJobId(null);
        dispatch({ type: "RESET" });
        setPdfFile(null);
        addToast("ok", "ログアウトしました");
      } catch (error) {
        console.warn("Logout failed:", error);
        addToast("er", error.message || "ログアウトに失敗しました。ページを再読み込みしてからもう一度試してください");
      }
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
              {activeView === "admin"
                ? "ADMIN OVERVIEW"
                : activeStudioScreen === "home"
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
                background: activeView === key ? "var(--ac)" : "transparent",
                color: activeView === key ? "#fff" : "var(--ts)",
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
          {experimentCondition && (
            <div title="現在の実験条件" style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px", borderRadius: 999, background: "rgba(76,175,130,.10)", border: "1px solid rgba(76,175,130,.25)", color: "var(--gr)", fontSize: 9 }}>
              <span>KG: {experimentCondition.kg_mode ?? "off"}</span>
              <span>ログ: {experimentCondition.log_reuse_enabled ? "ON" : "OFF"}</span>
            </div>
          )}
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
        {activeView === "studio" && activeStudioScreen === "editor" && (
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
      {activeView === "admin" ? (
        <div style={{ flex: 1, minHeight: 0 }}>
          <AdminDashboard addToast={addToast} />
        </div>
      ) : activeStudioScreen === "home" ? (
        <ProjectHome
          onCreateProject={handleCreateProject}
          onOpenProject={handleOpenProject}
          onResumeEditing={() => setStudioRoute("editor")}
          onStoredProjectRenamed={(projectId, nextName) => {
            if (state.projectMeta?.id !== projectId) return;
            const nextMeta = {
              ...(state.projectMeta ?? {}),
              id: projectId,
              name: nextName,
            };
            dispatch({ type: "SET", k: "projectMeta", v: nextMeta });
            dispatch({ type: "SET", k: "savedFingerprint", v: renameSavedFingerprint(state.savedFingerprint, nextMeta) });
          }}
          onStoredProjectDeleted={(projectId) => {
            forgetActiveProjectId(authUserId, projectId);
            if (state.projectMeta?.id !== projectId) return;
            closeWorkspace("replace");
          }}
          currentProject={currentWorkspace}
          requestConfirm={requestConfirm}
          requestPrompt={requestPrompt}
          addToast={addToast}
        />
      ) : openingProjectId && !hasWorkspace ? (
        <div style={{ flex: 1, display: "grid", placeItems: "center", color: "var(--ts)", background: "var(--bg)" }}>
          プロジェクトを復元中...
        </div>
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
            currentJobId={currentJobId}
            setCurrentJobId={setCurrentJobId}
            onSelectPdf={handleSelectPdf}
            addToast={addToast}
            requestConfirm={requestConfirm}
            handleReset={handleReset}
            saveProjectNow={saveCurrentProject}
            prepareProjectForGeneration={() => persistProject(currentProjectName)}
            isDirty={isDirty}
            hasPersistedSnapshot={hasPersistedSnapshot}
            reviewSettings={reviewSettings}
            startReviewFlow={startReviewFlow}
            clearReviewFlow={clearReviewFlow}
          />
        </div>

        {/* 左ハンドル */}
        <ResizeHandle onMouseDown={startResizeLeft} resizing={resizingLeft} />

        {/* 中央パネル（残り幅を占有） */}
        <div style={{ flex: 1, minWidth: 0, minHeight: 0, display: "flex", position: "relative", zIndex: 1 }}>
          <CenterPanel
            state={state}
            dispatch={dispatch}
            addToast={addToast}
            requestConfirm={requestConfirm}
            reviewStage={reviewFlow.active ? reviewFlow.stage : "editor"}
            previewPlayback={previewPlayback}
          />
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
            reviewStage={reviewFlow.active ? reviewFlow.stage : "editor"}
            reviewBanner={reviewBanner}
            reviewActionLabel={reviewActionLabel}
            reviewActionDisabled={reviewActionDisabled}
            reviewSavingStage={reviewSavingStage}
            onAdvanceReview={advanceReviewFlow}
            onPlaySentence={previewPlayback.playSentence}
            rightContent={(
              <ExportPanel
                state={state}
                dispatch={dispatch}
                addToast={addToast}
                ensureLatestDraftSaved={ensureLatestDraftSaved}
              />
            )}
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
