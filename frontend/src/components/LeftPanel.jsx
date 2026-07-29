import { useEffect, useRef, useState } from "react";
import Seg from "./Seg.jsx";
import { DETAIL_LABELS, DIFF_LABELS, DETAIL_VALS, DIFF_VALS } from "../utils/constants.js";
import { authFetch } from "../utils/sessionStore.js";
import { isPdfFile, makeDemo } from "../utils/helpers.js";

const JOB_POLL_MS = 2000;
const ENABLE_DEMO_FALLBACK = import.meta.env.VITE_ENABLE_DEMO_FALLBACK === "1";

function isReviewEnabled(mode) {
  return Boolean(mode) && mode !== "off";
}

function sentenceIdsForHighlight(highlight) {
  if (Array.isArray(highlight?.sentence_ids)) {
    return highlight.sentence_ids.map((id) => String(id)).filter(Boolean);
  }
  return highlight?.sid ? [String(highlight.sid)] : [];
}

function highlightOverlapScore(a, b) {
  if (!a || !b || Number(a.slide_idx) !== Number(b.slide_idx)) return 0;
  const ax2 = Number(a.x ?? 0) + Number(a.w ?? 0);
  const ay2 = Number(a.y ?? 0) + Number(a.h ?? 0);
  const bx2 = Number(b.x ?? 0) + Number(b.w ?? 0);
  const by2 = Number(b.y ?? 0) + Number(b.h ?? 0);
  const ix1 = Math.max(Number(a.x ?? 0), Number(b.x ?? 0));
  const iy1 = Math.max(Number(a.y ?? 0), Number(b.y ?? 0));
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  const iw = Math.max(0, ix2 - ix1);
  const ih = Math.max(0, iy2 - iy1);
  const inter = iw * ih;
  const union = Number(a.w ?? 0) * Number(a.h ?? 0) + Number(b.w ?? 0) * Number(b.h ?? 0) - inter;
  return union > 0 ? inter / union : 0;
}

function mergeGeneratedAssignmentsIntoReviewedLayout(reviewedHighlights, generatedHighlights) {
  const used = new Set();
  return (reviewedHighlights ?? []).map((reviewed) => {
    let best = null;
    let bestScore = 0;
    for (const generated of generatedHighlights ?? []) {
      if (used.has(generated.id)) continue;
      const score = highlightOverlapScore(reviewed, generated);
      if (score > bestScore) {
        best = generated;
        bestScore = score;
      }
    }
    if (!best || bestScore < 0.25) {
      return { ...reviewed, sentence_ids: reviewed.sentence_ids ?? [] };
    }
    used.add(best.id);
    const sentenceIds = sentenceIdsForHighlight(best);
    return {
      ...reviewed,
      sentence_ids: sentenceIds,
      sid: sentenceIds[0] ?? undefined,
    };
  });
}

function mergeFinalResultWithCurrentLayout(finalResult, currentState, partialLayoutLoaded) {
  if (!partialLayoutLoaded || finalResult?.mode === "audio") return finalResult;
  return {
    ...finalResult,
    highlights: mergeGeneratedAssignmentsIntoReviewedLayout(currentState?.hls ?? [], finalResult?.highlights ?? []),
  };
}

export default function LeftPanel({
  state,
  dispatch,
  pdfFile,
  setPdfFile,
  currentJobId,
  setCurrentJobId,
  onSelectPdf,
  addToast,
  requestConfirm,
  handleReset,
  saveProjectNow,
  prepareProjectForGeneration,
  isDirty,
  hasPersistedSnapshot = false,
  reviewSettings,
  startReviewFlow,
  clearReviewFlow,
}) {
  const [drag, setDrag] = useState(false);
  const latestStateRef = useRef(state);
  const fileInputRef = useRef(null);
  const sourcePdfReady = Boolean(
    pdfFile
    || (state.inputPdf?.available && (state.inputPdf?.artifact_id || state.inputPdf?.storage_key)),
  );
  const sourcePdfName = pdfFile?.name ?? state.inputPdf?.name ?? "slides.pdf";
  const pdfReference = pdfFile
    ? { name: pdfFile.name, size: pdfFile.size, ready: true }
    : (state.inputPdf ? { ...state.inputPdf, ready: sourcePdfReady } : null);
  const needsSave = isDirty || !hasPersistedSnapshot;
  const isGenerating = state.status === "proc";
  const saveStatusLabel = hasPersistedSnapshot ? (isDirty ? "未保存" : "保存済み") : "未保存";
  const saveStatusText = hasPersistedSnapshot
    ? (isDirty ? "未保存の変更があります" : "保存済みの状態です")
    : "まだ保存されていません";

  useEffect(() => {
    latestStateRef.current = state;
  }, [state]);

  const handleFile = (f) => {
    if (isGenerating) {
      addToast("er", "生成中は PDF を変更できません。先に生成を停止してください");
      return;
    }
    if (!isPdfFile(f)) return;
    onSelectPdf?.(f);
  };

  const startGen = async () => {
    if (isGenerating) return;
    if (!sourcePdfReady) {
      addToast("er", "PDFをアップロードしてサーバへ保存してください");
      return;
    }
    dispatch({
      type: "APP_LOG",
      message: `生成を開始しました（file=${sourcePdfName}, detail=${DETAIL_VALS[state.detail]}, difficulty=${DIFF_VALS[state.level]}, mode=${state.appMode}）`,
      meta: { type: "generate_start", filename: sourcePdfName, detail: DETAIL_VALS[state.detail], difficulty: DIFF_VALS[state.level], mode: state.appMode },
    });
    clearReviewFlow?.();
    dispatch({ type: "SET", k: "status",    v: "proc"           });
    dispatch({ type: "SET", k: "statusMsg", v: "スライドを解析中..." });
    dispatch({ type: "SET", k: "showProg",  v: true             });
    dispatch({ type: "SET", k: "progress",  v: 10               });
    const layoutReviewEnabled = state.appMode === "hl" && isReviewEnabled(reviewSettings?.layout_review_mode);
    const scriptReviewEnabled = isReviewEnabled(reviewSettings?.script_review_mode);
    try {
      const savedProject = await prepareProjectForGeneration?.();
      const projectId = savedProject?.id
        ?? savedProject?.data?.project_meta?.id
        ?? state.projectMeta?.id;
      const sourceArtifactId = savedProject?.source_artifact?.id
        ?? savedProject?.data?.input_pdf?.artifact_id
        ?? savedProject?.data?.input_pdf?.storage_key
        ?? state.inputPdf?.artifact_id
        ?? state.inputPdf?.storage_key;
      if (!projectId || !sourceArtifactId) {
        throw new Error("PDFのサーバ保存が完了していません");
      }
      dispatch({ type: "SET", k: "progress",  v: 20        });
      dispatch({ type: "SET", k: "statusMsg", v: "生成ジョブを登録中..." });
      const res = await authFetch(`/api/projects/${projectId}/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_artifact_id: sourceArtifactId,
          detail: DETAIL_VALS[state.detail],
          difficulty: DIFF_VALS[state.level],
          mode: state.appMode,
          usage_context: savedProject?.usage_context ?? "general",
          layout_review_enabled: layoutReviewEnabled,
          script_review_enabled: scriptReviewEnabled,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      let job = await res.json();
      const generationRunId = job?.generation_run?.id ?? job?.payload?.run_id ?? null;
      setCurrentJobId(job.job_id);
      let layoutPartialLoaded = false;
      const maybeLoadLayoutPartial = (nextJob) => {
        const partial = nextJob?.partial_result;
        const partialData = partial?.data;
        if (layoutPartialLoaded) return;
        if (partial?.stage !== "layout_ready" || !partialData?.slides?.length) return;
        if (!layoutReviewEnabled) return;
        layoutPartialLoaded = true;
        const data = {
          ...partialData,
          generation_ref: {
            ...(partialData.generation_ref ?? {}),
            job_id: nextJob.job_id,
            run_id: generationRunId,
            partial: true,
            partial_stage: "layout_ready",
          },
        };
        dispatch({ type: "LOAD", d: data });
        dispatch({ type: "SET", k: "status", v: "proc" });
        dispatch({ type: "SET", k: "showProg", v: true });
        dispatch({ type: "SET", k: "progress", v: Math.max(42, Number(nextJob.progress ?? 42)) });
        dispatch({ type: "SET", k: "statusMsg", v: "領域確認を開始できます。確認中に台本生成を進めます" });
        dispatch({
          type: "APP_LOG",
          message: `LayoutParser の結果を先行表示しました（job_id=${nextJob.job_id}）`,
          meta: { type: "generate_partial_layout_ready", job_id: nextJob.job_id },
        });
        startReviewFlow?.(data);
        addToast("ok", "領域確認を開始できます");
      };
      dispatch({
        type: "APP_LOG",
        message: `生成ジョブを受け付けました（job_id=${job.job_id}, status=${job.status}, kg=${job.experiment_condition?.kg_mode ?? "off"}）`,
        meta: { type: "generate_job_accepted", job_id: job.job_id, status: job.status, experiment_condition: job.experiment_condition ?? null },
      });
      maybeLoadLayoutPartial(job);

      while (job.status === "queued" || job.status === "running") {
        dispatch({ type: "SET", k: "progress", v: Math.max(20, Number(job.progress ?? 20)) });
        dispatch({
          type: "SET",
          k: "statusMsg",
          v: layoutPartialLoaded
            ? `${job.message || "バックエンドで生成中..."}（領域確認は進行できます）`
            : (job.message || "バックエンドで生成中..."),
        });
        await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS));
        const pollRes = await authFetch(`/api/jobs/${job.job_id}`);
        if (!pollRes.ok) throw new Error(`HTTP ${pollRes.status}`);
        job = await pollRes.json();
        maybeLoadLayoutPartial(job);
      }

      if (job.status === "cancelled") {
        dispatch({ type: "SET", k: "status", v: "stop" });
        dispatch({ type: "SET", k: "statusMsg", v: job.message || "生成を停止しました" });
        dispatch({ type: "SET", k: "showProg", v: false });
        dispatch({
          type: "APP_LOG",
          message: `生成を停止しました（job_id=${job.job_id}）`,
          meta: { type: "generate_cancelled", job_id: job.job_id, mode: state.appMode },
        });
        addToast("in", "生成を停止しました");
        setCurrentJobId(null);
        return;
      }

      if (job.status !== "completed" || !job.result) {
        throw new Error(job.error?.message || "生成ジョブが失敗しました");
      }

      const finalResult = mergeFinalResultWithCurrentLayout(job.result, latestStateRef.current, layoutPartialLoaded);
      if (Number(finalResult.draft_version) > 0) {
        dispatch({
          type: "SET",
          k: "projectMeta",
          v: {
            ...(latestStateRef.current.projectMeta ?? {}),
            version_number: Number(finalResult.draft_version),
          },
        });
      }
      dispatch({ type: "SET",  k: "progress",  v: 92             });
      dispatch({ type: "SET",  k: "statusMsg", v: "データを読み込み中..." });
      const stoppedAtLayoutReview = finalResult.pipeline_stage === "layout_ready";
      if (stoppedAtLayoutReview) {
        if (!layoutPartialLoaded) {
          dispatch({ type: "LOAD", d: finalResult });
          startReviewFlow?.(finalResult);
        } else if (finalResult.generation_ref) {
          dispatch({ type: "SET", k: "genRef", v: finalResult.generation_ref });
          dispatch({
            type: "APP_LOG",
            message: `領域確認用の生成参照を更新しました（job_id=${job.job_id}）`,
            meta: { type: "layout_generation_ref_updated", job_id: job.job_id, generation_ref: finalResult.generation_ref },
          });
        }
      } else if (layoutPartialLoaded) {
        dispatch({ type: "MERGE_SCRIPT_RESULT", d: finalResult });
      } else {
        dispatch({ type: "LOAD", d: finalResult });
      }
      dispatch({ type: "SET",  k: "progress",  v: 100   });
      dispatch({ type: "SET",  k: "status",    v: "done" });
      dispatch({
        type: "SET",
        k: "statusMsg",
        v: stoppedAtLayoutReview
          ? "領域確認を完了してください"
          : layoutPartialLoaded
            ? "台本生成まで完了。領域確認を完了してください"
            : "生成完了",
      });
      dispatch({
        type: "APP_LOG",
        message: `生成が完了しました（backend, mode=${state.appMode}, job_id=${job.job_id}, cache_hit=${job.cache_hit}）`,
        meta: { type: "generate_success", source: "backend", mode: state.appMode, job_id: job.job_id, cache_hit: job.cache_hit },
      });
      setCurrentJobId(null);
      addToast("ok", stoppedAtLayoutReview ? "領域確認を完了してください" : layoutPartialLoaded ? "台本生成まで完了しました" : "✅ 講義メディアを生成しました");
      if (!stoppedAtLayoutReview && !layoutPartialLoaded && (isReviewEnabled(reviewSettings?.layout_review_mode) || isReviewEnabled(reviewSettings?.script_review_mode))) {
        startReviewFlow?.(finalResult);
      }
    } catch (err) {
      console.warn("Backend generate failed:", err.message);
      const backendUnavailable = /Failed to fetch|HTTP 404|HTTP 500|HTTP 502|HTTP 503/.test(String(err.message));
      if (ENABLE_DEMO_FALLBACK && backendUnavailable) {
        dispatch({ type: "SET", k: "progress",  v: 60            });
        dispatch({ type: "SET", k: "statusMsg", v: "デモデータを準備中..." });
        await new Promise((r) => setTimeout(r, 300));
        dispatch({ type: "LOAD", d: { ...makeDemo(), mode: state.appMode } });
        dispatch({ type: "SET", k: "progress",  v: 100              });
        dispatch({ type: "SET", k: "status",    v: "done"            });
        dispatch({ type: "SET", k: "statusMsg", v: "生成完了（デモ）" });
        dispatch({
          type: "APP_LOG",
          message: `バックエンド接続に失敗したためデモデータを読み込みました（reason=${err.message}）`,
          meta: { type: "generate_fallback_demo", reason: err.message, mode: state.appMode },
        });
        setCurrentJobId(null);
        addToast("in", "🔧 バックエンド未接続 — デモデータで表示");
        if (isReviewEnabled(reviewSettings?.layout_review_mode) || isReviewEnabled(reviewSettings?.script_review_mode)) {
          startReviewFlow?.({ ...makeDemo(), mode: state.appMode });
        }
      } else {
        dispatch({ type: "SET", k: "status", v: "err" });
        dispatch({ type: "SET", k: "statusMsg", v: err.message || "生成に失敗しました" });
        dispatch({
          type: "APP_LOG",
          message: `生成に失敗しました（reason=${err.message ?? "unknown"}）`,
          meta: { type: "generate_error", reason: err.message ?? "unknown", mode: state.appMode },
        });
        setCurrentJobId(null);
        addToast("er", err.message || "生成に失敗しました");
      }
    }
    setTimeout(() => dispatch({ type: "SET", k: "showProg", v: false }), 800);
  };

  const stopGeneration = () => {
    if (!currentJobId || !isGenerating) return;
    requestConfirm({
      title: "生成を停止",
      message: "現在の生成ジョブを停止しますか？\n停止すると途中までの結果は破棄され、あとで設定を変えて再生成できます。",
      confirmLabel: "停止する",
      confirmColor: "var(--am)",
      confirmBg: "var(--amd)",
      confirmBorder: "rgba(232,169,75,.35)",
      onConfirm: async () => {
        try {
          const res = await authFetch(`/api/jobs/${currentJobId}/cancel`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          dispatch({ type: "SET", k: "statusMsg", v: "生成停止をリクエストしました..." });
          dispatch({
            type: "APP_LOG",
            message: `生成停止をリクエストしました（job_id=${currentJobId}）`,
            meta: { type: "generate_cancel_requested", job_id: currentJobId, mode: state.appMode },
          });
          addToast("in", "生成停止をリクエストしました");
        } catch (err) {
          addToast("er", err.message || "生成停止に失敗しました");
        }
      },
    });
  };

  const handleSaveProject = () => {
    saveProjectNow?.();
  };

  const statusStyle = {
    idle: { background: "var(--s2)",  color: "var(--tm)" },
    proc: { background: "var(--amd)", border: "1px solid rgba(232,169,75,.28)", color: "var(--am)" },
    done: { background: "var(--gd)",  border: "1px solid rgba(76,175,130,.28)",  color: "var(--gr)" },
    stop: { background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.1)", color: "var(--ts)" },
    err:  { background: "var(--rdd)", border: "1px solid rgba(224,91,91,.28)",   color: "var(--rd)" },
  }[state.status];

  const modeLocked = state.generated || isGenerating;

  return (
    <aside style={{ background: "var(--sur)", borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0, minHeight: 0, height: "100%", width: "100%" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>

        {/* ─── アップロード ─── */}
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>プロジェクト</div>
        <div style={{ padding: "8px 9px", borderRadius: "var(--r)", background: "var(--s2)", border: "1px solid var(--bd)", marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 8 }}>
            <button
              onClick={handleSaveProject}
              style={{
                minWidth: 96,
                padding: "9px 16px",
                border: "1px solid rgba(130,178,255,.42)",
                borderRadius: 9,
                background: needsSave
                  ? "linear-gradient(180deg, rgba(122,165,242,.98), rgba(91,141,239,.88))"
                  : "linear-gradient(180deg, rgba(58,79,122,.98), rgba(47,67,104,.92))",
                color: "#fff",
                fontSize: 11,
                fontWeight: 700,
                opacity: 1,
                boxShadow: needsSave
                  ? "inset 0 1px 0 rgba(255,255,255,.18), 0 10px 22px rgba(91,141,239,.22), 0 1px 0 rgba(7,8,11,.38)"
                  : "inset 0 1px 0 rgba(255,255,255,.12), 0 6px 14px rgba(39,57,92,.18), 0 1px 0 rgba(7,8,11,.32)",
                letterSpacing: ".04em",
                cursor: "pointer",
              }}
            >
              保存
            </button>
            <div style={{ fontSize: 9, color: needsSave ? "var(--am)" : "var(--gr)", background: needsSave ? "var(--amd)" : "var(--gd)", border: `1px solid ${needsSave ? "rgba(232,169,75,.28)" : "rgba(76,175,130,.28)"}`, borderRadius: 999, padding: "2px 8px", whiteSpace: "nowrap" }}>
              {saveStatusLabel}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <div>
              <div style={{ fontSize: 10, color: "var(--ts)", marginBottom: 2 }}>
                現在: {state.projectMeta?.name ?? "未保存"}
              </div>
              <div style={{ fontSize: 9, color: "var(--tm)" }}>
                {saveStatusText}
              </div>
            </div>
            <div style={{ width: 10, height: 10, borderRadius: 999, background: needsSave ? "var(--am)" : "var(--gr)", boxShadow: needsSave ? "0 0 0 4px rgba(232,169,75,.12)" : "0 0 0 4px rgba(76,175,130,.12)" }} />
          </div>
        </div>

        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>入力スライド</div>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!isGenerating) setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            if (isGenerating) {
              addToast("er", "生成中は PDF を変更できません。先に生成を停止してください");
              return;
            }
            handleFile(e.dataTransfer.files[0]);
          }}
          style={{
            border: `2px dashed ${isGenerating ? "rgba(232,169,75,.4)" : sourcePdfReady ? "rgba(76,175,130,.58)" : drag ? "var(--ac)" : "var(--bd2)"}`,
            borderRadius: "var(--rl)",
            padding: "14px 10px",
            textAlign: "center",
            cursor: isGenerating ? "not-allowed" : "pointer",
            transition: "var(--tr)",
            position: "relative",
            marginBottom: 8,
            background: isGenerating
              ? "linear-gradient(180deg, rgba(232,169,75,.10), rgba(232,169,75,.04))"
              : sourcePdfReady
              ? "linear-gradient(180deg, rgba(76,175,130,.14), rgba(76,175,130,.05))"
              : drag
                ? "var(--adim)"
                : "none",
            boxShadow: sourcePdfReady ? "inset 0 0 0 1px rgba(76,175,130,.18), 0 10px 24px rgba(76,175,130,.08)" : "none",
          }}
        >
          {/* key={pdfFile} でリセット後に input を再マウント → ファイル選択が再度できるようになる */}
          <input
            ref={fileInputRef}
            key={pdfFile ? "has-file" : pdfReference ? "has-pdf-reference" : "no-file"}
            type="file"
            accept=".pdf"
            onChange={(e) => handleFile(e.target.files[0])}
            disabled={isGenerating}
            style={{ position: "absolute", inset: 0, opacity: 0, cursor: isGenerating ? "not-allowed" : "pointer" }}
          />
          {pdfReference && (
            <div style={{ position: "absolute", top: 8, right: 8, padding: "2px 8px", borderRadius: 999, background: "var(--gd)", border: "1px solid rgba(76,175,130,.32)", color: "var(--gr)", fontSize: 9, fontWeight: 700 }}>
              {pdfFile ? "選択済み" : "サーバ保存済み"}
            </div>
          )}
          <div style={{ fontSize: 20, marginBottom: 4 }}>{isGenerating ? "⏳" : sourcePdfReady ? "✅" : "📑"}</div>
          <p style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.45 }}>
            <strong style={{ color: isGenerating ? "var(--am)" : sourcePdfReady ? "var(--gr)" : "var(--ac)" }}>
              {isGenerating ? "生成中は変更できません" : sourcePdfReady ? "別の PDF で新規作成" : "クリック or ドロップ"}
            </strong>
            <br />
            {isGenerating ? "停止または完了後に PDF を変更できます" : sourcePdfReady ? "サーバ保存済みPDFから生成できます" : "PDFを選択"}
          </p>
          <small style={{ fontSize: 9, color: sourcePdfReady ? "rgba(228,230,239,.78)" : "var(--tm)" }}>
            {sourcePdfReady ? "この PDF を使って講義メディアを生成します" : "PDF / max 60MB"}
          </small>
        </div>

        {pdfReference && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 9px", background: "linear-gradient(180deg, rgba(76,175,130,.18), rgba(76,175,130,.1))", border: "1px solid rgba(76,175,130,.42)", borderRadius: "var(--r)", marginBottom: 8, boxShadow: "0 8px 18px rgba(76,175,130,.08)" }}>
            <span style={{ fontSize: 13 }}>✅</span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 9, color: "rgba(228,230,239,.72)", marginBottom: 2 }}>{pdfFile ? "現在選択中の PDF" : "サーバ保存済み PDF"}</div>
              <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--tp)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{pdfReference.name}</div>
            </div>
            <button
              onClick={(event) => {
                event.stopPropagation();
                fileInputRef.current?.click();
              }}
              disabled={isGenerating}
              style={{ padding: "3px 7px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "rgba(19,21,26,.68)", color: "var(--tp)", fontSize: 10, opacity: isGenerating ? 0.55 : 1, cursor: isGenerating ? "not-allowed" : "pointer" }}
            >
              別PDFを選択
            </button>
          </div>
        )}

        {/* ─── 学習者要求3軸 ─── */}
        <div style={{ height: 12 }} />
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)" }}>学習者要求</div>
          {modeLocked && (
            <span style={{ fontSize: 9, color: "var(--am)", background: "var(--amd)", border: "1px solid rgba(232,169,75,.3)", padding: "1px 7px", borderRadius: 10 }}>
              🔒 {isGenerating ? "生成中" : "生成済み"}
            </span>
          )}
        </div>

        {[
          ["詳細度", "detail", DETAIL_LABELS, ["要約", "標準", "精緻"]],
          ["難易度", "level",  DIFF_LABELS,   ["入門", "基礎", "発展"]],
        ].map(([lbl, key, fullLabels, shortLabels]) => (
          <div key={key} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: "var(--ts)" }}>{lbl}</span>
              <span style={{ fontFamily: "var(--fm)", fontSize: 9, padding: "1px 5px", borderRadius: 20, background: "var(--adim)", color: "var(--ac)", border: "1px solid rgba(91,141,239,.22)" }}>
                {fullLabels[state[key]]}
              </span>
            </div>
            <Seg opts={shortLabels.map((l, i) => ({ v: i, l }))} val={state[key]} onChange={(v) => dispatch({ type: "SET", k: key, v })} disabled={isGenerating} />
          </div>
        ))}

        {/* 提示形態（生成後ロック） */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: "var(--ts)" }}>提示形態</span>
            <span style={{ fontFamily: "var(--fm)", fontSize: 9, padding: "1px 5px", borderRadius: 20, background: "var(--adim)", color: "var(--ac)", border: "1px solid rgba(91,141,239,.22)" }}>
              {{ audio: "音声", video: "動画", hl: "HL動画" }[state.appMode]}
            </span>
          </div>
          {modeLocked ? (
            <div style={{ padding: "7px 10px", background: "var(--s2)", border: "1px solid var(--bd)", borderRadius: "var(--r)", fontSize: 11, color: "var(--ts)", display: "flex", alignItems: "center", gap: 6 }}>
              <span>{{ audio: "🔊", video: "📹", hl: "🎬" }[state.appMode]}</span>
              <span>{{ audio: "音声のみ", video: "動画", hl: "HL動画" }[state.appMode]}</span>
              <span style={{ marginLeft: "auto", fontSize: 9, color: "var(--tm)" }}>{isGenerating ? "完了後に変更" : "リセット後に変更"}</span>
            </div>
          ) : (
            <Seg
              opts={[{ v: "audio", l: "音声" }, { v: "video", l: "動画" }, { v: "hl", l: "HL動画" }]}
              val={state.appMode}
              onChange={(v) => dispatch({ type: "SET", k: "appMode", v })}
              disabled={isGenerating}
            />
          )}
        </div>

        {/* ─── 生成ボタン ─── */}
        <div style={{ display: "grid", gridTemplateColumns: isGenerating ? "1fr auto" : "1fr", gap: 8, marginBottom: 10 }}>
          <button
            onClick={startGen}
            disabled={isGenerating}
            style={{
              width: "100%",
              padding: 9,
              background: isGenerating ? "rgba(91,141,239,.36)" : "var(--ac)",
              border: "none",
              borderRadius: "var(--r)",
              color: "#fff",
              fontFamily: "var(--fb)",
              fontSize: 12,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 5,
              cursor: isGenerating ? "not-allowed" : "pointer",
            }}
          >
            ⚡ 講義メディア生成
          </button>
          {isGenerating && (
            <button
              onClick={stopGeneration}
              style={{
                padding: "9px 12px",
                border: "1px solid rgba(232,169,75,.34)",
                borderRadius: "var(--r)",
                background: "var(--amd)",
                color: "var(--am)",
                fontSize: 11,
                fontWeight: 700,
                whiteSpace: "nowrap",
              }}
            >
              生成停止
            </button>
          )}
        </div>

        {/* ─── ステータス ─── */}
        <div style={{ ...statusStyle, padding: "6px 8px", borderRadius: "var(--r)", fontSize: 10, display: "flex", alignItems: "center", gap: 5, marginBottom: 4 }}>
          {isGenerating && (
            <div style={{ width: 9, height: 9, border: "1.5px solid rgba(232,169,75,.22)", borderTopColor: "var(--am)", borderRadius: "50%", animation: "lc-spin .8s linear infinite", flexShrink: 0 }} />
          )}
          <span>{{ idle: "⏸ ", done: "✅ ", err: "❌ ", proc: "", stop: "■ " }[state.status]}{state.statusMsg}</span>
        </div>
        {state.showProg && (
          <div style={{ height: 2, background: "var(--s2)", borderRadius: 1, overflow: "hidden", marginTop: 3 }}>
            <div style={{ height: "100%", background: "var(--ac)", width: state.progress + "%", transition: "width .3s ease" }} />
          </div>
        )}

        {/* ─── スライド一覧 ─── */}
        <div style={{ height: 10 }} />
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>スライド一覧</div>
        {state.slides.length === 0 ? (
          <div style={{ color: "var(--tm)", fontSize: 10, textAlign: "center", padding: "10px 0" }}>生成後に表示</div>
        ) : (
          state.slides.map((sl, i) => {
            const ct = state.hls.filter((h) => h.slide_idx === i).length;
            return (
              <div key={sl.id} onClick={() => dispatch({ type: "SEEK_SLIDE", v: i })} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 7px", borderRadius: "var(--r)", border: `1px solid ${i === state.curSl ? "var(--ac)" : "var(--bd)"}`, cursor: "pointer", background: i === state.curSl ? "var(--adim)" : "var(--s2)", marginBottom: 3 }}>
                <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", width: 15, textAlign: "right", flexShrink: 0 }}>{i + 1}</span>
                <div style={{ width: 36, height: 22, background: sl.color ?? "var(--s3)", borderRadius: 3, overflow: "hidden", flexShrink: 0, display: "grid", placeItems: "center", fontSize: 9, color: "var(--tm)" }}>
                  {sl.image_base64 ? <img src={`data:image/png;base64,${sl.image_base64}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} alt="" /> : "🖼"}
                </div>
                <span style={{ fontSize: 10, color: "var(--ts)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{sl.title}</span>
                {ct > 0 && <span style={{ fontFamily: "var(--fm)", fontSize: 9, padding: "1px 4px", borderRadius: 7, background: "var(--adim)", color: "var(--ac)", flexShrink: 0 }}>{ct}</span>}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
