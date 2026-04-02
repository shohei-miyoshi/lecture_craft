const LEGACY_STORAGE_KEY = "kenkyu_local_projects_v1";
const INDEX_STORAGE_KEY = "kenkyu_local_project_index_v2";
const MIGRATION_FLAG_KEY = "kenkyu_local_project_index_v2_migrated";
const DB_NAME = "kenkyu-project-store";
const DB_VERSION = 1;
const STORE_NAME = "projects";

let dbPromise = null;
let migrationPromise = null;

function loadIndex() {
  try {
    return JSON.parse(localStorage.getItem(INDEX_STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveIndex(rows) {
  localStorage.setItem(INDEX_STORAGE_KEY, JSON.stringify(rows));
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
    if (localStorage.getItem(MIGRATION_FLAG_KEY) === "done") return;

    const legacyRows = loadLegacyRows();
    if (!legacyRows.length) {
      if (!localStorage.getItem(INDEX_STORAGE_KEY)) saveIndex([]);
      localStorage.setItem(MIGRATION_FLAG_KEY, "done");
      return;
    }

    const indexRows = [];
    for (const row of legacyRows) {
      await putProjectRecord(row);
      indexRows.push(indexRowFor(row));
    }

    saveIndex(sortIndex(indexRows));
    localStorage.removeItem(LEGACY_STORAGE_KEY);
    localStorage.setItem(MIGRATION_FLAG_KEY, "done");
  })();
  return migrationPromise;
}

export async function listProjects() {
  await migrateLegacyStorage();
  return sortIndex(loadIndex());
}

export async function saveProject(project) {
  await migrateLegacyStorage();
  await putProjectRecord(project);
  const rows = loadIndex().filter((row) => row.id !== project.id);
  rows.push(indexRowFor(project));
  saveIndex(sortIndex(rows));
}

export async function loadProject(projectId) {
  await migrateLegacyStorage();
  return getProjectRecord(projectId);
}

export async function deleteProject(projectId) {
  await migrateLegacyStorage();
  await deleteProjectRecord(projectId);
  saveIndex(loadIndex().filter((row) => row.id !== projectId));
}

export async function updateProjectName(projectId, nextName) {
  await migrateLegacyStorage();
  const row = await getProjectRecord(projectId);
  if (!row) return;
  const now = new Date().toISOString();
  const updated = {
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
  await putProjectRecord(updated);
  const rows = loadIndex().map((item) => (
    item.id === projectId
      ? { ...item, name: nextName, updated_at: now }
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
