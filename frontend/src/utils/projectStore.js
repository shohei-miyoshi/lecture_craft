const STORAGE_KEY = "kenkyu_local_projects_v1";

function loadAll() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

function saveAll(rows) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(rows));
}

export function listProjects() {
  return loadAll().sort((a, b) => String(b.updated_at ?? "").localeCompare(String(a.updated_at ?? "")));
}

export function saveProject(project) {
  const rows = loadAll();
  const next = rows.filter((row) => row.id !== project.id);
  next.push(project);
  saveAll(next);
}

export function loadProject(projectId) {
  return loadAll().find((row) => row.id === projectId) ?? null;
}

export function deleteProject(projectId) {
  saveAll(loadAll().filter((row) => row.id !== projectId));
}

export function buildProjectPayload(state, name) {
  const now = new Date().toISOString();
  const projectId = state.projectMeta?.id ?? `project_${Date.now()}`;
  return {
    id: projectId,
    name,
    created_at: state.projectMeta?.created_at ?? now,
    updated_at: now,
    data: {
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
      project_meta: {
        id: projectId,
        name,
        created_at: state.projectMeta?.created_at ?? now,
        updated_at: now,
      },
    },
  };
}
