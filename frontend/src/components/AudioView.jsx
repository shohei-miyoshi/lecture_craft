import { useEffect, useRef } from "react";
import { fmt } from "../utils/helpers.js";

/**
 * 音声のみモード用の中央ビュー
 * - 現在再生中の文を大きく表示
 * - 前後の文をフェードで表示
 * - 波形風のビジュアルアニメーション
 */
export default function AudioView({ state }) {
  const { sents, curT, playing } = state;
  const scrollRef = useRef(null);

  const actIdx = sents.findIndex(
    (s) => s.start_sec <= curT && curT < s.end_sec
  );
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
        生成後に表示されます
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
        {sents.map((s, i) => {
          const isActive = i === actIdx;
          const isPast   = s.end_sec <= curT;
          const isFuture = s.start_sec > curT;
          const progress = isActive && (s.end_sec - s.start_sec) > 0
            ? ((curT - s.start_sec) / (s.end_sec - s.start_sec)) * 100
            : 0;

          return (
            <div key={s.id} style={{
              padding: "12px 0",
              borderBottom: "1px solid var(--bd)",
              opacity: isFuture ? 0.35 : isPast ? 0.55 : 1,
              transition: "opacity .3s",
            }}>
              {/* 時刻 */}
              <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: isActive ? "var(--ac)" : "var(--tm)", marginBottom: 5, display: "flex", alignItems: "center", gap: 6 }}>
                <span>{fmt(s.start_sec)}–{fmt(s.end_sec)}</span>
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
