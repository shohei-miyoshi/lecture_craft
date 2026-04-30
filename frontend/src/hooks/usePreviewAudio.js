import { useEffect, useRef, useState } from "react";
import { API_URL, DETAIL_VALS, DIFF_VALS } from "../utils/constants.js";

function sortSentencesForPreview(sentences = []) {
  return [...sentences].sort((a, b) => {
    const aSlide = Number(a?.slide_idx ?? 0) || 0;
    const bSlide = Number(b?.slide_idx ?? 0) || 0;
    if (aSlide !== bSlide) return aSlide - bSlide;
    const aStart = Number(a?.start_sec ?? 0) || 0;
    const bStart = Number(b?.start_sec ?? 0) || 0;
    if (aStart !== bStart) return aStart - bStart;
    return String(a?.id ?? "").localeCompare(String(b?.id ?? ""));
  });
}

function buildPreviewAudioSignature(sentences = []) {
  return JSON.stringify(
    sortSentencesForPreview(sentences).map((sentence) => [
      String(sentence?.id ?? ""),
      String(sentence?.text ?? "").trim(),
    ]),
  );
}

function mapTimelineToAudioTime(curT, totDur, audioDur) {
  const duration = Number(audioDur ?? 0);
  if (!(duration > 0)) return 0;

  const timeline = Number(totDur ?? 0);
  if (!(timeline > 0)) {
    return Math.max(0, Math.min(duration, Number(curT ?? 0) || 0));
  }

  const ratio = Math.max(0, Math.min(1, (Number(curT ?? 0) || 0) / timeline));
  return duration * ratio;
}

function mapAudioTimeToTimelineTime(audioTime, audioDur, totDur) {
  const duration = Number(audioDur ?? 0);
  if (!(duration > 0)) return 0;

  const timeline = Number(totDur ?? 0);
  if (!(timeline > 0)) {
    return Math.max(0, Number(audioTime ?? 0) || 0);
  }

  const ratio = Math.max(0, Math.min(1, (Number(audioTime ?? 0) || 0) / duration));
  return timeline * ratio;
}

function clampPlaybackRate(rate) {
  return Math.max(0.25, Math.min(4, Number(rate) || 1));
}

function buildRequestedExportType(state) {
  if (state.appMode === "audio") return "audio";
  if (state.appMode === "video") return "video";
  return "video_highlight";
}

function buildGeneratedPreviewAudioUrl(genRef) {
  const outputRootName = String(genRef?.output_root_name ?? "").trim();
  const materialName = String(genRef?.material_name ?? "").trim();
  if (!outputRootName || !materialName) return null;
  const params = new URLSearchParams({
    output_root_name: outputRootName,
    material_name: materialName,
  });
  return `${API_URL}/api/preview-audio/source?${params.toString()}`;
}

function buildPreviewAudioRequest(state) {
  return {
    type: buildRequestedExportType(state),
    mode: state.appMode,
    slides: state.slides,
    sentences: state.sents,
    highlights: [],
    operation_logs: state.opLogs,
    session_id: state.sessionId,
    source_cache_key: state.genRef?.cache_key ?? null,
    source_material_name: state.genRef?.material_name ?? null,
    source_output_root_name: state.genRef?.output_root_name ?? null,
    generation_ref: state.genRef ?? {},
    settings: {
      detail: DETAIL_VALS[state.detail],
      difficulty: DIFF_VALS[state.level],
      preview_mode: state.prevMode,
      play_speed: state.playSpeed,
    },
  };
}

export function usePreviewAudio(state, dispatch, addToast) {
  const audioRef = useRef(null);
  const objectUrlRef = useRef(null);
  const abortRef = useRef(null);
  const pendingRef = useRef(null);
  const latestSignatureRef = useRef(buildPreviewAudioSignature(state.sents));
  const prevSignatureRef = useRef(latestSignatureRef.current);
  const syncStateRef = useRef({
    totDur: state.totDur,
    sents: state.sents,
  });
  const latestStateRef = useRef(state);
  const syncedTimelineRef = useRef(state.curT);
  const lastAutoSlideRef = useRef(state.curSl);
  const pendingTimelineSeekRef = useRef(state.curT);
  const scrubbingRef = useRef(false);
  const [previewAudio, setPreviewAudio] = useState({
    status: "idle",
    signature: null,
    duration: 0,
    error: null,
  });

  const signature = buildPreviewAudioSignature(state.sents);
  latestSignatureRef.current = signature;
  const baselineSentences = Array.isArray(state.baseline?.sentences) ? state.baseline.sentences : [];
  const baselineSignature = baselineSentences.length ? buildPreviewAudioSignature(baselineSentences) : null;

  const requiresAudio = state.generated && state.sents.length > 0;
  const isReady = requiresAudio
    && previewAudio.status === "ready"
    && previewAudio.signature === signature
    && previewAudio.duration > 0;
  const isStale = requiresAudio
    && (previewAudio.status === "stale"
      || (Boolean(previewAudio.signature) && previewAudio.signature !== signature));
  const generatedPreviewAudioUrl = buildGeneratedPreviewAudioUrl(state.genRef);
  const canUseGeneratedPreviewAudio = Boolean(
    generatedPreviewAudioUrl
    && state.genRef?.preview_audio_source_ready
    && state.genRef?.preview_audio_signature
    && state.genRef.preview_audio_signature === signature,
  );

  const syncTimelineFromSentences = (sentences, totalDuration) => {
    if (!Array.isArray(sentences) || !sentences.length) return;
    dispatch({
      type: "SYNC_SENT_TIMINGS",
      sentences,
      total_duration: totalDuration,
    });
  };

  useEffect(() => {
    syncStateRef.current = {
      totDur: state.totDur,
      sents: state.sents,
    };
  }, [state.sents, state.totDur]);

  useEffect(() => {
    latestStateRef.current = state;
  }, [state]);

  useEffect(() => {
    syncedTimelineRef.current = state.curT;
    pendingTimelineSeekRef.current = state.curT;
  }, [state.curT]);

  useEffect(() => {
    lastAutoSlideRef.current = state.curSl;
  }, [state.curSl]);

  const applyAudioSeekForTimeline = (timelineTime, options = {}) => {
    const { force = false, totalDuration = null, audioDuration = null } = options;
    const audio = audioRef.current;
    if (!audio) return;
    pendingTimelineSeekRef.current = Number(timelineTime ?? 0) || 0;
    const resolvedAudioDuration = Number(audioDuration ?? audio.duration ?? previewAudio.duration ?? 0);
    if (!(resolvedAudioDuration > 0)) return;
    const resolvedTotalDuration = Number(totalDuration ?? syncStateRef.current.totDur ?? latestStateRef.current.totDur ?? 0);
    const targetTime = mapTimelineToAudioTime(pendingTimelineSeekRef.current, resolvedTotalDuration, resolvedAudioDuration);
    if (force || Math.abs((audio.currentTime || 0) - targetTime) > 0.04) {
      try {
        audio.currentTime = targetTime;
      } catch {
        // currentTime を変更できない状態では次の loadedmetadata / timeupdate に任せる
      }
    }
  };

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      pendingRef.current = null;
      const audio = audioRef.current;
      if (audio) {
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      }
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (requiresAudio) return;

    abortRef.current?.abort();
    abortRef.current = null;
    pendingRef.current = null;

    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }

    setPreviewAudio({
      status: "idle",
      signature: null,
      duration: 0,
      error: null,
    });
  }, [requiresAudio]);

  useEffect(() => {
    if (prevSignatureRef.current === signature) return;
    prevSignatureRef.current = signature;

    abortRef.current?.abort();
    abortRef.current = null;
    pendingRef.current = null;

    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }

    setPreviewAudio((current) => ({
      status: current.signature ? "stale" : "idle",
      signature: current.signature,
      duration: 0,
      error: null,
    }));

    if (state.playing) {
      dispatch({ type: "SET", k: "playing", v: false });
    }
  }, [dispatch, signature, state.playing]);

  const ensurePreviewAudio = async ({ silent = false, forceExport = false } = {}) => {
    if (!requiresAudio) return { ok: false, reason: "empty" };

    if (isReady) {
      const audio = audioRef.current;
      if (audio) {
        applyAudioSeekForTimeline(latestStateRef.current.curT, {
          totalDuration: latestStateRef.current.totDur,
          audioDuration: audio.duration || previewAudio.duration,
        });
      }
      return { ok: true, reused: true };
    }

    const audio = audioRef.current;
    if (!audio) {
      return { ok: false, reason: "missing_audio" };
    }

    if (pendingRef.current) {
      return pendingRef.current;
    }

    const requestSignature = signature;
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }

    if (!forceExport && canUseGeneratedPreviewAudio && generatedPreviewAudioUrl) {
      if (!silent) {
        addToast("in", "🔊 生成済み音声を読み込んでいます...");
      }
      setPreviewAudio({
        status: "loading",
        signature: null,
        duration: 0,
        error: null,
      });

      const requestPromise = new Promise((resolve) => {
        const onLoaded = () => {
          cleanup();
          const duration = Number(audio.duration) || 0;
          let syncedTotalDuration = duration;
          if (baselineSignature && baselineSignature === requestSignature) {
            syncedTotalDuration = baselineSentences[baselineSentences.length - 1]?.end_sec ?? duration;
            syncTimelineFromSentences(
              baselineSentences,
              syncedTotalDuration,
            );
          }
          applyAudioSeekForTimeline(pendingTimelineSeekRef.current, {
            force: true,
            totalDuration: syncedTotalDuration,
            audioDuration: duration,
          });
          setPreviewAudio({
            status: "ready",
            signature: requestSignature,
            duration,
            error: null,
          });
          dispatch({
            type: "APP_LOG",
            message: "生成済みプレビュー音声を接続しました",
            meta: { type: "preview_audio_attached", duration },
          });
          resolve({ ok: true, reused: false, duration });
        };
        const onError = () => {
          cleanup();
          setPreviewAudio({
            status: "idle",
            signature: null,
            duration: 0,
            error: null,
          });
          audio.removeAttribute("src");
          audio.load();
          resolve({ ok: false, generatedSourceFailed: true });
        };
        const cleanup = () => {
          audio.removeEventListener("loadedmetadata", onLoaded);
          audio.removeEventListener("error", onError);
        };

        audio.addEventListener("loadedmetadata", onLoaded);
        audio.addEventListener("error", onError);
        audio.src = generatedPreviewAudioUrl;
        audio.load();
      }).finally(() => {
        if (pendingRef.current === requestPromise) {
          pendingRef.current = null;
        }
      });

      pendingRef.current = requestPromise;
      return requestPromise;
    }

    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;

    if (!silent) {
      addToast("in", "🔊 プレビュー音声を準備しています...");
    }
    setPreviewAudio({
      status: "loading",
      signature: null,
      duration: 0,
      error: null,
    });

    const requestPromise = (async () => {
      const response = await fetch(`${API_URL}/api/preview-audio/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPreviewAudioRequest(state)),
        signal: controller.signal,
      });

      if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
          const payload = await response.json();
          detail = payload?.error?.message || detail;
        } catch {
          // ignore JSON parse failure and keep the HTTP status detail.
        }
        throw new Error(detail);
      }

      const payload = await response.json();
      if (requestSignature !== latestSignatureRef.current) {
        return { ok: false, stale: true };
      }

      const audioUrl = buildGeneratedPreviewAudioUrl(payload);
      if (!audioUrl) {
        throw new Error("プレビュー音声のURL取得に失敗しました");
      }
      const duration = await new Promise((resolve, reject) => {
        const onLoaded = () => {
          cleanup();
          resolve(Number(audio.duration) || 0);
        };
        const onError = () => {
          cleanup();
          reject(new Error("プレビュー音声の読み込みに失敗しました"));
        };
        const cleanup = () => {
          audio.removeEventListener("loadedmetadata", onLoaded);
          audio.removeEventListener("error", onError);
        };

        audio.addEventListener("loadedmetadata", onLoaded);
        audio.addEventListener("error", onError);
        audio.src = audioUrl;
        audio.load();
      });

      if (requestSignature !== latestSignatureRef.current) {
        return { ok: false, stale: true };
      }
      const nextTotalDuration = Number(payload?.total_duration ?? duration) || duration;
      syncTimelineFromSentences(payload?.sentences ?? [], nextTotalDuration);

      applyAudioSeekForTimeline(pendingTimelineSeekRef.current, {
        force: true,
        totalDuration: nextTotalDuration,
        audioDuration: duration,
      });

      setPreviewAudio({
        status: "ready",
        signature: requestSignature,
        duration,
        error: null,
      });
      dispatch({
        type: "APP_LOG",
        message: "プレビュー音声を更新しました",
        meta: { type: "preview_audio_ready", duration, export_type: buildRequestedExportType(state) },
      });
      return { ok: true, reused: false, duration };
    })()
      .catch((error) => {
        if (controller.signal.aborted) {
          return { ok: false, aborted: true };
        }

        const message = error instanceof Error
          ? error.message
          : "プレビュー音声の生成に失敗しました";

        setPreviewAudio({
          status: "error",
          signature: null,
          duration: 0,
          error: message,
        });
        dispatch({
          type: "APP_LOG",
          message: `プレビュー音声の更新に失敗しました（reason=${message}）`,
          meta: { type: "preview_audio_error", reason: message },
        });
        addToast("er", message);
        return { ok: false, error: message };
      })
      .finally(() => {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        if (pendingRef.current === requestPromise) {
          pendingRef.current = null;
        }
      });

    pendingRef.current = requestPromise;
    return requestPromise;
  };

  useEffect(() => {
    if (!requiresAudio || !state.playing || isReady) return;

    ensurePreviewAudio({ silent: previewAudio.status === "loading" }).then(async (result) => {
      if (result?.generatedSourceFailed) {
        result = await ensurePreviewAudio({ silent: true, forceExport: true });
      }
      if (result?.ok || result?.aborted || result?.stale) return;
      dispatch({ type: "SET", k: "playing", v: false });
    });
  }, [dispatch, isReady, previewAudio.status, requiresAudio, signature, state.playing]);

  useEffect(() => {
    if (!requiresAudio || !canUseGeneratedPreviewAudio || previewAudio.status !== "idle") return;
    ensurePreviewAudio({ silent: true }).catch(() => {});
  }, [canUseGeneratedPreviewAudio, previewAudio.status, requiresAudio, signature]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !isReady) return;

    const audioDur = Number(audio.duration || previewAudio.duration || 0);
    audio.playbackRate = clampPlaybackRate(Number(state.playSpeed || 1));

    if (!state.playing) {
      audio.pause();
      return;
    }

    applyAudioSeekForTimeline(latestStateRef.current.curT, {
      totalDuration: latestStateRef.current.totDur,
      audioDuration: audioDur,
    });

    const playPromise = audio.play();
    if (playPromise?.catch) {
      playPromise.catch(() => {
        dispatch({ type: "SET", k: "playing", v: false });
      });
    }
  }, [dispatch, isReady, previewAudio.duration, state.playSpeed, state.playing, state.totDur]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !isReady) return;

    applyAudioSeekForTimeline(state.curT, {
      totalDuration: state.totDur,
      audioDuration: audio.duration || previewAudio.duration,
    });
  }, [isReady, previewAudio.duration, state.curT, state.seekSignal, state.totDur]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onEnded = () => {
      dispatch({ type: "SET", k: "curT", v: state.totDur });
      dispatch({ type: "SET", k: "playing", v: false });
    };

    audio.addEventListener("ended", onEnded);
    return () => audio.removeEventListener("ended", onEnded);
  }, [dispatch, state.totDur]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !isReady || !state.playing) return undefined;

    let rafId = 0;
    const tick = () => {
      if (scrubbingRef.current) {
        rafId = requestAnimationFrame(tick);
        return;
      }
      const { totDur, sents } = syncStateRef.current;
      const audioDur = Number(audio.duration || previewAudio.duration || 0);
      const nextTimelineTime = mapAudioTimeToTimelineTime(audio.currentTime || 0, audioDur, totDur);

      if (Math.abs((syncedTimelineRef.current || 0) - nextTimelineTime) > 1 / 120) {
        syncedTimelineRef.current = nextTimelineTime;
        dispatch({ type: "SET", k: "curT", v: nextTimelineTime });
      }

      const activeSent = sents.find((sentence) => sentence.start_sec <= nextTimelineTime && nextTimelineTime < sentence.end_sec);
      if (activeSent && activeSent.slide_idx !== lastAutoSlideRef.current) {
        lastAutoSlideRef.current = activeSent.slide_idx;
        dispatch({ type: "SET_SL", v: activeSent.slide_idx });
      }

      if (!audio.paused && !audio.ended) {
        rafId = requestAnimationFrame(tick);
      }
    };

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [dispatch, isReady, previewAudio.duration, state.playing]);

  const togglePlayback = async () => {
    if (state.playing) {
      dispatch({ type: "SET", k: "playing", v: false });
      return;
    }

    let result = await ensurePreviewAudio();
    if (result?.generatedSourceFailed) {
      result = await ensurePreviewAudio({ silent: true, forceExport: true });
    }
    if (!result?.ok) return;

    const audio = audioRef.current;
    if (audio) {
      const audioDur = Number(audio.duration || previewAudio.duration || result.duration || 0);
      audio.playbackRate = clampPlaybackRate(Number(latestStateRef.current.playSpeed || 1));
      applyAudioSeekForTimeline(latestStateRef.current.curT, {
        force: true,
        totalDuration: latestStateRef.current.totDur,
        audioDuration: audioDur,
      });
      const playPromise = audio.play();
      if (playPromise?.catch) {
        playPromise.catch(() => {});
      }
    }

    dispatch({ type: "SET", k: "playing", v: true });
  };

  const beginPreviewScrub = () => {
    scrubbingRef.current = true;
  };

  const seekPreview = (nextTimelineTime) => {
    pendingTimelineSeekRef.current = Number(nextTimelineTime ?? 0) || 0;
    syncedTimelineRef.current = pendingTimelineSeekRef.current;
    if (isReady) {
      applyAudioSeekForTimeline(pendingTimelineSeekRef.current, {
        force: true,
        totalDuration: latestStateRef.current.totDur,
      });
    }
  };

  const endPreviewScrub = () => {
    scrubbingRef.current = false;
    if (!isReady) return;
    applyAudioSeekForTimeline(pendingTimelineSeekRef.current, {
      force: true,
      totalDuration: latestStateRef.current.totDur,
    });
    const audio = audioRef.current;
    if (audio && latestStateRef.current.playing && audio.paused) {
      const playPromise = audio.play();
      if (playPromise?.catch) {
        playPromise.catch(() => {});
      }
    }
  };

  return {
    audioRef,
    ensurePreviewAudio,
    togglePlayback,
    previewAudio,
    previewAudioReady: isReady,
    previewAudioStale: isStale,
    beginPreviewScrub,
    seekPreview,
    endPreviewScrub,
  };
}
