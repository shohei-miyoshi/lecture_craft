import { useState } from "react";
import { DETAIL_VALS, DIFF_VALS } from "../utils/constants.js";
import { authFetch } from "../utils/sessionStore.js";
import { submitPreviewAudio, waitForJob } from "../utils/jobClient.js";
import { fmt } from "../utils/helpers.js";
import { buildResearchSnapshot } from "../utils/research.js";
import { buildProjectData } from "../utils/projectStore.js";

const EXPORT_ROWS = [
  ["🎬 ハイライトあり動画", "video_highlight", ".mp4"],
  ["📹 動画（HL無し）",     "video",           ".mp4"],
  ["🔊 音声のみ",           "audio",           ".mp3"],
  ["🗂 編集データ",         "json",            ".json"],
  ["📄 台本テキスト",       "script",          ".txt"],
  ["🧾 操作ログ",           "log",             ".json"],
];

const EXPORT_LABELS = Object.fromEntries(EXPORT_ROWS.map(([label, type]) => [type, label.replace(/^[^\s]+\s*/, "")]));

async function responseErrorMessage(response, fallback) {
  const text = await response.text().catch(() => "");
  if (!text) return fallback;
  try {
    const payload = JSON.parse(text);
    const detail = payload?.detail ?? payload?.error ?? payload;
    if (typeof detail === "string") return detail;
    if (detail?.message) return String(detail.message);
    if (detail?.code) return String(detail.code);
  } catch {
    // Proxy errors may be plain text or HTML.
  }
  return text.replace(/\s+/g, " ").trim() || fallback;
}

/**
 * 書き出しパネル
 * JSON / テキストはフロントエンドのみで生成
 * 動画 / 音声はバックエンドに委譲
 */
export default function ExportPanel({ state, dispatch, addToast, ensureLatestDraftSaved }) {
  const [exportProgress, setExportProgress] = useState({
    status: "idle",
    type: null,
    progress: 0,
    message: "",
  });
  const hasSlides = state.slides.length > 0;
  const hasSentences = state.sents.length > 0;
  const hasProjectData = hasSlides || hasSentences || state.hls.length > 0;
  const isGenerating = state.status === "proc";
  const isExporting = exportProgress.status === "running";
  const isBusy = isGenerating || isExporting;
  const exportRows = EXPORT_ROWS.filter(([, type]) => {
    if (state.appMode === "audio") return !["video", "video_highlight"].includes(type);
    if (state.appMode === "video") return type !== "video_highlight";
    return true;
  });

  const exportGuardMessage = (type) => {
    if (isGenerating) return "生成中は書き出しできません。完了または停止してから書き出してください";
    if (isExporting) return "別のメディアを書き出しています．完了してから続けてください";
    switch (type) {
      case "json":
        return hasProjectData ? null : "保存・共有できる編集データがまだありません";
      case "log":
        return state.opLogs.length > 0 ? null : "まだ書き出せる操作ログがありません";
      case "script":
        return hasSentences ? null : "台本がないためテキストを書き出せません";
      case "audio":
        if (!hasSentences) return "音声書き出しには台本が必要です";
        if (!state.projectMeta?.id || !state.genRef?.run_id) {
          return "このプロジェクトは旧形式です．左の「講義メディア生成」を実行して新しい生成runへ更新してください";
        }
        return null;
      case "video":
      case "video_highlight":
        if (state.appMode === "audio") return "音声のみモードでは動画を書き出せません";
        if (type === "video_highlight" && state.appMode !== "hl") {
          return "ハイライトあり動画はハイライトありモードで生成してください";
        }
        if (!hasSlides) return "動画書き出しにはスライドが必要です";
        if (!hasSentences) return "動画書き出しには台本が必要です";
        if (!state.projectMeta?.id || !state.genRef?.run_id) {
          return "このプロジェクトは旧形式です．左の「講義メディア生成」を実行して新しい生成runへ更新してください";
        }
        return null;
      default:
        return null;
    }
  };

  const persistResearchSession = async (trigger) => {
    const research = buildResearchSnapshot(state, trigger);
    try {
      const res = await authFetch("/api/research/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.sessionId,
          trigger,
          mode: state.appMode,
          generation_ref: state.genRef ?? {},
          operation_logs: state.opLogs,
          research,
          settings: {
            detail: DETAIL_VALS[state.detail],
            difficulty: DIFF_VALS[state.level],
            preview_mode: state.prevMode,
            play_speed: state.playSpeed,
          },
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch {
      // 研究ログ保存は best effort。ローカル作業を止めない。
    }
    return research;
  };

  const doExport = async (type) => {
    const guardMessage = exportGuardMessage(type);
    if (guardMessage) {
      addToast("er", guardMessage);
      return;
    }
    // ── JSON エクスポート（フロントのみ） ──
    if (type === "json") {
      const research = await persistResearchSession("export_json");
      const projectData = buildProjectData(
        state,
        state.projectMeta?.name ?? "lecture_data",
        state.projectMeta?.id ?? null,
      );
      const data = {
        export_schema: "lecture_craft_edit_data_v2",
        exported_at: new Date().toISOString(),
        ...projectData,
        research_snapshot: research,
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "lecture_data.json"; a.click();
      dispatch({ type: "APP_LOG", message: "編集データ(JSON)をエクスポートしました", meta: { type: "export_json" } });
      addToast("ok", "📦 JSONをエクスポートしました");
      return;
    }

    // ── 操作ログ（フロントのみ） ──
    if (type === "log") {
      const research = await persistResearchSession("export_log");
      const data = {
        exported_at: new Date().toISOString(),
        mode: state.appMode,
        counts: {
          slides: state.slides.length,
          sentences: state.sents.length,
          highlights: state.hls.length,
          logs: state.opLogs.length,
        },
        operation_logs: state.opLogs,
        research_snapshot: research,
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "operation_log.json"; a.click();
      dispatch({ type: "APP_LOG", message: `操作ログをエクスポートしました（logs=${state.opLogs.length}）`, meta: { type: "export_log", count: state.opLogs.length } });
      addToast("ok", "🧾 操作ログをエクスポートしました");
      return;
    }

    // ── 台本テキスト（フロントのみ） ──
    if (type === "script") {
      await persistResearchSession("export_script");
      const txt = state.sents.map((s) => `[${fmt(s.start_sec)}-${fmt(s.end_sec)}] ${s.text}`).join("\n");
      const blob = new Blob([txt], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "lecture_script.txt"; a.click();
      dispatch({ type: "APP_LOG", message: "台本テキストをエクスポートしました", meta: { type: "export_script" } });
      addToast("ok", "📄 台本をエクスポートしました");
      return;
    }

    // ── 動画 / 音声（バックエンド） ──
    setExportProgress({
      status: "running",
      type,
      progress: 3,
      message: "書き出しを準備しています",
    });
    addToast("in", "⏳ 生成中...");
    dispatch({ type: "APP_LOG", message: `メディア書き出しを開始しました（type=${type}）`, meta: { type: "export_start", export_type: type } });
    try {
      await persistResearchSession(`export_${type}`);
      setExportProgress((current) => ({
        ...current,
        progress: 8,
        message: "書き出しを準備しています",
      }));
      let mediaResponse;
      let ext;
      if (type === "audio") {
        await ensureLatestDraftSaved?.();
        const submitted = await submitPreviewAudio({
          project_id: state.projectMeta.id,
          run_id: state.genRef.run_id,
          scope: "all",
          sentences: state.sents,
          generation_ref: state.genRef ?? {},
          settings: {
            detail: DETAIL_VALS[state.detail],
            difficulty: DIFF_VALS[state.level],
            preview_mode: state.prevMode,
            play_speed: state.playSpeed,
          },
        });
        const job = await waitForJob(submitted, {
          pollIntervalMs: 1200,
          onProgress: (currentJob) => {
            setExportProgress((current) => ({
              ...current,
              progress: Math.min(92, Math.max(8, Number(currentJob?.progress ?? current.progress))),
              message: "音声を書き出しています",
            }));
          },
        });
        const preview = job.result;
        setExportProgress((current) => ({
          ...current,
          progress: 94,
          message: "ファイルを準備しています",
        }));
        mediaResponse = await authFetch(preview.audio_url, { method: "GET" });
        ext = "mp3";
      } else {
        const saved = await ensureLatestDraftSaved?.();
        const draftVersion = Number(
          saved?.draft_version
          ?? saved?.data?.project_meta?.version_number
          ?? state.projectMeta?.version_number,
        );
        const res = await authFetch("/api/preview/final-render", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: state.projectMeta.id,
            run_id: state.genRef.run_id,
            type,
            draft_version: draftVersion,
          }),
        });
        if (!res.ok) {
          throw new Error(await responseErrorMessage(res, `動画生成を開始できませんでした（HTTP ${res.status}）`));
        }
        const submitted = await res.json();
        let job = submitted;
        setExportProgress((current) => ({
          ...current,
          progress: Math.max(8, Number(submitted?.progress ?? 8)),
          message: "動画を書き出しています",
        }));
        while (job.status === "queued" || job.status === "running") {
          await new Promise((resolve) => setTimeout(resolve, 1800));
          const poll = await authFetch(`/api/jobs/${submitted.job_id}`, { method: "GET" });
          if (!poll.ok) {
            throw new Error(await responseErrorMessage(poll, `生成状況を取得できませんでした（HTTP ${poll.status}）`));
          }
          job = await poll.json();
          setExportProgress((current) => ({
            ...current,
            progress: Math.min(92, Math.max(8, Number(job?.progress ?? current.progress))),
            message: "動画を書き出しています",
          }));
        }
        if (job.status !== "completed" || !job.result?.media_url) {
          throw new Error(job.error?.message || job.message || "動画生成に失敗しました");
        }
        setExportProgress((current) => ({
          ...current,
          progress: 94,
          message: "ファイルを準備しています",
        }));
        mediaResponse = await authFetch(job.result.media_url, { method: "GET" });
        ext = "mp4";
      }
      if (!mediaResponse?.ok) {
        throw new Error(await responseErrorMessage(
          mediaResponse,
          `生成ファイルを取得できませんでした（HTTP ${mediaResponse?.status ?? 500}）`,
        ));
      }
      setExportProgress((current) => ({
        ...current,
        progress: 97,
        message: "ダウンロードを開始しています",
      }));
      const blob = await mediaResponse.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = `lecture.${ext}`; a.click();
      dispatch({ type: "APP_LOG", message: `メディア書き出しが完了しました（type=${type}, ext=${ext}）`, meta: { type: "export_success", export_type: type, ext } });
      setExportProgress({
        status: "completed",
        type,
        progress: 100,
        message: "書き出しが完了しました",
      });
      addToast("ok", "✅ エクスポート完了");
    } catch (err) {
      const message = err?.message || "メディア書き出しに失敗しました";
      dispatch({ type: "APP_LOG", message: `メディア書き出しに失敗しました（type=${type}, reason=${message}）`, meta: { type: "export_error", export_type: type, reason: message } });
      const networkFailure = /Failed to fetch|NetworkError|Load failed/i.test(message);
      setExportProgress((current) => ({
        ...current,
        status: "error",
        message: "書き出しに失敗しました",
      }));
      addToast("er", networkFailure ? "バックエンドへ接続できませんでした" : `書き出しに失敗しました．${message}`);
    }
  };

  return (
    <aside style={{ width: 380, background: "var(--sur)", borderLeft: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0 }}>
      <div style={{ padding: 12 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 10 }}>書き出し</div>
        {exportProgress.status !== "idle" && (
          <div
            aria-live="polite"
            style={{
              padding: "10px 11px",
              marginBottom: 8,
              background: exportProgress.status === "error" ? "rgba(232,92,92,.09)" : "rgba(110,193,255,.08)",
              border: `1px solid ${exportProgress.status === "error" ? "rgba(232,92,92,.35)" : "rgba(110,193,255,.28)"}`,
              borderRadius: "var(--r)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700 }}>
                {exportProgress.status === "completed" ? "書き出し完了" : exportProgress.status === "error" ? "書き出し失敗" : "書き出し中"}
                {exportProgress.type ? `・${EXPORT_LABELS[exportProgress.type]}` : ""}
              </span>
              <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--ac)" }}>
                {Math.round(exportProgress.progress)}%
              </span>
            </div>
            <div style={{ height: 4, overflow: "hidden", borderRadius: 999, background: "rgba(255,255,255,.08)", marginBottom: 6 }}>
              <div
                style={{
                  width: `${Math.max(0, Math.min(100, exportProgress.progress))}%`,
                  height: "100%",
                  borderRadius: 999,
                  background: exportProgress.status === "error" ? "var(--rd)" : "var(--ac)",
                  transition: "width .3s ease",
                }}
              />
            </div>
            <div style={{ fontSize: 9, lineHeight: 1.45, color: exportProgress.status === "error" ? "var(--rd)" : "var(--ts)" }}>
              {exportProgress.message}
            </div>
          </div>
        )}
        <div style={{ padding: "8px 10px", marginBottom: 8, background: "var(--s2)", border: "1px solid var(--bd)", borderRadius: "var(--r)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: "var(--ts)" }}>操作ログ</span>
            <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--ac)" }}>{state.opLogs.length}件</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 88, overflowY: "auto" }}>
            {state.opLogs.length === 0 ? (
              <span style={{ fontSize: 10, color: "var(--tm)" }}>まだログはありません</span>
            ) : (
              state.opLogs.slice(-4).reverse().map((log) => (
                <div key={log.id} style={{ fontSize: 9, color: "var(--tm)", lineHeight: 1.45 }}>
                  <div style={{ fontFamily: "var(--fm)", color: "var(--ac)" }}>{new Date(log.at).toLocaleTimeString("ja-JP", { hour12: false })}</div>
                  <div style={{ color: "var(--ts)" }}>{log.message}</div>
                </div>
              ))
            )}
          </div>
        </div>
        {exportRows.map(([nm, tp, ext]) => (
          <div
            key={tp}
            onClick={() => doExport(tp)}
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 11px", border: "1px solid var(--bd)", borderRadius: "var(--r)", marginBottom: 5, cursor: isBusy ? "not-allowed" : "pointer", transition: "var(--tr)", opacity: isBusy ? 0.55 : 1 }}
            onMouseEnter={(e) => {
              if (!isBusy) e.currentTarget.style.background = "var(--s2)";
            }}
            onMouseLeave={(e) => (e.currentTarget.style.background = "")}
          >
            <div>
              <div style={{ fontSize: 12, fontWeight: 500 }}>{nm}</div>
              <div style={{ fontSize: 9, color: "var(--tm)" }}>{ext}</div>
            </div>
            <span>
              {isExporting && exportProgress.type === tp
                ? `${Math.round(exportProgress.progress)}%`
                : "↓"}
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}
