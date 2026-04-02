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

export function updateProjectName(projectId, nextName) {
  const rows = loadAll();
  const updated = rows.map((row) => {
    if (row.id !== projectId) return row;
    const now = new Date().toISOString();
    return {
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
  });
  saveAll(updated);
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
