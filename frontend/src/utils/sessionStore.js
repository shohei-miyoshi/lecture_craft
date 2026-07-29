import { apiFetch } from "./constants.js";

const SESSION_STORAGE_KEY = "lecture_craft_auth_session_v4";
const LEGACY_SESSION_STORAGE_KEY = "kenkyu_auth_session_v2";

function sanitizeSession(value) {
  if (!value || typeof value !== "object") return null;
  return {
    session_id: value.session_id ?? null,
    experiment_id: value.experiment_id ?? null,
    participant_label: value.participant_label ?? null,
    csrf_token: value.csrf_token ?? null,
    user: value.user ?? null,
  };
}

function loadStoredSession() {
  try {
    const current = localStorage.getItem(SESSION_STORAGE_KEY);
    if (current) return sanitizeSession(JSON.parse(current));
    return sanitizeSession(JSON.parse(localStorage.getItem(LEGACY_SESSION_STORAGE_KEY) ?? "null"));
  } catch {
    return null;
  }
}

function saveStoredSession(value) {
  const sanitized = sanitizeSession(value);
  if (!sanitized?.session_id || !sanitized?.user?.id) {
    clearStoredSession();
    return;
  }
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sanitized));
  localStorage.removeItem(LEGACY_SESSION_STORAGE_KEY);
}

async function readErrorMessage(res) {
  const text = await res.text().catch(() => "");
  if (!text) return `HTTP ${res.status}`;
  try {
    const parsed = JSON.parse(text);
    return parsed?.error?.message || text;
  } catch {
    return text;
  }
}

export function getStoredSession() {
  return loadStoredSession();
}

export function clearStoredSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
  localStorage.removeItem(LEGACY_SESSION_STORAGE_KEY);
}

async function authRequest(path, body) {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(await readErrorMessage(res));
  }
  const data = await res.json();
  saveStoredSession(data);
  return getStoredSession();
}

export async function registerUser(username, password) {
  return authRequest("/api/auth/register", { username, password });
}

export async function loginUser(username, password) {
  return authRequest("/api/auth/login", { username, password });
}

export async function fetchCurrentSession() {
  const res = await apiFetch("/api/auth/me");
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      clearStoredSession();
      return null;
    }
    throw new Error(await readErrorMessage(res));
  }
  const data = await res.json();
  saveStoredSession(data);
  return getStoredSession();
}

export async function logoutUser() {
  const buildLogoutOptions = () => {
    const session = loadStoredSession();
    const headers = {
      "Content-Type": "application/json",
    };
    if (session?.csrf_token) {
      headers["X-LectureCraft-CSRF"] = session.csrf_token;
    }
    return {
      method: "POST",
      headers,
    };
  };

  let res = await apiFetch("/api/auth/logout", buildLogoutOptions());
  if (res.status === 403) {
    // localStorage のセッション情報だけ失われても、Cookie が残っていれば CSRF を再取得してログアウトできる。
    await fetchCurrentSession().catch(() => null);
    res = await apiFetch("/api/auth/logout", buildLogoutOptions());
  }

  if (!res.ok && res.status !== 401) {
    throw new Error(await readErrorMessage(res));
  }

  clearStoredSession();
}

export async function authFetch(path, options = {}, retry = true) {
  const session = loadStoredSession();
  const method = String(options?.method ?? "GET").toUpperCase();
  const needsCsrf = !["GET", "HEAD", "OPTIONS"].includes(method);
  const headers = {
    ...(options?.headers ?? {}),
  };
  if (needsCsrf && session?.csrf_token) {
    headers["X-LectureCraft-CSRF"] = session.csrf_token;
  }
  const res = await apiFetch(path, { ...options, headers });
  if (res.status === 401 && retry) {
    clearStoredSession();
    throw new Error("セッションが切れました。もう一度ログインしてください。");
  }
  if (res.status === 403) {
    const message = await readErrorMessage(res.clone()).catch(() => "");
    if (/CSRF|安全のため|再読み込み/i.test(message)) {
      throw new Error("安全確認に失敗しました。ページを再読み込みしてからもう一度試してください。");
    }
    if (retry) {
      throw new Error(message || "この操作を実行する権限がありません。");
    }
  }
  if (res.status === 401 || res.status === 403) {
    throw new Error("ログインが必要です");
  }
  return res;
}
