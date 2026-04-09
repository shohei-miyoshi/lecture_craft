import { API_URL } from "./constants.js";

const SESSION_STORAGE_KEY = "kenkyu_guest_session_v1";

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

let ensurePromise = null;

export async function ensureGuestSession() {
  const existing = loadStoredSession();
  if (existing?.session_token) return existing;
  if (ensurePromise) return ensurePromise;
  ensurePromise = fetch(`${API_URL}/api/auth/guest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      saveStoredSession(data);
      return data;
    })
    .finally(() => {
      ensurePromise = null;
    });
  return ensurePromise;
}

export function getGuestSessionToken() {
  return loadStoredSession()?.session_token ?? null;
}

export function clearGuestSession() {
  localStorage.removeItem(SESSION_STORAGE_KEY);
}
