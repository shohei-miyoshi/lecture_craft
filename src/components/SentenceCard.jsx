import { useState, useEffect, useRef } from "react";
import HlSummaryBar from "./HlSummaryBar.jsx";
import HlEditor     from "./HlEditor.jsx";
import AiPanel      from "./AiPanel.jsx";
import { fmt } from "../utils/helpers.js";

/**
 * 台本1文カード
 * - テキスト直接編集（contentEditable）
 * - ✨AI修正 / 🔦HL設定 ボタン（常時薄く、ホバー・選択で濃く）
 * - 🗑 削除ボタン（右上）
 * - HLサマリーバー（テキスト下、動画モード時のみ）
 * - タイミング編集（音声モード時のみ）
 * - AIパネル / HLエディタ（選択時に展開）
 */
export default function SentenceCard({
  sent, idx, hl, isSel, isPlay, drawMode, drawSentId,
  dispatch, addToast,
  showHl = true,   // false のとき HL関連UIを非表示（音声モード）
}) {
  const [hlOpen, setHlOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [timingOpen, setTimingOpen] = useState(false);
  const [txt, setTxt] = useState(sent.text);
  const cardRef = useRef(null);

  useEffect(() => { if (!isSel) { setHlOpen(false); setAiOpen(false); setTimingOpen(false); } }, [isSel]);
  useEffect(() => { if (!hl) setHlOpen(false); }, [!!hl]);
  useEffect(() => setTxt(sent.text), [sent.text]);

  // 再生中の文へ自動スクロール
  useEffect(() => {
    if (isPlay && cardRef.current) {
      cardRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isPlay]);

  const sel = () => dispatch({ type: "SEL_SENT", v: sent.id });

  const ovBtnBase = {
    display: "inline-flex", alignItems: "center", gap: 2,
    padding: "2px 7px", borderRadius: 3, fontSize: 9,
    border: "1px solid transparent", lineHeight: 1.6,
    fontFamily: "var(--fb)",
    opacity: isSel ? 1 : 0.3,
    transition: "opacity .15s",
  };

  return (
    <div
      ref={cardRef}
      onClick={(e) => { if (e.target.contentEditable !== "true") sel(); }}
      style={{
        borderBottom: "1px solid var(--bd)",
        background:   isSel ? "var(--s2)" : isPlay ? "var(--adim)" : "transparent",
        borderLeft:   isPlay ? "3px solid var(--ac)" : "none",
        transition:   "background .15s",
      }}
    >
      <div style={{ padding: "9px 12px" }}>

        {/* ヘッダー行 */}
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 6, flexWrap: "wrap" }}>
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", minWidth: 18 }}>{idx + 1}</span>
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", background: "var(--s3)", padding: "1px 5px", borderRadius: 3 }}>
            {fmt(sent.start_sec)}–{fmt(sent.end_sec)}
          </span>
          {/* 音声モード：タイミング編集ボタン */}
          {!showHl && (
            <button
              onClick={(e) => { e.stopPropagation(); sel(); setTimingOpen((p) => !p); }}
              style={{ ...ovBtnBase, background: "rgba(232,169,75,.14)", borderColor: "rgba(232,169,75,.3)", color: "var(--am)" }}
            >
              ⏱ タイミング
            </button>
          )}
        </div>

        {/* テキスト + オーバーレイボタン */}
        <div style={{ position: "relative", marginBottom: 6 }}>
          {/* 左上：AI修正・HL設定（音声モードはHLなし） */}
          <div style={{ position: "absolute", top: 0, left: 0, display: "flex", gap: 3, pointerEvents: "all", zIndex: 5 }}>
            <button
              onClick={(e) => { e.stopPropagation(); sel(); setAiOpen((p) => !p); setHlOpen(false); setTimingOpen(false); }}
              style={{ ...ovBtnBase, background: "rgba(167,139,250,.18)", borderColor: "rgba(167,139,250,.35)", color: "var(--pu)" }}
            >
              ✨ AI修正
            </button>
            {showHl && (
              <button
                onClick={(e) => { e.stopPropagation(); sel(); setHlOpen((p) => !p); setAiOpen(false); }}
                style={{ ...ovBtnBase, background: "rgba(91,141,239,.18)", borderColor: "rgba(91,141,239,.35)", color: "var(--ac)" }}
              >
                🔦 HL設定
              </button>
            )}
          </div>
          {/* 右上：削除 */}
          <div style={{ position: "absolute", top: 0, right: 0, pointerEvents: "all", zIndex: 5 }}>
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (confirm("この文を削除しますか？")) dispatch({ type: "DEL_SENT", v: sent.id });
              }}
              style={{ ...ovBtnBase, background: "rgba(224,91,91,.16)", borderColor: "rgba(224,91,91,.3)", color: "var(--rd)" }}
            >
              🗑
            </button>
          </div>
          {/* テキスト本体 */}
          <div
            contentEditable
            suppressContentEditableWarning
            onBlur={(e) => {
              const t = e.currentTarget.textContent;
              if (t !== sent.text) dispatch({ type: "UPD_TXT", id: sent.id, text: t });
            }}
            style={{ fontSize: 12, lineHeight: 1.62, color: "var(--tp)", borderRadius: 3, padding: "20px 28px 5px 4px", display: "block", width: "100%", outline: "none", cursor: "text" }}
          >
            {txt}
          </div>
        </div>

        {/* HLサマリーバー（動画モード時のみ） */}
        {showHl && (
          <HlSummaryBar
            hl={hl}
            sent={sent}
            onClick={(e) => { e.stopPropagation(); sel(); setHlOpen((p) => !p); setAiOpen(false); }}
          />
        )}

        {/* タイミング編集（音声モード時のみ） */}
        {timingOpen && !showHl && (
          <TimingEditor sent={sent} dispatch={dispatch} />
        )}

        {/* AIパネル */}
        {aiOpen && (
          <AiPanel
            text={sent.text}
            onApply={(t) => dispatch({ type: "UPD_TXT", id: sent.id, text: t })}
            addToast={addToast}
          />
        )}

        {/* HLエディタ */}
        {hlOpen && showHl && (
          <HlEditor
            sid={sent.id}
            hl={hl}
            dispatch={dispatch}
            drawMode={drawMode}
            drawSentId={drawSentId}
          />
        )}
      </div>
    </div>
  );
}

/**
 * タイミング編集（音声モード専用）
 * start_sec / end_sec を直接入力
 */
function TimingEditor({ sent, dispatch }) {
  const [start, setStart] = useState(String(sent.start_sec));
  const [end,   setEnd]   = useState(String(sent.end_sec));

  const apply = () => {
    const s = parseFloat(start);
    const e = parseFloat(end);
    if (isNaN(s) || isNaN(e) || e <= s) return;
    dispatch({ type: "UPD_SENT_TIME", id: sent.id, start_sec: s, end_sec: e });
  };

  const inputSty = {
    width: 72, padding: "4px 6px",
    background: "var(--s3)", border: "1px solid var(--bd)",
    borderRadius: 4, color: "var(--tp)",
    fontFamily: "var(--fm)", fontSize: 11, outline: "none",
  };

  return (
    <div style={{ marginTop: 8, padding: "8px 10px", background: "var(--s3)", border: "1px solid rgba(232,169,75,.2)", borderRadius: "var(--r)" }}>
      <div style={{ fontSize: 10, color: "var(--am)", marginBottom: 7 }}>⏱ タイミング編集（秒）</div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div>
          <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>開始</div>
          <input type="number" value={start} step="0.1" min="0" onChange={(e) => setStart(e.target.value)} style={inputSty} />
        </div>
        <div style={{ color: "var(--tm)", marginTop: 14 }}>→</div>
        <div>
          <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>終了</div>
          <input type="number" value={end} step="0.1" min="0" onChange={(e) => setEnd(e.target.value)} style={inputSty} />
        </div>
        <button
          onClick={apply}
          style={{ marginTop: 14, padding: "4px 10px", background: "var(--amd)", border: "1px solid var(--am)", borderRadius: 4, color: "var(--am)", fontSize: 10 }}
        >
          適用
        </button>
      </div>
    </div>
  );
}
