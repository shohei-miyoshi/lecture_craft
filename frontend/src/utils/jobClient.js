import { authFetch } from "./sessionStore.js";

function jobError(job, fallback) {
  return new Error(job?.error?.message || job?.message || fallback);
}

export async function submitPreviewAudio(payload) {
  const response = await authFetch("/api/preview/audio", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status}${text ? `: ${text.slice(0, 240)}` : ""}`);
  }
  return response.json();
}

export async function waitForJob(submitted, {
  pollIntervalMs = 1000,
  onProgress = null,
} = {}) {
  if (!submitted?.job_id) throw new Error("生成ジョブIDが返されませんでした");
  let job = submitted;
  while (job.status === "queued" || job.status === "running") {
    onProgress?.(job);
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    const response = await authFetch(`/api/jobs/${submitted.job_id}`, { method: "GET" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    job = await response.json();
  }
  onProgress?.(job);
  if (job.status !== "completed" || !job.result) {
    throw jobError(job, "生成ジョブに失敗しました");
  }
  return job;
}
