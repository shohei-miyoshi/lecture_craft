import { useState, useEffect, useRef } from "react";
import HlEditor     from "./HlEditor.jsx";
import AiPanel      from "./AiPanel.jsx";
import { fmt } from "../utils/helpers.js";

export default function SentenceCard({
  sent, idx, hl, isSel, isPlay, drawMode, drawSentId,
  dispatch, addToast, requestConfirm,
  showHl = true,
}) {
  const [hlOpen,     setHlOpen]     = useState(false);
  const [aiOpen,     setAiOpen]     = useState(false);
  const [timingOpen, setTimingOpen] = useState(false);
  const [txt,        setTxt]        = useState(sent.text);
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

  const handleDelete = (e) => {
    e.stopPropagation();
    requestConfirm({
      title:        "文を削除",
      message:      `「${sent.text.substring(0, 40)}${sent.text.length > 40 ? "…" : ""}」\nを削除しますか？この操作は取り消せません。`,
      confirmLabel: "削除",
      onConfirm:    () => {
        dispatch({ type: "PUSH_HISTORY" });
        dispatch({ type: "DEL_SENT", v: sent.id });
      },
    });
  };

  const railLabel = hl ? `HL\n${HlRailLabel(hl.kind)}` : "HL\n未設定";
  const railColor = hl ? "var(--tp)" : "var(--tm)";
  const railBg = hl ? `linear-gradient(180deg, ${hlColorBg(hl.kind)}, rgba(255,255,255,.03))` : "var(--s3)";

  return (
    <div
      ref={cardRef}
      onClick={(e) => { if (e.target.contentEditable !== "true") sel(); }}
      style={{
        borderBottom: "1px solid var(--bd)",
        background:   isSel ? "var(--s2)" : isPlay ? "var(--adim)" : "transparent",
        borderLeft:   isPlay ? "3px solid var(--ac)" : "none",
        transition:   "background .15s",
        position: "relative",
      }}
    >
      {showHl && (
        <button
          onClick={(e) => { e.stopPropagation(); sel(); setHlOpen((p) => !p); setAiOpen(false); }}
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: 26,
            border: "none",
            borderRight: "1px solid var(--bd)",
            background: railBg,
            color: railColor,
            fontFamily: "var(--fm)",
            fontSize: 9,
            whiteSpace: "pre-line",
            lineHeight: 1.15,
            cursor: "pointer",
            textAlign: "center",
            padding: "8px 2px",
          }}
        >
          {railLabel}
        </button>
      )}

      <div style={{ padding: "9px 12px", paddingLeft: showHl ? 36 : 12 }}>

        {/* ヘッダー行 */}
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 6, flexWrap: "wrap" }}>
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", minWidth: 18 }}>{idx + 1}</span>
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", background: "var(--s3)", padding: "1px 5px", borderRadius: 3 }}>
            {fmt(sent.start_sec)}–{fmt(sent.end_sec)}
          </span>
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
          <div style={{ position: "absolute", top: 0, right: 0, pointerEvents: "all", zIndex: 5 }}>
            <button
              onClick={handleDelete}
              style={{ ...ovBtnBase, background: "rgba(224,91,91,.16)", borderColor: "rgba(224,91,91,.3)", color: "var(--rd)" }}
            >
              🗑
            </button>
          </div>
          <div
            contentEditable
            suppressContentEditableWarning
            onBlur={(e) => {
              const t = e.currentTarget.textContent;
              if (t !== sent.text) {
                dispatch({ type: "PUSH_HISTORY" });
                dispatch({ type: "UPD_TXT", id: sent.id, text: t });
              }
            }}
            style={{ fontSize: 12, lineHeight: 1.62, color: "var(--tp)", borderRadius: 3, padding: "20px 28px 5px 4px", display: "block", width: "100%", outline: "none", cursor: "text" }}
          >
            {txt}
          </div>
        </div>

        {timingOpen && !showHl && <TimingEditor sent={sent} dispatch={dispatch} />}

        {aiOpen && (
          <AiPanel
            text={sent.text}
            onApply={(t) => dispatch({ type: "UPD_TXT", id: sent.id, text: t })}
            addToast={addToast}
          />
        )}

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

function HlRailLabel(kind) {
  switch (kind) {
    case "marker":
      return "マー\nカー";
    case "arrow":
      return "矢印";
    case "box":
      return "囲み";
    default:
      return "設定";
  }
}

function hlColorBg(kind) {
  switch (kind) {
    case "marker":
      return "rgba(91,141,239,.28)";
    case "arrow":
      return "rgba(76,175,130,.26)";
    case "box":
      return "rgba(232,169,75,.26)";
    default:
      return "rgba(255,255,255,.04)";
  }
}

function TimingEditor({ sent, dispatch }) {
  const [start, setStart] = useState(String(sent.start_sec));
  const [end,   setEnd]   = useState(String(sent.end_sec));

  const apply = () => {
    const s = parseFloat(start);
    const e = parseFloat(end);
    if (isNaN(s) || isNaN(e) || e <= s) return;
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "UPD_SENT_TIME", id: sent.id, start_sec: s, end_sec: e });
  };

  const iSty = {
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
          <input type="number" value={start} step="0.1" min="0" onChange={(e) => setStart(e.target.value)} style={iSty} />
        </div>
        <div style={{ color: "var(--tm)", marginTop: 14 }}>→</div>
        <div>
          <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>終了</div>
          <input type="number" value={end} step="0.1" min="0" onChange={(e) => setEnd(e.target.value)} style={iSty} />
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
