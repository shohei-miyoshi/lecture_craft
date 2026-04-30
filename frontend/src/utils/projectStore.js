import { authFetch, getStoredSession } from "./sessionStore.js";

function buildEventPayloads(project) {
  const data = project?.data ?? {};
  const studyEvents = Array.isArray(data.study_events) ? data.study_events : [];
  const operationLogs = Array.isArray(data.operation_logs) ? data.operation_logs : [];

  const mappedStudyEvents = studyEvents.map((event) => ({
    external_event_id: event?.id,
    action_type: event?.kind ?? "study_event",
    slide_idx: event?.payload?.slide_idx ?? null,
    entity_type: "study_event",
    entity_id: event?.payload?.sentence_id ?? event?.payload?.highlight_id ?? null,
    source: "study_event",
    before: event?.payload?.before ?? null,
    after: event?.payload?.after ?? null,
    payload: event?.payload ?? {},
    created_at: event?.at ?? null,
  }));

  const mappedOperationLogs = operationLogs.map((log) => ({
    external_event_id: log?.id,
    action_type: log?.meta?.type ?? "operation_log",
    slide_idx: log?.meta?.slide_idx ?? null,
    entity_type: "operation_log",
    entity_id: log?.meta?.sentence_id ?? log?.meta?.highlight_id ?? null,
    source: "operation_log",
    payload: {
      message: log?.message ?? "",
      meta: log?.meta ?? {},
    },
    created_at: log?.at ?? null,
  }));

  return [...mappedStudyEvents, ...mappedOperationLogs].filter((row) => row.external_event_id);
}

async function apiRequest(path, options = {}, retry = true) {
  if (!getStoredSession()?.session_token) {
    throw new Error("ログインが必要です");
  }
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers ?? {}),
  };
  const res = await authFetch(path, { ...options, headers }, retry);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function listProjects() {
  const payload = await apiRequest("/api/projects", { method: "GET" });
  const rows = Array.isArray(payload?.projects) ? payload.projects : [];
  return [...rows].sort((a, b) => String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? "")));
}

export async function saveProject(project) {
  const saved = await apiRequest("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      client_project_id: project.id,
      name: project.name,
      data: project.data,
    }),
  });

  const normalized = {
    id: saved?.id ?? project.id,
    name: saved?.name ?? project.name,
    created_at: saved?.created_at ?? project.created_at,
    updated_at: saved?.updated_at ?? project.updated_at,
    data: saved?.data ?? project.data,
    version_number: saved?.version_number ?? null,
    project_meta: saved?.project_meta ?? project.data?.project_meta ?? null,
  };

  const eventRows = buildEventPayloads(normalized);
  if (eventRows.length) {
    apiRequest(`/api/projects/${normalized.id}/events`, {
      method: "POST",
      body: JSON.stringify({ events: eventRows }),
    }).catch(() => {});
  }

  return normalized;
}

export async function loadProject(projectId) {
  return apiRequest(`/api/projects/${projectId}`, { method: "GET" });
}

export async function deleteProject(projectId) {
  await apiRequest(`/api/projects/${projectId}`, { method: "DELETE" });
}

export async function updateProjectName(projectId, nextName) {
  return apiRequest(`/api/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify({ name: nextName }),
  });
}

export function buildProjectData(state, name) {
  const now = new Date().toISOString();
  const projectId = state.projectMeta?.id ?? `project_${Date.now()}`;
  const projectMeta = {
    id: projectId,
    name,
    created_at: state.projectMeta?.created_at ?? now,
    updated_at: now,
  };
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
    project_meta: projectMeta,
  };
}

export function fingerprintProjectData(data) {
  return JSON.stringify({
    slides: data?.slides ?? [],
    sentences: data?.sentences ?? [],
    highlights: data?.highlights ?? [],
    total_duration: data?.total_duration ?? 0,
    mode: data?.mode ?? null,
    generation_ref: data?.generation_ref ?? null,
    settings: data?.settings ?? null,
    project_meta: {
      id: data?.project_meta?.id ?? null,
      name: data?.project_meta?.name ?? null,
      created_at: data?.project_meta?.created_at ?? null,
    },
  });
}

export function fingerprintProjectState(state, name = null) {
  const resolvedName = name ?? state.projectMeta?.name ?? "未保存プロジェクト";
  return fingerprintProjectData(buildProjectData(state, resolvedName));
}

export function buildProjectPayload(state, name) {
  const now = new Date().toISOString();
  const projectId = state.projectMeta?.id ?? `project_${Date.now()}`;
  const data = buildProjectData(state, name);
  return {
    id: projectId,
    name,
    created_at: state.projectMeta?.created_at ?? now,
    updated_at: now,
    data,
  };
}
