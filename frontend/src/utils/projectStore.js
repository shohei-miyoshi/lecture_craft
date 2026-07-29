import { authFetch, getStoredSession } from "./sessionStore.js";

const LEGACY_STORAGE_KEY = "kenkyu_local_projects_v1";
const LEGACY_INDEX_STORAGE_KEY_BASE = "kenkyu_local_project_index_v2";
const INDEX_STORAGE_KEY_BASE = "lecture_craft_local_project_index_v3";
const LEGACY_MIGRATION_FLAG_KEY_BASE = "kenkyu_local_project_index_v2_migrated";
const MIGRATION_FLAG_KEY_BASE = "lecture_craft_local_project_index_v3_migrated";
const DB_NAME = "kenkyu-project-store";
const DB_VERSION = 1;
const STORE_NAME = "projects";
const LOCAL_PROJECT_FALLBACK_ENABLED =
  import.meta.env.DEV || import.meta.env.VITE_ALLOW_LOCAL_PROJECT_FALLBACK === "1";

let dbPromise = null;
let migrationPromise = null;

function currentStorageScope() {
  return getStoredSession()?.user?.id ?? "anonymous";
}

function scopedIndexKey() {
  return `${INDEX_STORAGE_KEY_BASE}_${currentStorageScope()}`;
}

function legacyScopedIndexKey() {
  return `${LEGACY_INDEX_STORAGE_KEY_BASE}_${currentStorageScope()}`;
}

function scopedMigrationFlagKey() {
  return `${MIGRATION_FLAG_KEY_BASE}_${currentStorageScope()}`;
}

function legacyScopedMigrationFlagKey() {
  return `${LEGACY_MIGRATION_FLAG_KEY_BASE}_${currentStorageScope()}`;
}

function loadIndex() {
  try {
    const current = localStorage.getItem(scopedIndexKey());
    if (current) return JSON.parse(current);
    return JSON.parse(localStorage.getItem(legacyScopedIndexKey()) ?? "[]");
  } catch {
    return [];
  }
}

function saveIndex(rows) {
  if (!LOCAL_PROJECT_FALLBACK_ENABLED) {
    try {
      localStorage.removeItem(scopedIndexKey());
      localStorage.removeItem(legacyScopedIndexKey());
    } catch {}
    return;
  }
  localStorage.setItem(scopedIndexKey(), JSON.stringify(rows));
  localStorage.removeItem(legacyScopedIndexKey());
}

function loadLegacyRows() {
  try {
    return JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function indexRowFor(project) {
  const data = project?.data ?? {};
  const inputPdf = sanitizeInputPdfMeta(data.input_pdf);
  return {
    id: project.id,
    name: project.name,
    created_at: project.created_at,
    updated_at: project.updated_at,
    mode: data.mode ?? null,
    slide_count: data.slides?.length ?? 0,
    sentence_count: data.sentences?.length ?? 0,
    highlight_count: data.highlights?.length ?? 0,
    version_number: project?.version_number ?? data?.project_meta?.version_number ?? null,
    input_pdf: inputPdf,
    has_pdf: Boolean(inputPdf?.available),
  };
}

function sanitizeInputPdfMeta(inputPdf) {
  if (!inputPdf || typeof inputPdf !== "object") return null;
  const {
    upload_base64: _uploadBase64,
    base64: _base64,
    data_url: _dataUrl,
    ...meta
  } = inputPdf;
  return {
    name: meta.name ?? null,
    type: meta.type ?? "application/pdf",
    size: meta.size ?? null,
    last_modified: meta.last_modified ?? null,
    sha256: meta.sha256 ?? null,
    storage_key: meta.storage_key ?? meta.sha256 ?? null,
    artifact_id: meta.artifact_id ?? meta.storage_key ?? null,
    available: Boolean(meta.available),
    artifact_kind: meta.artifact_kind ?? null,
    download_url: meta.download_url ?? null,
  };
}

function mergeIndexRows(primaryRows, fallbackRows) {
  const map = new Map();
  for (const row of fallbackRows ?? []) {
    if (row?.id) map.set(row.id, { ...row });
  }
  for (const row of primaryRows ?? []) {
    if (!row?.id) continue;
    map.set(row.id, { ...(map.get(row.id) ?? {}), ...row });
  }
  return [...map.values()];
}

function buildEventPayloads(project) {
  const data = project?.data ?? {};
  const studyEvents = Array.isArray(data.study_events) ? data.study_events : [];
  const operationLogs = Array.isArray(data.operation_logs) ? data.operation_logs : [];

  const mappedStudyEvents = studyEvents.map((event) => ({
    external_event_id: event?.id,
    generation_run_id: project?.active_run_id ?? data?.generation_ref?.run_id ?? null,
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
    generation_run_id: project?.active_run_id ?? data?.generation_ref?.run_id ?? null,
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

function normalizeProjectMeta(project, fallbackMeta = null) {
  const dataMeta = project?.data?.project_meta;
  return {
    ...(fallbackMeta ?? {}),
    ...(dataMeta ?? {}),
    id: project?.project_meta?.id ?? dataMeta?.id ?? project?.id ?? fallbackMeta?.id ?? null,
    name: project?.project_meta?.name ?? dataMeta?.name ?? project?.name ?? fallbackMeta?.name ?? null,
    created_at:
      project?.project_meta?.created_at
      ?? dataMeta?.created_at
      ?? project?.created_at
      ?? fallbackMeta?.created_at
      ?? null,
    updated_at:
      project?.project_meta?.updated_at
      ?? dataMeta?.updated_at
      ?? project?.updated_at
      ?? fallbackMeta?.updated_at
      ?? null,
    version_number:
      project?.version_number
      ?? project?.project_meta?.version_number
      ?? dataMeta?.version_number
      ?? fallbackMeta?.version_number
      ?? null,
  };
}

function normalizeProjectRecord(project, fallbackProject = null) {
  const fallbackMeta = fallbackProject?.data?.project_meta ?? fallbackProject?.project_meta ?? null;
  const projectMeta = normalizeProjectMeta(project, fallbackMeta);
  const data = {
    ...(fallbackProject?.data ?? {}),
    ...(project?.data ?? {}),
    project_meta: projectMeta,
  };
  if (data.input_pdf) {
    data.input_pdf = sanitizeInputPdfMeta(data.input_pdf);
  }
  return {
    id: projectMeta.id ?? project?.id ?? fallbackProject?.id,
    name: projectMeta.name ?? project?.name ?? fallbackProject?.name ?? "新しいプロジェクト",
    created_at: projectMeta.created_at ?? project?.created_at ?? fallbackProject?.created_at ?? null,
    updated_at: projectMeta.updated_at ?? project?.updated_at ?? fallbackProject?.updated_at ?? null,
    version_number: projectMeta.version_number,
    draft_version: project?.draft_version ?? projectMeta.version_number ?? fallbackProject?.draft_version ?? null,
    usage_context: project?.usage_context ?? fallbackProject?.usage_context ?? "general",
    analysis_status: project?.analysis_status ?? fallbackProject?.analysis_status ?? "candidate",
    active_run_id: project?.active_run_id ?? fallbackProject?.active_run_id ?? null,
    source_artifact: project?.source_artifact ?? fallbackProject?.source_artifact ?? null,
    data,
  };
}

function stripLargeSlidePayload(slide) {
  if (!slide || typeof slide !== "object") return slide;
  const {
    image_base64: _imageBase64,
    image_data_url: _imageDataUrl,
    image_blob_url: _imageBlobUrl,
    ...rest
  } = slide;
  return {
    ...rest,
    image_available: Boolean(slide.image_base64 || slide.image_url || slide.image_available),
  };
}

function sortIndex(rows) {
  return [...rows].sort((a, b) => String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? "")));
}

function openDb() {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (!globalThis.indexedDB) {
      reject(new Error("このブラウザでは IndexedDB が利用できません"));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error ?? new Error("IndexedDB を開けませんでした"));
  });
  return dbPromise;
}

async function withStore(mode, run) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, mode);
    const store = tx.objectStore(STORE_NAME);
    let settled = false;
    const finishResolve = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    const finishReject = (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    tx.oncomplete = () => finishResolve(undefined);
    tx.onerror = () => finishReject(tx.error ?? new Error("IndexedDB transaction failed"));
    tx.onabort = () => finishReject(tx.error ?? new Error("IndexedDB transaction aborted"));
    try {
      const maybePromise = run(store, finishResolve, finishReject);
      if (maybePromise?.then) {
        maybePromise.catch(finishReject);
      }
    } catch (error) {
      finishReject(error);
    }
  });
}

function storeRequestAsPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB request failed"));
  });
}

async function getProjectRecord(projectId) {
  return withStore("readonly", async (store, resolve, reject) => {
    try {
      const record = await storeRequestAsPromise(store.get(projectId));
      resolve(record ?? null);
    } catch (error) {
      reject(error);
    }
  });
}

async function putProjectRecord(project) {
  return withStore("readwrite", async (store, resolve, reject) => {
    try {
      await storeRequestAsPromise(store.put(project));
      resolve(project);
    } catch (error) {
      reject(error);
    }
  });
}

async function deleteProjectRecord(projectId) {
  return withStore("readwrite", async (store, resolve, reject) => {
    try {
      await storeRequestAsPromise(store.delete(projectId));
      resolve(undefined);
    } catch (error) {
      reject(error);
    }
  });
}

async function migrateLegacyStorage() {
  if (!LOCAL_PROJECT_FALLBACK_ENABLED) return;
  if (migrationPromise) return migrationPromise;
  migrationPromise = (async () => {
    const migrationFlagKey = scopedMigrationFlagKey();
    if (
      localStorage.getItem(migrationFlagKey) === "done" ||
      localStorage.getItem(legacyScopedMigrationFlagKey()) === "done"
    ) {
      if (localStorage.getItem(legacyScopedMigrationFlagKey()) === "done") {
        localStorage.setItem(migrationFlagKey, "done");
      }
      return;
    }

    const legacyRows = loadLegacyRows();
    if (!legacyRows.length) {
      if (!localStorage.getItem(scopedIndexKey())) saveIndex([]);
      localStorage.setItem(migrationFlagKey, "done");
      return;
    }

    const indexRows = [];
    for (const row of legacyRows) {
      await putProjectRecord(row);
      indexRows.push(indexRowFor(row));
    }

    saveIndex(sortIndex(indexRows));
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    localStorage.setItem(migrationFlagKey, "done");
  })();
  return migrationPromise;
}

async function apiRequest(path, options = {}, retry = true) {
  if (!getStoredSession()?.user?.id) {
    throw new Error("ログインが必要です");
  }
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers ?? {}),
  };
  const res = await authFetch(path, { ...options, headers }, retry);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const error = new Error(formatApiErrorMessage(text, res.status));
    error.status = res.status;
    error.responseText = text;
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

function formatApiErrorMessage(text, status) {
  const fallback = `HTTP ${status}`;
  if (!text) return fallback;
  try {
    const payload = JSON.parse(text);
    const detail = payload?.detail ?? payload;
    if (typeof detail === "string") return detail;
    if (detail?.message) return String(detail.message);
    if (detail?.code) return String(detail.code);
  } catch {
    // Plain text or HTML response from a proxy.
  }
  const plain = String(text).replace(/\s+/g, " ").trim();
  return plain || fallback;
}

export async function listProjects() {
  const payload = await apiRequest("/api/projects", { method: "GET" });
  return sortIndex(payload?.projects ?? []);
}

function isProjectMissingError(error) {
  return Number(error?.status) === 404 || /PROJECT_NOT_FOUND/i.test(String(error?.message ?? ""));
}

export async function createProject(name, usageContext = "general") {
  return apiRequest("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      name,
      usage_context: usageContext,
    }),
  });
}

export async function uploadProjectPdf(projectId, file) {
  const form = new FormData();
  form.append("file", file, file.name);
  const res = await authFetch(`/api/projects/${projectId}/source-pdf`, {
    method: "PUT",
    body: form,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    const error = new Error(formatApiErrorMessage(text, res.status));
    error.status = res.status;
    throw error;
  }
  return res.json();
}

export async function saveProjectDraft(projectId, baseVersion, name, data) {
  return apiRequest(`/api/projects/${projectId}/draft`, {
    method: "PUT",
    body: JSON.stringify({
      base_version: baseVersion,
      name,
      data,
    }),
  });
}

export async function checkpointProject(projectId, revisionKind = "manual_save") {
  return apiRequest(`/api/projects/${projectId}/revisions`, {
    method: "POST",
    body: JSON.stringify({ revision_kind: revisionKind }),
  });
}

export async function createGenerationRun(projectId, payload) {
  return apiRequest(`/api/projects/${projectId}/runs`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function loadGenerationRun(runId) {
  return apiRequest(`/api/runs/${runId}`, { method: "GET" });
}

export async function saveProject(project, { pdfFile = null, checkpoint = true } = {}) {
  let serverProject;
  const existingId = project?.data?.project_meta?.id ?? project?.id ?? null;
  if (existingId) {
    serverProject = await apiRequest(`/api/projects/${existingId}`, { method: "GET" });
  } else {
    serverProject = await createProject(project.name);
  }
  let draftVersion = Number(serverProject?.draft_version ?? serverProject?.data?.project_meta?.version_number ?? 1);
  if (pdfFile) {
    const currentHash = serverProject?.source_artifact?.sha256 ?? null;
    const localHash = project?.data?.input_pdf?.sha256 ?? null;
    if (!currentHash || !localHash || currentHash !== localHash) {
      const uploaded = await uploadProjectPdf(serverProject.id, pdfFile);
      draftVersion = Number(uploaded.draft_version ?? draftVersion);
      serverProject = await apiRequest(`/api/projects/${serverProject.id}`, { method: "GET" });
    }
  }
  const data = {
    ...(project.data ?? {}),
    project_meta: {
      ...(project.data?.project_meta ?? {}),
      id: serverProject.id,
      name: project.name,
      created_at: serverProject.created_at,
      version_number: draftVersion,
    },
    input_pdf: serverProject.data?.input_pdf ?? project.data?.input_pdf ?? null,
  };
  const saved = await saveProjectDraft(serverProject.id, draftVersion, project.name, data);
  if (checkpoint) {
    await checkpointProject(serverProject.id, "manual_save");
  }
  const normalized = normalizeProjectRecord(saved, { ...project, id: serverProject.id, data });
  const eventRows = buildEventPayloads(normalized);
  if (eventRows.length) {
    apiRequest(`/api/projects/${normalized.id}/events`, {
      method: "POST",
      body: JSON.stringify({ events: eventRows }),
    }).catch((error) => console.warn("Project event sync failed:", error));
  }
  return normalized;
}

export async function loadProject(projectId) {
  const project = await apiRequest(`/api/projects/${projectId}`, { method: "GET" });
  return project ? normalizeProjectRecord(project) : null;
}

export async function deleteProject(projectId) {
  await apiRequest(`/api/projects/${projectId}`, { method: "DELETE" });
}

export async function updateProjectName(projectId, nextName) {
  const current = await apiRequest(`/api/projects/${projectId}`, { method: "GET" });
  return saveProjectDraft(
    projectId,
    current.draft_version,
    nextName,
    {
      ...(current.data ?? {}),
      project_meta: {
        ...(current.data?.project_meta ?? {}),
        id: projectId,
        name: nextName,
      },
    },
  );
}

export function buildProjectData(state, name, projectIdOverride = null) {
  const now = new Date().toISOString();
  const projectId = projectIdOverride ?? state.projectMeta?.id ?? null;
  const projectMeta = {
    id: projectId,
    name,
    created_at: state.projectMeta?.created_at ?? now,
    updated_at: now,
    version_number: state.projectMeta?.version_number ?? null,
  };
  return {
    slides: (state.slides ?? []).map(stripLargeSlidePayload),
    sentences: state.sents,
    highlights: state.hls,
    total_duration: state.totDur,
    generated: state.generated,
    mode: state.appMode,
    generation_ref: state.genRef ?? null,
    session_id: state.sessionId ?? null,
    baseline: state.baseline ?? null,
    input_pdf: state.inputPdf ? { ...state.inputPdf } : null,
    operation_logs: state.opLogs,
    study_events: state.studyEvents,
    preview_audio: {
      stale: Boolean(state.previewAudioStale),
    },
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
  const inputPdf = sanitizeInputPdfMeta(data?.input_pdf);
  return JSON.stringify({
    slides: (data?.slides ?? []).map(stripLargeSlidePayload),
    sentences: data?.sentences ?? [],
    highlights: data?.highlights ?? [],
    total_duration: data?.total_duration ?? 0,
    generated: Boolean(data?.generated),
    mode: data?.mode ?? null,
    generation_ref: data?.generation_ref ?? null,
    operation_logs: data?.operation_logs ?? [],
    study_events: data?.study_events ?? [],
    preview_audio: data?.preview_audio ?? null,
    settings: data?.settings ?? null,
    input_pdf: inputPdf
      ? {
          name: inputPdf.name ?? null,
          size: inputPdf.size ?? null,
          sha256: inputPdf.sha256 ?? inputPdf.storage_key ?? null,
          available: Boolean(inputPdf.available),
        }
      : null,
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
  const projectId = state.projectMeta?.id ?? null;
  const data = buildProjectData(state, name, projectId);
  return {
    id: projectId,
    name,
    created_at: state.projectMeta?.created_at ?? now,
    updated_at: now,
    data,
  };
}
