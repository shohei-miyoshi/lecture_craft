import { authFetch } from "./sessionStore.js";

function normalizeProjectName(state, pdfFile) {
  return state.projectMeta?.name
    ?? pdfFile?.name?.replace(/\.pdf$/i, "")
    ?? "編集中のワークスペース";
}

function hasRows(value) {
  return Array.isArray(value) && value.length > 0;
}

export function hasPersistableWorkspace(state) {
  return Boolean(
    state.generated
    || hasRows(state.slides)
    || hasRows(state.sents)
    || hasRows(state.hls)
    || state.activeJobId
    || state.status === "proc"
    || state.projectMeta?.id
    || state.projectMeta?.name,
  );
}

export function isHydratableWorkspaceDraft(data) {
  return Boolean(
    data
    && (
      hasRows(data.slides)
      || hasRows(data.sentences)
      || hasRows(data.highlights)
      || data.generation_ref
      || Number(data.total_duration ?? 0) > 0
      || data.active_job_id
      || data.project_meta?.id
      || data.project_meta?.name
      || data.pdf_name
    ),
  );
}

export function buildWorkspaceDraftData(state, pdfFile) {
  return buildWorkspaceDraftDataWithMeta(state, pdfFile, null);
}

export function buildWorkspaceDraftDataWithMeta(state, pdfFile, workspaceMeta = null) {
  const now = new Date().toISOString();
  return {
    slides: state.slides,
    sentences: state.sents,
    highlights: state.hls,
    total_duration: state.totDur,
    mode: state.appMode,
    generation_ref: state.genRef ?? null,
    operation_logs: state.opLogs,
    study_events: state.studyEvents,
    settings: {
      detail: state.detail,
      level: state.level,
      prev_mode: state.prevMode,
      play_speed: state.playSpeed,
      preview_frame: state.previewFrame ?? null,
    },
    saved_fingerprint: state.savedFingerprint ?? null,
    project_meta: {
      id: state.projectMeta?.id ?? null,
      name: normalizeProjectName(state, pdfFile),
      created_at: state.projectMeta?.created_at ?? null,
      updated_at: now,
    },
    workspace_meta: {
      scope_id: workspaceMeta?.scopeId ?? null,
      revision: Number(workspaceMeta?.revision ?? 0) || 0,
    },
    status: state.status,
    status_message: state.statusMsg,
    progress: state.progress,
    active_job_id: state.activeJobId ?? null,
    pdf_name: pdfFile?.name ?? null,
  };
}

export function fingerprintWorkspaceData(data) {
  return JSON.stringify({
    slides: data?.slides ?? [],
    sentences: data?.sentences ?? [],
    highlights: data?.highlights ?? [],
    total_duration: data?.total_duration ?? 0,
    mode: data?.mode ?? null,
    generation_ref: data?.generation_ref ?? null,
    settings: data?.settings ?? null,
    saved_fingerprint: data?.saved_fingerprint ?? null,
    project_meta: {
      id: data?.project_meta?.id ?? null,
      name: data?.project_meta?.name ?? null,
      created_at: data?.project_meta?.created_at ?? null,
    },
    status: data?.status ?? null,
    status_message: data?.status_message ?? null,
    progress: Number(data?.progress ?? 0) || 0,
    active_job_id: data?.active_job_id ?? null,
    pdf_name: data?.pdf_name ?? null,
  });
}

async function workspaceRequest(path, options = {}) {
  const res = await authFetch(path, options);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function loadWorkspaceDraft() {
  const payload = await workspaceRequest("/api/workspace", { method: "GET" });
  return payload?.draft ?? null;
}

export async function saveWorkspaceDraft(data) {
  const revision = Number(data?.workspace_meta?.revision ?? 0) || 0;
  const workspaceId = data?.workspace_meta?.scope_id ?? null;
  return workspaceRequest("/api/workspace", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ data, workspace_id: workspaceId, revision }),
  });
}

export async function clearWorkspaceDraft(workspaceMeta = null) {
  const headers = {};
  if (workspaceMeta?.scopeId) {
    headers["X-Workspace-Id"] = workspaceMeta.scopeId;
  }
  if (workspaceMeta?.revision != null) {
    headers["X-Workspace-Revision"] = String(workspaceMeta.revision);
  }
  return workspaceRequest("/api/workspace", { method: "DELETE", headers });
}
