import { useRef } from "react";
import { fmt } from "../utils/helpers.js";

const SPEEDS = [0.5, 1.0, 1.5, 2.0];

/**
 * 再生コントロールバー
 *
 * シーク操作は dispatch({ type: "SEEK", v: t }) を使う。
 * SEEK アクションは:
 *   - curT を更新
 *   - 対応スライドへ自動ジャンプ
 *   - seekSignal をインクリメント → usePlayback が再起動して再生中シークに対応
 */
export default function Playbar({
  state,
  dispatch,
  hideSlideNav = false,
  highlightTicksEnabled = true,
  previewPlayback = null,
  finalRenderEnabled = true,
  playbackDisabled = false,
}) {
  const { curT, totDur, playing, playSpeed, slides, curSl, hls, sents, appMode } = state;
  const timingBySentenceId = new Map((previewPlayback?.sentenceTimings ?? []).map((row) => [String(row.sentence_id), row]));
  const timelineTotDur = Math.max(0, Number(previewPlayback?.timelineDuration ?? totDur) || 0);
  const pct    = timelineTotDur > 0 ? Math.min(100, (curT / timelineTotDur) * 100) : 0;
  const remain = Math.max(0, timelineTotDur - curT);
  const sc     = slides.length;
  const barRef = useRef(null);
  const sentenceStart = (sentence) => Number(timingBySentenceId.get(String(sentence.id))?.start_sec ?? sentence.start_sec ?? 0);
  const sentenceEnd = (sentence) => Number(timingBySentenceId.get(String(sentence.id))?.end_sec ?? sentence.end_sec ?? sentenceStart(sentence));

  // HL位置のティックマーク（HLありモードのみ）
  const ticks = appMode === "hl" && highlightTicksEnabled
    ? hls.map((h) => {
        const sid = h.sentence_ids?.[0];
        const s = sents.find((row) => row.id === sid);
        return s && timelineTotDur ? (sentenceStart(s) / timelineTotDur) * 100 : null;
      }).filter((v) => v !== null)
    : [];

  // 文セグメント
  const sentSegs = sents.map((s) => ({
    left:  timelineTotDur > 0 ? (sentenceStart(s) / timelineTotDur) * 100 : 0,
    width: timelineTotDur > 0 ? Math.max(0.3, (sentenceEnd(s) - sentenceStart(s)) / timelineTotDur * 100) : 0,
  }));

  const seekTo = (clientX) => {
    if (!barRef.current || !timelineTotDur) return;
    const r = barRef.current.getBoundingClientRect();
    if (!r.width) return;
    const t = Math.max(0, Math.min(timelineTotDur, ((clientX - r.left) / r.width) * timelineTotDur));
    if (previewPlayback?.seekTo) {
      previewPlayback.seekTo(t);
    } else {
      dispatch({ type: "SEEK", v: t });
    }
  };

  const onMouseDown = (e) => {
    seekTo(e.clientX);
    const onMove = (ev) => seekTo(ev.clientX);
    const onUp   = ()   => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
  };

  const nextSpeed = () => {
    const idx = SPEEDS.indexOf(playSpeed);
    dispatch({ type: "SET", k: "playSpeed", v: SPEEDS[(idx + 1) % SPEEDS.length] });
  };
  const jumpSlide = (slideIdx) => {
    if (previewPlayback?.jumpToSlide) {
      previewPlayback.jumpToSlide(slideIdx);
      return;
    }
    dispatch({ type: "SEEK_SLIDE", v: slideIdx });
  };
  const togglePlay = () => {
    if (playbackDisabled) return;
    if (previewPlayback?.togglePlayback) {
      previewPlayback.togglePlayback();
      return;
    }
    dispatch({ type: "SET", k: "playing", v: !playing });
  };
  const previewBusy = previewPlayback?.preview?.status === "preparing";
  const finalBusy = ["queued", "running"].includes(previewPlayback?.finalRender?.status);
  const canFinalRender = Boolean(!playbackDisabled && finalRenderEnabled && slides.length && sents.length);
  const showFinalRenderControls = Boolean(canFinalRender || finalBusy || previewPlayback?.finalRender?.videoUrl);
  const audioBadge = (() => {
    if (!previewPlayback) return { label: "", border: "transparent", background: "transparent", color: "var(--tm)" };
    if (previewBusy) {
      return {
        label: "音声準備中",
        border: "rgba(110,193,255,.34)",
        background: "rgba(110,193,255,.10)",
        color: "var(--ac)",
      };
    }
    if (!previewPlayback.preview?.audioUrl) {
      return {
        label: "音声未生成",
        border: "rgba(232,169,75,.36)",
        background: "var(--amd)",
        color: "var(--am)",
      };
    }
    if (previewPlayback.isAudioStale) {
      return {
        label: "音声プレビュー未更新",
        border: "rgba(232,169,75,.36)",
        background: "var(--amd)",
        color: "var(--am)",
      };
    }
    return {
      label: "音声プレビュー最新",
      border: "rgba(76,175,130,.28)",
      background: "rgba(76,175,130,.10)",
      color: "var(--gr)",
    };
  })();

  return (
    <div style={{ background: "var(--sur)", borderTop: "1px solid var(--bd)", flexShrink: 0 }}>

      {previewPlayback && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "7px 12px 0", fontSize: 10, color: "var(--tm)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <span style={{
              padding: "3px 8px",
              borderRadius: 999,
              border: `1px solid ${audioBadge.border}`,
              background: audioBadge.background,
              color: audioBadge.color,
              whiteSpace: "nowrap",
            }}>
              {audioBadge.label}
            </span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {previewPlayback.preview?.message || "プレビュー待機中"}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
            {showFinalRenderControls && finalBusy ? (
              <button
                onClick={previewPlayback.cancelFinalRenderPreview}
                style={{ padding: "4px 9px", borderRadius: 999, border: "1px solid rgba(224,91,91,.35)", background: "rgba(224,91,91,.12)", color: "var(--rd)", fontSize: 10 }}
              >
                本番確認停止
              </button>
            ) : showFinalRenderControls ? (
              <button
                onClick={previewPlayback.startFinalRenderPreview}
                disabled={!canFinalRender}
                style={{ padding: "4px 9px", borderRadius: 999, border: "1px solid rgba(110,193,255,.28)", background: "rgba(110,193,255,.10)", color: "var(--tp)", fontSize: 10, opacity: canFinalRender ? 1 : 0.55, cursor: canFinalRender ? "pointer" : "not-allowed" }}
              >
                本番確認プレビュー
              </button>
            ) : null}
            {finalBusy && (
              <span style={{ fontFamily: "var(--fm)", color: "var(--ac)" }}>
                {Math.round(previewPlayback.finalRender?.progress ?? 0)}%
              </span>
            )}
          </div>
        </div>
      )}

      {/* スライドナビ（音声モード以外） */}
      {!hideSlideNav && sc > 0 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, padding: "6px 12px 0" }}>
          <button onClick={() => jumpSlide(Math.max(0, curSl - 1))}
            style={{ width: 24, height: 24, border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontSize: 10, display: "grid", placeItems: "center" }}>◀</button>
          <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--ts)", minWidth: 46, textAlign: "center" }}>
            {sc ? `${curSl + 1} / ${sc}` : "— / —"}
          </span>
          <button onClick={() => jumpSlide(Math.min(sc - 1, curSl + 1))}
            style={{ width: 24, height: 24, border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontSize: 10, display: "grid", placeItems: "center" }}>▶</button>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 12px" }}>

        {/* 再生/停止 */}
        <button onClick={togglePlay} disabled={previewBusy || playbackDisabled}
          style={{ width: 32, height: 32, background: previewBusy || playbackDisabled ? "var(--s4)" : "var(--ac)", border: "none", borderRadius: "50%", color: "#fff", fontSize: 12, display: "grid", placeItems: "center", flexShrink: 0, opacity: previewBusy || playbackDisabled ? 0.7 : 1, cursor: previewBusy || playbackDisabled ? "not-allowed" : "pointer" }}>
          {previewBusy ? "…" : playing ? "⏸" : "▶"}
        </button>

        {/* タイムライン */}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--fm)", fontSize: 9, color: "var(--ts)", marginBottom: 4 }}>
            <span>{fmt(curT)}</span>
            <span style={{ color: "var(--tm)" }}>−{fmt(remain)}</span>
            <span>{fmt(timelineTotDur)}</span>
          </div>

          <div ref={barRef} onMouseDown={onMouseDown}
            style={{ height: 8, background: "var(--s2)", borderRadius: 4, position: "relative", cursor: "pointer", userSelect: "none" }}>

            {/* 文セグメント背景 */}
            {sentSegs.map((seg, i) => (
              <div key={i} style={{
                position: "absolute", top: 1, bottom: 1,
                left: seg.left + "%", width: seg.width + "%",
                background: "rgba(255,255,255,.04)",
                borderRight: "1px solid rgba(255,255,255,.07)",
                pointerEvents: "none",
              }} />
            ))}

            {/* 進捗 */}
            <div style={{ height: "100%", background: "var(--ac)", borderRadius: 4, width: pct + "%", position: "relative" }}>
              <div style={{
                position: "absolute", right: -7, top: "50%", transform: "translateY(-50%)",
                width: 14, height: 14, background: "var(--ac)", border: "2px solid var(--bg)",
                borderRadius: "50%", boxShadow: "0 0 0 2px rgba(91,141,239,.3)",
              }} />
            </div>

            {/* HLティック（HLありモードのみ） */}
            {ticks.map((p, i) => (
              <div key={i} style={{
                position: "absolute", top: -2, bottom: -2, left: p + "%",
                width: 2, background: "#e8a94b", opacity: 0.8, borderRadius: 1, pointerEvents: "none",
              }} />
            ))}
          </div>
        </div>

        {/* 再生速度 */}
        <button onClick={nextSpeed} title="再生速度"
          style={{ padding: "3px 7px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--ts)", fontFamily: "var(--fm)", fontSize: 10, flexShrink: 0, minWidth: 36 }}>
          {playSpeed}x
        </button>
      </div>
    </div>
  );
}
