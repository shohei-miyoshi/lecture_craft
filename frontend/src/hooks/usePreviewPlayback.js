import { useEffect, useMemo, useRef, useState } from "react";
import { DETAIL_VALS, DIFF_VALS } from "../utils/constants.js";
import { buildSentenceHighlightsForExport } from "../utils/highlights.js";
import { authFetch } from "../utils/sessionStore.js";
import { submitPreviewAudio, waitForJob } from "../utils/jobClient.js";

function sortedSentences(rows) {
  return [...(rows ?? [])].sort((a, b) => (
    Number(a?.start_sec ?? 0) - Number(b?.start_sec ?? 0)
    || String(a?.id ?? "").localeCompare(String(b?.id ?? ""))
  ));
}

function currentPreviewSentences(state) {
  if (state.appMode === "audio") return sortedSentences(state.sents);
  return sortedSentences(state.sents.filter((sent) => sent.slide_idx === state.curSl));
}

function getPreviewScope(state, reviewStage = "editor") {
  const fullLecture = state.appMode === "audio" || reviewStage === "assignment" || reviewStage === "editor";
  return {
    scope: fullLecture ? "all" : "slide",
    slideIdx: fullLecture ? null : state.curSl,
    label: fullLecture ? "全体" : `スライド${state.curSl + 1}`,
  };
}

function previewSentencesForScope(state, scope) {
  if (scope.scope === "all") return sortedSentences(state.sents);
  return currentPreviewSentences(state);
}

function buildAudioFingerprint(state, sentences, scope) {
  if (!sentences.length) return "";
  return JSON.stringify({
    v: 3,
    scope: scope.scope,
    slide_idx: scope.slideIdx,
    sentences: sentences.map((sent) => ({
      id: sent.id,
      slide_idx: sent.slide_idx,
      text: String(sent.text ?? "").trim(),
      start_sec: Number(sent.start_sec ?? 0),
      end_sec: Number(sent.end_sec ?? 0),
    })),
  });
}

function previewRequestPayload(state, sentences, scope) {
  return {
    project_id: state.projectMeta?.id ?? null,
    run_id: state.genRef?.run_id ?? null,
    scope: scope.scope,
    slide_idx: scope.slideIdx,
    sentences,
    session_id: state.sessionId,
    generation_ref: state.genRef ?? {},
    settings: {
      detail: DETAIL_VALS[state.detail],
      difficulty: DIFF_VALS[state.level],
      preview_mode: state.prevMode,
      play_speed: state.playSpeed,
    },
  };
}

function preparingMessage(reason) {
  if (reason === "script_confirmed") return "台本確認後の音声を先行生成中...";
  if (reason === "edit_refresh") return "編集した文の音声を更新中...";
  return "プレビュー準備中...";
}

function readyMessage(reason, payload) {
  if (reason === "script_confirmed") return "音声付きプレビューを準備しました";
  if (reason === "edit_refresh") return "変更した文の音声を差し替えました";
  if (payload?.cache_hit) return "キャッシュ済み音声を準備しました";
  if (Number(payload?.sentence_cache_hits ?? 0) > 0) return "文単位キャッシュを使って音声を準備しました";
  return "音声プレビューを生成しました";
}

function firstSlideTime(state, slideIdx) {
  const rows = sortedSentences(state.sents.filter((sent) => sent.slide_idx === slideIdx));
  if (rows.length) return Number(rows[0].start_sec ?? 0) || 0;
  return 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function localToGlobal(localTime, timings) {
  const rows = timings ?? [];
  if (!rows.length) return localTime;
  const row = timingAtLocal(localTime, rows);
  if (row) {
    return Number(row.start_sec ?? 0) + (localTime - Number(row.local_start_sec ?? 0));
  }
  const first = rows[0];
  const last = rows[rows.length - 1];
  if (localTime <= Number(first.local_start_sec ?? 0)) return Number(first.start_sec ?? 0);
  return Number(last.end_sec ?? 0);
}

function timingAtLocal(localTime, timings) {
  return (timings ?? []).find((item) => Number(item.local_start_sec ?? 0) <= localTime && localTime < Number(item.local_end_sec ?? 0));
}

function timingAtGlobal(globalTime, timings) {
  return (timings ?? []).find((item) => Number(item.start_sec ?? 0) <= globalTime && globalTime < Number(item.end_sec ?? 0));
}

function timelineDuration(timings, fallback = 0) {
  const rows = timings ?? [];
  if (!rows.length) return Math.max(0, Number(fallback ?? 0) || 0);
  const last = rows[rows.length - 1];
  return Math.max(0, Number(last.end_sec ?? last.local_end_sec ?? fallback) || 0);
}

function globalToLocal(globalTime, timings, duration = 0) {
  const rows = timings ?? [];
  if (!rows.length) return 0;
  const row = timingAtGlobal(globalTime, rows);
  if (row) {
    return Number(row.local_start_sec ?? 0) + (globalTime - Number(row.start_sec ?? 0));
  }
  const first = rows[0];
  const last = rows[rows.length - 1];
  if (globalTime <= Number(first.start_sec ?? 0)) return 0;
  if (globalTime >= Number(last.end_sec ?? 0)) return Math.max(0, Number(duration ?? last.local_end_sec ?? 0));
  return clamp(globalTime - Number(first.start_sec ?? 0), 0, Math.max(0, duration));
}

function isWithinPreview(globalTime, timings) {
  if (!timings?.length) return false;
  const first = timings[0];
  const last = timings[timings.length - 1];
  return globalTime >= Number(first.start_sec ?? 0) && globalTime <= Number(last.end_sec ?? 0);
}

function createFinalRenderPayload(state, draftVersion = null) {
  const type = state.appMode === "video" || state.prevMode === "plain" ? "video" : "video_highlight";
  return {
    type,
    project_id: state.projectMeta?.id,
    run_id: state.genRef?.run_id,
    draft_version: draftVersion ?? state.projectMeta?.version_number,
  };
}

export function usePreviewPlayback(state, dispatch, addToast, options = {}) {
  const reviewStage = options.reviewStage ?? "editor";
  const audioRef = useRef(null);
  const rafRef = useRef(null);
  const previewRef = useRef(null);
  const previewStateRef = useRef(null);
  const objectUrlRef = useRef(null);
  const finalVideoUrlRef = useRef(null);
  const stateRef = useRef(state);
  const reviewStageRef = useRef(reviewStage);
  const attachedProjectRunRef = useRef("");
  const requestIdRef = useRef(0);
  const inFlightFingerprintRef = useRef("");
  const unlockingPlaybackRef = useRef(false);
  const [preview, setPreview] = useState({
    status: "idle",
    message: "音声プレビュー未生成",
    fingerprint: "",
    audioUrl: "",
    cacheHit: false,
    source: "instant",
    timings: [],
  });
  const [finalRender, setFinalRender] = useState({
    status: "idle",
    message: "",
    progress: 0,
    jobId: null,
    videoUrl: "",
  });

  const previewScope = useMemo(() => getPreviewScope(state, reviewStage), [state.appMode, state.curSl, reviewStage]);
  const previewSentences = useMemo(() => previewSentencesForScope(state, previewScope), [state, previewScope]);
  const currentFingerprint = useMemo(() => buildAudioFingerprint(state, previewSentences, previewScope), [state, previewSentences, previewScope]);
  const isAudioStale = Boolean(
    state.previewAudioStale
    || (currentFingerprint && preview.fingerprint !== currentFingerprint),
  );
  const audioActive = preview.source === "audio" && ["ready", "playing", "paused", "preparing", "buffering"].includes(preview.status);

  const getLatestPreviewInputs = () => {
    const nextState = stateRef.current;
    const scope = getPreviewScope(nextState, reviewStageRef.current);
    const sentences = previewSentencesForScope(nextState, scope);
    return {
      nextState,
      scope,
      sentences,
      fingerprint: buildAudioFingerprint(nextState, sentences, scope),
    };
  };

  const prepareAudioPreview = async ({ reason = "manual", force = false } = {}) => {
    const { nextState, scope, sentences, fingerprint } = getLatestPreviewInputs();
    if (!sentences.length || !fingerprint) {
      setPreview((prev) => ({ ...prev, status: "instant", source: "instant", message: "音声なしの簡易プレビュー中" }));
      return null;
    }

    const current = previewStateRef.current;
    if (!force && current?.audioUrl && current.fingerprint === fingerprint) {
      return current;
    }

    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    inFlightFingerprintRef.current = fingerprint;
    setPreview((prev) => ({
      ...prev,
      status: "preparing",
      source: "audio",
      message: preparingMessage(reason),
    }));

    try {
      await options.ensureLatestDraftSaved?.();
      const submitted = await submitPreviewAudio(previewRequestPayload(nextState, sentences, scope));
      const job = await waitForJob(submitted, {
        onProgress: (currentJob) => {
          if (requestId !== requestIdRef.current) return;
          setPreview((prev) => ({
            ...prev,
            status: "preparing",
            source: "audio",
            message: currentJob.message || preparingMessage(reason),
          }));
        },
      });
      const payload = job.result;
      const mediaRes = await authFetch(payload.audio_url, { method: "GET" });
      if (!mediaRes.ok) throw new Error(`HTTP ${mediaRes.status}`);
      const blob = await mediaRes.blob();
      const latest = getLatestPreviewInputs();
      if (requestId !== requestIdRef.current || latest.fingerprint !== fingerprint) {
        return null;
      }
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = URL.createObjectURL(blob);
      const nextPreview = {
        status: "ready",
        message: readyMessage(reason, payload),
        fingerprint,
        audioUrl: objectUrlRef.current,
        cacheHit: Boolean(payload.cache_hit),
        source: "audio",
        timings: payload.sentence_timings ?? [],
      };
      previewRef.current = nextPreview;
      previewStateRef.current = nextPreview;
      setPreview(nextPreview);
      dispatch({ type: "SET_PREVIEW_AUDIO_STALE", v: false });
      const audio = audioRef.current;
      if (audio && audio.paused) {
        audio.src = nextPreview.audioUrl;
        audio.preload = "auto";
        audio.load();
      }
      dispatch({
        type: "APP_LOG",
        message: `音声プレビューを準備しました（scope=${scope.scope}, reason=${reason}, cache_hit=${Boolean(payload.cache_hit)}）`,
        meta: {
          type: "preview_audio_ready",
          scope: scope.scope,
          slide_idx: scope.slideIdx,
          reason,
          cache_hit: Boolean(payload.cache_hit),
          sentence_cache_hits: payload.sentence_cache_hits ?? 0,
          sentence_count: sentences.length,
        },
      });
      if (reason === "script_confirmed") {
        addToast?.("ok", "確認済み台本の音声付きプレビューを準備しました");
      }
      return nextPreview;
    } catch (error) {
      console.warn("Audio preview failed:", error);
      addToast?.("er", "音声プレビュー生成に失敗しました");
      setPreview((prev) => ({
        ...prev,
        status: "instant",
        source: "instant",
        message: reason === "edit_refresh"
          ? "変更文の音声更新に失敗しました"
          : "音声なしの簡易プレビューに切り替えました",
      }));
      return null;
    } finally {
      if (inFlightFingerprintRef.current === fingerprint) {
        inFlightFingerprintRef.current = "";
      }
    }
  };

  stateRef.current = state;
  reviewStageRef.current = reviewStage;
  previewStateRef.current = preview;

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    reviewStageRef.current = reviewStage;
  }, [reviewStage]);

  useEffect(() => {
    previewStateRef.current = preview;
  }, [preview]);

  useEffect(() => {
    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;

    const stopSync = () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
    const sync = () => {
      const current = previewRef.current;
      if (!current || audio.paused || audio.ended) return;
      const row = timingAtLocal(audio.currentTime, current.timings);
      dispatch({
        type: "SET_PREVIEW_TIME",
        v: localToGlobal(audio.currentTime, current.timings),
        sentenceId: row?.sentence_id ?? null,
        slideIdx: row?.slide_idx,
        totalDuration: timelineDuration(current.timings, stateRef.current.totDur),
      });
      rafRef.current = requestAnimationFrame(sync);
    };
    const onPlaying = () => {
      if (unlockingPlaybackRef.current) return;
      setPreview((prev) => ({ ...prev, status: "playing", source: "audio", message: prev.cacheHit ? "キャッシュ済み音声を再生中" : "音声プレビュー再生中" }));
      dispatch({ type: "SET", k: "playing", v: true });
      stopSync();
      rafRef.current = requestAnimationFrame(sync);
    };
    const onPause = () => {
      stopSync();
      if (unlockingPlaybackRef.current) return;
      if (!audio.ended) {
        setPreview((prev) => prev.source === "audio" ? { ...prev, status: "paused", message: "音声プレビュー一時停止中" } : prev);
        dispatch({ type: "SET", k: "playing", v: false });
      }
    };
    const onEnded = () => {
      stopSync();
      const current = previewRef.current;
      if (current?.timings?.length) {
        const last = current.timings[current.timings.length - 1];
        dispatch({
          type: "SET_PREVIEW_TIME",
          v: Number(last.end_sec ?? stateRef.current.curT),
          sentenceId: last.sentence_id ?? null,
          slideIdx: last.slide_idx,
          totalDuration: timelineDuration(current.timings, stateRef.current.totDur),
        });
      }
      setPreview((prev) => ({ ...prev, status: "ready", source: "audio", message: "音声プレビュー再生完了" }));
      dispatch({ type: "SET", k: "playing", v: false });
    };
    const onWaiting = () => setPreview((prev) => prev.source === "audio" ? { ...prev, status: "buffering", message: "バッファ中..." } : prev);
    const onError = () => {
      stopSync();
      setPreview((prev) => ({ ...prev, status: "error", source: "instant", message: "音声プレビュー再生に失敗しました" }));
      dispatch({ type: "SET", k: "playing", v: false });
      addToast?.("er", "音声プレビューを再生できませんでした");
    };

    audio.addEventListener("playing", onPlaying);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("waiting", onWaiting);
    audio.addEventListener("error", onError);
    return () => {
      stopSync();
      audio.pause();
      audio.removeEventListener("playing", onPlaying);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("waiting", onWaiting);
      audio.removeEventListener("error", onError);
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      if (finalVideoUrlRef.current) URL.revokeObjectURL(finalVideoUrlRef.current);
    };
  }, [addToast, dispatch]);

  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = Number(state.playSpeed ?? 1) || 1;
    }
  }, [state.playSpeed]);

  useEffect(() => {
    const audio = audioRef.current;
    const current = previewRef.current;
    if (!audio || audio.paused || !current?.timings?.length) return;
    if (!isWithinPreview(state.curT, current.timings)) {
      audio.pause();
      setPreview((prev) => prev.source === "audio"
        ? { ...prev, status: "ready", message: "別範囲に移動しました。再生で音声を準備します" }
        : prev);
    }
  }, [state.curT, state.curSl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!isAudioStale || !audio || audio.paused || unlockingPlaybackRef.current) return;
    audio.pause();
    setPreview((prev) => ({
      ...prev,
      status: "ready",
      message: "台本が変更されました。次の再生時に変更文の音声を更新します",
    }));
  }, [currentFingerprint, isAudioStale]);

  useEffect(() => {
    if (!(reviewStage === "assignment" || reviewStage === "editor")) return;
    if (!state.projectMeta?.id || !state.genRef?.run_id || !state.sents.length) return;
    const projectRunKey = `${state.projectMeta.id}:${state.genRef.run_id}`;
    if (attachedProjectRunRef.current === projectRunKey) return;
    attachedProjectRunRef.current = projectRunKey;
    prepareAudioPreview({ reason: "script_confirmed" });
  }, [reviewStage, state.projectMeta?.id, state.genRef?.run_id, state.sents.length]);

  const playAudioPreview = async ({ sentenceId = null, requestedTime = null } = {}) => {
    const audio = audioRef.current;
    if (!audio) return;
    if (!previewSentences.length) {
      dispatch({ type: "SET", k: "playing", v: true });
      setPreview((prev) => ({ ...prev, status: "instant", source: "instant", message: "音声なしの簡易プレビュー中" }));
      return;
    }

    let nextPreview = previewStateRef.current;
    if (isAudioStale || !nextPreview?.audioUrl) {
      if (nextPreview?.audioUrl && audio.paused) {
        unlockingPlaybackRef.current = true;
        audio.src = nextPreview.audioUrl;
        audio.muted = true;
        audio.loop = true;
        audio.play().catch(() => {});
      }
      nextPreview = await prepareAudioPreview({
        reason: nextPreview?.audioUrl && isAudioStale ? "edit_refresh" : "play",
      });
      if (unlockingPlaybackRef.current) {
        audio.pause();
        audio.loop = false;
        audio.muted = false;
        unlockingPlaybackRef.current = false;
      }
      if (!nextPreview?.audioUrl) {
        dispatch({ type: "SET", k: "playing", v: true });
        return;
      }
    }

    previewRef.current = nextPreview;
    audio.src = nextPreview.audioUrl;
    audio.playbackRate = Number(state.playSpeed ?? 1) || 1;
    const requestedRow = sentenceId
      ? nextPreview.timings.find((row) => String(row.sentence_id) === String(sentenceId))
      : null;
    const targetTime = Number(
      requestedRow?.start_sec
      ?? requestedTime
      ?? stateRef.current.curT
      ?? 0,
    ) || 0;
    if (requestedRow) {
      dispatch({
        type: "SET_PREVIEW_TIME",
        v: targetTime,
        sentenceId: requestedRow.sentence_id,
        slideIdx: requestedRow.slide_idx,
        totalDuration: timelineDuration(nextPreview.timings, stateRef.current.totDur),
      });
    }
    audio.currentTime = globalToLocal(targetTime, nextPreview.timings, audio.duration || 0);
    try {
      await audio.play();
    } catch (error) {
      console.warn("Audio play failed:", error);
      setPreview((prev) => ({ ...prev, status: "ready", source: "audio", message: "ブラウザが自動再生を止めました。もう一度再生してください" }));
      addToast?.("er", "音声再生を開始できませんでした。もう一度再生してください");
    }
  };

  const playSentence = async (sentenceId) => {
    const sentence = stateRef.current.sents.find((row) => String(row.id) === String(sentenceId));
    if (!sentence) return;
    dispatch({ type: "PLAY_SENTENCE", id: sentence.id });
    await playAudioPreview({
      sentenceId: sentence.id,
      requestedTime: Number(sentence.start_sec ?? 0) || 0,
    });
  };

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (state.playing) {
      if (audioActive && audio) audio.pause();
      dispatch({ type: "SET", k: "playing", v: false });
      return;
    }
    await playAudioPreview();
  };

  const seekTo = (time) => {
    const target = Number(time ?? 0) || 0;
    const audio = audioRef.current;
    const current = previewRef.current;
    const row = current?.timings?.length ? timingAtGlobal(target, current.timings) : null;
    if (row) {
      dispatch({
        type: "SET_PREVIEW_TIME",
        v: target,
        sentenceId: row.sentence_id ?? null,
        slideIdx: row.slide_idx,
        totalDuration: timelineDuration(current.timings, stateRef.current.totDur),
      });
    } else {
      dispatch({ type: "SEEK", v: target });
    }
    if (!audio || !current || current.source !== "audio") return;
    if (isWithinPreview(target, current.timings)) {
      audio.currentTime = globalToLocal(target, current.timings, audio.duration || 0);
      return;
    }
    audio.pause();
    setPreview((prev) => prev.source === "audio" ? { ...prev, status: "ready", message: "別範囲に移動しました。再生で音声を準備します" } : prev);
  };

  const jumpToSlide = (slideIdx) => {
    const current = previewRef.current;
    const row = current?.timings?.find((item) => Number(item.slide_idx) === Number(slideIdx));
    seekTo(row ? Number(row.start_sec ?? 0) : firstSlideTime(state, slideIdx));
  };

  const startFinalRenderPreview = async () => {
    if (state.appMode === "audio") {
      addToast?.("er", "音声のみモードでは本番動画プレビューを生成しません");
      return;
    }
    if (state.status === "proc") {
      addToast?.("er", "生成中は本番確認プレビューを開始できません。完了または停止してから実行してください");
      return;
    }
    if (!state.slides.length || !state.sents.length) {
      addToast?.("er", "本番確認プレビューにはスライドと台本が必要です");
      return;
    }
    if (!state.projectMeta?.id || !state.genRef?.run_id) {
      addToast?.("er", "本番確認プレビューには保存済みprojectと生成runが必要です");
      return;
    }
    setFinalRender({ status: "queued", message: "本番確認プレビューを開始しています...", progress: 0, jobId: null, videoUrl: "" });
    try {
      const saved = await options.ensureLatestDraftSaved?.();
      const latestState = stateRef.current;
      const draftVersion = Number(
        saved?.draft_version
        ?? saved?.data?.project_meta?.version_number
        ?? latestState.projectMeta?.version_number,
      );
      const res = await authFetch("/api/preview/final-render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createFinalRenderPayload(latestState, draftVersion)),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const submitted = await res.json();
      setFinalRender((prev) => ({ ...prev, status: submitted.status, message: submitted.message, progress: submitted.progress ?? 0, jobId: submitted.job_id }));

      let job = submitted;
      while (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 1800));
        const poll = await authFetch(`/api/jobs/${submitted.job_id}`, { method: "GET" });
        if (!poll.ok) throw new Error(`HTTP ${poll.status}`);
        job = await poll.json();
        setFinalRender((prev) => ({ ...prev, status: job.status, message: job.message, progress: job.progress ?? prev.progress, jobId: submitted.job_id }));
      }
      if (job.status !== "completed" || !job.result?.media_url) {
        throw new Error(job.error?.message || job.message || "本番確認プレビューに失敗しました");
      }
      const media = await authFetch(job.result.media_url, { method: "GET" });
      if (!media.ok) throw new Error(`HTTP ${media.status}`);
      const blob = await media.blob();
      if (finalVideoUrlRef.current) URL.revokeObjectURL(finalVideoUrlRef.current);
      finalVideoUrlRef.current = URL.createObjectURL(blob);
      setFinalRender({
        status: "completed",
        message: "本番確認プレビューが完了しました",
        progress: 100,
        jobId: submitted.job_id,
        videoUrl: finalVideoUrlRef.current,
      });
      addToast?.("ok", "本番確認プレビューが完了しました");
    } catch (error) {
      console.warn("Final render preview failed:", error);
      setFinalRender((prev) => ({ ...prev, status: "failed", message: error.message || "本番確認プレビューに失敗しました" }));
      addToast?.("er", error.message || "本番確認プレビューに失敗しました");
    }
  };

  const cancelFinalRenderPreview = async () => {
    if (!finalRender.jobId) return;
    try {
      await authFetch(`/api/jobs/${finalRender.jobId}/cancel`, { method: "POST" });
      setFinalRender((prev) => ({ ...prev, status: "cancelled", message: "本番確認プレビュー停止をリクエストしました" }));
    } catch (error) {
      addToast?.("er", error.message || "本番確認プレビューを停止できませんでした");
    }
  };

  const openFinalRenderPreview = () => {
    if (finalRender.videoUrl) window.open(finalRender.videoUrl, "_blank", "noopener,noreferrer");
  };

  return {
    audioActive,
    isAudioStale,
    preview,
    finalRender,
    togglePlayback,
    playSentence,
    seekTo,
    jumpToSlide,
    startFinalRenderPreview,
    cancelFinalRenderPreview,
    openFinalRenderPreview,
    sentenceTimings: preview.timings ?? [],
    timelineDuration: timelineDuration(preview.timings, state.totDur),
  };
}
