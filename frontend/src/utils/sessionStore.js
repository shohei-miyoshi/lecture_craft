import { API_URL } from "./constants.js";

const SESSION_STORAGE_KEY = "kenkyu_auth_session_v2";

function loadStoredSession() {
  try {
    return JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) ?? "null");
  } catch {
    return null;
  }
}

function saveStoredSession(value) {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(value));
}

export function getStoredSession() {
  return loadStoredSession();
}

export function getSessionToken() {
  return loadStoredSession()?.session_token ?? null;
}

export function clearStoredSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
}

async function authRequest(path, body) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  const data = await res.json();
  saveStoredSession(data);
  return data;
}

export async function registerUser(username, password) {
  return authRequest("/api/auth/register", { username, password });
}

export async function loginUser(username, password) {
  return authRequest("/api/auth/login", { username, password });
}

export async function fetchCurrentSession() {
  const session = loadStoredSession();
  if (!session?.session_token) return null;
  const res = await fetch(`${API_URL}/api/auth/me`, {
    headers: {
      "X-Kenkyu-Session": session.session_token,
    },
  });
  if (!res.ok) {
    clearStoredSession();
    return null;
  }
  const data = await res.json();
  const merged = {
    ...session,
    ...data,
  };
  saveStoredSession(merged);
  return merged;
}

export async function logoutUser() {
  const token = getSessionToken();
  if (token) {
    await fetch(`${API_URL}/api/auth/logout`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Kenkyu-Session": token,
      },
    }).catch(() => {});
  }
  clearStoredSession();
}

export async function authFetch(path, options = {}, retry = true) {
  const session = loadStoredSession();
  if (!session?.session_token) {
    throw new Error("ログインが必要です");
  }
  const headers = {
    ...(options.headers ?? {}),
    "X-Kenkyu-Session": session.session_token,
  };
  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if ((res.status === 401 || res.status === 403) && retry) {
    clearStoredSession();
    throw new Error("セッションが切れました。もう一度ログインしてください。");
  }
  return res;
}
