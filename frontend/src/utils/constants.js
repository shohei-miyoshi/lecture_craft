export const API_URL = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");

function normalizeHeaders(headers) {
  if (!headers) return {};
  if (headers instanceof Headers) {
    const out = {};
    headers.forEach((value, key) => {
      out[key] = value;
    });
    return out;
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return { ...headers };
}

function isMcpGatewayUrl() {
  try {
    const parsed = new URL(API_URL, window.location.href);
    return parsed.pathname.startsWith("/qu/mcp/");
  } catch {
    return false;
  }
}

function normalizeApiPath(path) {
  const trimmed = String(path ?? "").trim();
  if (!trimmed) return "/";
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

function joinApiUrl(base, path) {
  const normalizedPath = normalizeApiPath(path);
  if (!base) return normalizedPath;

  const baseUrl = base.replace(/\/+$/, "");
  if (/\/api$/i.test(baseUrl)) {
    return `${baseUrl}${normalizedPath.replace(/^\/api(?=\/|$)/i, "")}`;
  }
  return `${baseUrl}${normalizedPath}`;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  const chunks = [];
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)));
  }
  return btoa(chunks.join(""));
}

export async function apiFetch(path, options = {}) {
  const { credentials, ...restOptions } = options;
  const nextCredentials = credentials ?? "include";
  if (!isMcpGatewayUrl()) {
    return fetch(joinApiUrl(API_URL, path), {
      ...restOptions,
      credentials: nextCredentials,
    });
  }

  const { headers, method = "GET", body, ...rest } = restOptions;
  const normalizedHeaders = normalizeHeaders(headers);
  const payload = {
    method,
    path,
    headers: normalizedHeaders,
  };
  if (body instanceof FormData) {
    const encoded = new Response(body);
    const contentType = encoded.headers.get("content-type");
    if (contentType) payload.headers["content-type"] = contentType;
    payload.body_base64 = arrayBufferToBase64(await encoded.arrayBuffer());
  } else if (body !== undefined && body !== null) {
    payload.body = typeof body === "string" ? body : JSON.stringify(body);
  }

  return fetch(API_URL, {
    ...rest,
    method: "POST",
    credentials: nextCredentials,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const DETAIL_VALS   = ["summary", "standard", "detail"];
export const DIFF_VALS     = ["intro", "basic", "advanced"];
export const DETAIL_LABELS = ["要約的", "標準的", "精緻"];
export const DIFF_LABELS   = ["入門", "基礎", "発展"];

/** ハイライト種別の表示名 */
export const KIND_LABEL = { marker: "マーカー", arrow: "矢印", box: "囲み" };

/** ハイライト種別の色 */
export const KIND_COLOR = { marker: "#6ec1ff", arrow: "#6ec1ff", box: "#6ec1ff" };

/** ハイライト種別の背景色（通常） */
export const KIND_BG = {
  marker: "rgba(110,193,255,.14)",
  arrow:  "rgba(110,193,255,.14)",
  box:    "rgba(110,193,255,.14)",
};

/** ハイライト種別の背景色（選択時） */
export const KIND_BG_SEL = {
  marker: "rgba(110,193,255,.28)",
  arrow:  "rgba(110,193,255,.28)",
  box:    "rgba(110,193,255,.28)",
};
