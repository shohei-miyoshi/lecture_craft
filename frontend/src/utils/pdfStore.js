import { authFetch } from "./sessionStore.js";
import { toB64 } from "./helpers.js";

export function normalizePdfRef(value) {
  if (!value || typeof value !== "object") return null;
  const materialName = String(value.material_name ?? "").trim();
  if (!materialName) return null;
  const filename = String(value.filename ?? "").trim() || materialName;
  return {
    material_name: materialName,
    filename,
    fingerprint: String(value.fingerprint ?? "").trim() || null,
    size_bytes: Number(value.size_bytes ?? 0) || 0,
    uploaded_at: value.uploaded_at ?? null,
  };
}

export function extractPdfRefFromData(data) {
  const direct = normalizePdfRef(data?.pdf_ref);
  if (direct) return direct;
  const materialName = String(data?.generation_ref?.material_name ?? "").trim();
  if (!materialName) return null;
  return normalizePdfRef({
    material_name: materialName,
    filename: data?.pdf_name ?? data?.project_meta?.name ?? materialName,
  });
}

export async function uploadSourcePdf(file) {
  const pdfBase64 = await toB64(file);
  const res = await authFetch("/api/source-pdfs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pdf_base64: pdfBase64,
      filename: file.name,
    }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  const payload = await res.json();
  return normalizePdfRef(payload?.pdf_ref);
}

export async function restoreSourcePdf(pdfRef) {
  const normalized = normalizePdfRef(pdfRef);
  if (!normalized) return null;
  const path = `/api/source-pdfs/${encodeURIComponent(normalized.material_name)}?filename=${encodeURIComponent(normalized.filename)}`;
  const res = await authFetch(path, { method: "GET" });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  const blob = await res.blob();
  return new File([blob], normalized.filename, {
    type: "application/pdf",
    lastModified: Date.now(),
  });
}
