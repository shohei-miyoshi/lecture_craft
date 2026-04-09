import { authFetch, getStoredSession } from "./sessionStore.js";

const LEGACY_STORAGE_KEY = "kenkyu_local_projects_v1";
const LEGACY_INDEX_STORAGE_KEY_BASE = "kenkyu_local_project_index_v2";
const INDEX_STORAGE_KEY_BASE = "lecture_craft_local_project_index_v3";
const LEGACY_MIGRATION_FLAG_KEY_BASE = "kenkyu_local_project_index_v2_migrated";
const MIGRATION_FLAG_KEY_BASE = "lecture_craft_local_project_index_v3_migrated";
const DB_NAME = "kenkyu-project-store";
const DB_VERSION = 1;
const STORE_NAME = "projects";

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
  return {
    id: project.id,
    name: project.name,
    created_at: project.created_at,
    updated_at: project.updated_at,
    mode: data.mode ?? null,
    slide_count: data.slides?.length ?? 0,
    sentence_count: data.sentences?.length ?? 0,
    highlight_count: data.highlights?.length ?? 0,
  };
}

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
  await migrateLegacyStorage();
  try {
    const payload = await apiRequest("/api/projects", { method: "GET" });
    const rows = sortIndex(payload?.projects ?? []);
    saveIndex(rows);
    return rows;
  } catch {
    return sortIndex(loadIndex());
  }
}

export async function saveProject(project) {
  await migrateLegacyStorage();
  const existsRemotely = loadIndex().some((row) => row.id === project.id);
  const method = existsRemotely ? "PATCH" : "POST";
  const path = existsRemotely ? `/api/projects/${project.id}` : "/api/projects";
  const body = existsRemotely
    ? {
        name: project.name,
        data: project.data,
      }
    : {
        client_project_id: project.id,
        name: project.name,
        data: project.data,
      };
  try {
    const saved = await apiRequest(path, {
      method,
      body: JSON.stringify(body),
    });
    const normalized = {
      id: saved?.id ?? project.id,
      name: saved?.name ?? project.name,
      created_at: saved?.created_at ?? project.created_at,
      updated_at: saved?.updated_at ?? project.updated_at,
      data: saved?.data ?? project.data,
    };
    await putProjectRecord(normalized);
    const rows = loadIndex().filter((row) => row.id !== normalized.id);
    rows.push(indexRowFor(normalized));
    saveIndex(sortIndex(rows));

    const eventRows = buildEventPayloads(normalized);
    if (eventRows.length) {
      await apiRequest(`/api/projects/${normalized.id}/events`, {
        method: "POST",
        body: JSON.stringify({ events: eventRows }),
      });
    }
    return normalized;
  } catch (error) {
    await putProjectRecord(project);
    const rows = loadIndex().filter((row) => row.id !== project.id);
    rows.push(indexRowFor(project));
    saveIndex(sortIndex(rows));
    throw error;
  }
}

export async function loadProject(projectId) {
  await migrateLegacyStorage();
  try {
    const project = await apiRequest(`/api/projects/${projectId}`, { method: "GET" });
    if (project) {
      await putProjectRecord(project);
      const rows = loadIndex().filter((row) => row.id !== project.id);
      rows.push(indexRowFor(project));
      saveIndex(sortIndex(rows));
    }
    return project;
  } catch {
    return getProjectRecord(projectId);
  }
}

export async function deleteProject(projectId) {
  await migrateLegacyStorage();
  try {
    await apiRequest(`/api/projects/${projectId}`, { method: "DELETE" });
  } catch {
    // ローカル退避だけでも削除できるようにする
  }
  await deleteProjectRecord(projectId);
  saveIndex(loadIndex().filter((row) => row.id !== projectId));
}

export async function updateProjectName(projectId, nextName) {
  await migrateLegacyStorage();
  let row = await getProjectRecord(projectId);
  if (!row) return;
  try {
    row = await apiRequest(`/api/projects/${projectId}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: nextName,
        data: {
          ...(row.data ?? {}),
          project_meta: {
            ...(row.data?.project_meta ?? {}),
            id: projectId,
            name: nextName,
          },
        },
      }),
    });
  } catch {
    const now = new Date().toISOString();
    row = {
      ...row,
      name: nextName,
      updated_at: now,
      data: {
        ...(row.data ?? {}),
        project_meta: {
          ...(row.data?.project_meta ?? {}),
          id: projectId,
          name: nextName,
          created_at: row.data?.project_meta?.created_at ?? row.created_at ?? now,
          updated_at: now,
        },
      },
    };
  }
  await putProjectRecord(row);
  const rows = loadIndex().map((item) => (
    item.id === projectId
      ? { ...item, name: row.name, updated_at: row.updated_at }
      : item
  ));
  saveIndex(sortIndex(rows));
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
