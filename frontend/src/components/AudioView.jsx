import { useEffect, useRef } from "react";
import { fmt } from "../utils/helpers.js";

/**
 * 音声のみモード用の中央ビュー
 * - 現在再生中の文を大きく表示
 * - 前後の文をフェードで表示
 * - 波形風のビジュアルアニメーション
 */
export default function AudioView({ state, onPlaySentence, sentenceTimings = [] }) {
  const { sents, curT, playing } = state;
  const scrollRef = useRef(null);
  const timingBySentenceId = new Map(
    sentenceTimings.map((timing) => [String(timing.sentence_id), timing]),
  );
  const rows = sents.map((sentence) => {
    const timing = timingBySentenceId.get(String(sentence.id));
    return {
      sentence,
      startSec: Number(timing?.start_sec ?? sentence.start_sec ?? 0) || 0,
      endSec: Number(timing?.end_sec ?? sentence.end_sec ?? 0) || 0,
    };
  });

  const activeSentenceId = state.previewActiveSentenceId == null
    ? null
    : String(state.previewActiveSentenceId);
  const activeIdIdx = activeSentenceId == null
    ? -1
    : rows.findIndex(({ sentence }) => String(sentence.id) === activeSentenceId);
  const actIdx = activeIdIdx >= 0
    ? activeIdIdx
    : rows.findIndex(({ startSec, endSec }) => startSec <= curT && curT < endSec);
  const actSent = actIdx >= 0 ? sents[actIdx] : null;

  // 再生中の文へスクロール
  useEffect(() => {
    if (actIdx < 0 || !scrollRef.current) return;
    const el = scrollRef.current.children[actIdx];
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [actIdx]);

  if (!sents.length) {
    return (
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--tm)", fontSize: 13 }}>
        {state.generated ? "台本がありません" : "まだ台本がありません。右パネルから文を追加してください"}
      </div>
    );
  }

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

      {/* 波形アニメーション */}
      <div style={{ height: 48, display: "flex", alignItems: "center", justifyContent: "center", gap: 3, padding: "0 20px", flexShrink: 0 }}>
        {Array.from({ length: 32 }).map((_, i) => {
          const phase = (i / 32) * Math.PI * 2;
          const baseH = 4 + Math.sin(phase) * 3;
          const animH = playing
            ? `${baseH + Math.sin(phase + curT * 6) * 10}px`
            : `${baseH}px`;
          return (
            <div key={i} style={{
              width: 3, borderRadius: 2,
              height: animH,
              background: actSent
                ? `rgba(91,141,239,${0.3 + Math.sin(phase + i * 0.3) * 0.3})`
                : "var(--bd2)",
              transition: playing ? "none" : "height .3s ease",
            }} />
          );
        })}
      </div>

      {/* 台本スクロールビュー */}
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "0 24px 40px" }}>
        {rows.map(({ sentence: s, startSec, endSec }, i) => {
          const isActive = i === actIdx;
          const isPast   = endSec <= curT;
          const isFuture = startSec > curT;
          const progress = isActive && (endSec - startSec) > 0
            ? ((curT - startSec) / (endSec - startSec)) * 100
            : 0;

          return (
            <div
              key={s.id}
              role="button"
              tabIndex={0}
              title="クリックしてこの文から再生"
              onClick={() => onPlaySentence?.(s.id)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                onPlaySentence?.(s.id);
              }}
              style={{
              padding: "12px 0",
              borderBottom: "1px solid var(--bd)",
              opacity: isFuture ? 0.35 : isPast ? 0.55 : 1,
              transition: "opacity .3s",
              cursor: "pointer",
              outline: "none",
            }}>
              {/* 時刻 */}
              <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: isActive ? "var(--ac)" : "var(--tm)", marginBottom: 5, display: "flex", alignItems: "center", gap: 6 }}>
                <span>{fmt(startSec)}–{fmt(endSec)}</span>
                {isActive && (
                  <div style={{ flex: 1, height: 2, background: "var(--s3)", borderRadius: 1, overflow: "hidden" }}>
                    <div style={{ height: "100%", background: "var(--ac)", width: progress + "%", transition: "width .1s linear" }} />
                  </div>
                )}
              </div>
              {/* テキスト */}
              <div style={{
                fontSize: isActive ? 15 : 13,
                lineHeight: 1.7,
                color: isActive ? "var(--tp)" : "var(--ts)",
                fontWeight: isActive ? 500 : 400,
                transition: "font-size .2s, color .2s",
              }}>
                {s.text}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
