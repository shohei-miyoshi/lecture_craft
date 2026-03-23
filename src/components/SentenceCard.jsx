import { useState, useEffect } from "react";
import HlSummaryBar from "./HlSummaryBar.jsx";
import HlEditor     from "./HlEditor.jsx";
import AiPanel      from "./AiPanel.jsx";
import { fmt } from "../utils/helpers.js";

/**
 * 台本1文カード
 * - テキスト直接編集（contentEditable）
 * - ✨AI修正 / 🔦HL設定 ボタン（常時薄く表示、ホバー・選択で濃く）
 * - 🗑 削除ボタン（右上）
 * - HLサマリーバー（テキスト下）
 * - AIパネル / HLエディタ（選択時に展開）
 */
export default function SentenceCard({ sent, idx, hl, isSel, isPlay, drawMode, drawSentId, dispatch, addToast }) {
  const [hlOpen, setHlOpen] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [txt,    setTxt]    = useState(sent.text);

  // 別文選択でパネルを閉じる
  useEffect(() => { if (!isSel) { setHlOpen(false); setAiOpen(false); } }, [isSel]);
  // HL削除されたらエディタを閉じる
  useEffect(() => { if (!hl) setHlOpen(false); }, [!!hl]);
  // 外部からテキストが変わったとき同期（AI修正適用後など）
  useEffect(() => setTxt(sent.text), [sent.text]);

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
      onClick={(e) => { if (e.target.contentEditable !== "true") sel(); }}
      style={{
        borderBottom: "1px solid var(--bd)",
        background:   isSel ? "var(--s2)" : isPlay ? "var(--adim)" : "transparent",
        borderLeft:   isPlay ? "3px solid var(--ac)" : "none",
      }}
    >
      <div style={{ padding: "9px 12px" }}>

        {/* ヘッダー行（番号・時刻） */}
        <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 6 }}>
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", minWidth: 18 }}>{idx + 1}</span>
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", background: "var(--s3)", padding: "1px 5px", borderRadius: 3 }}>
            {fmt(sent.start_sec)}–{fmt(sent.end_sec)}
          </span>
        </div>

        {/* テキスト + オーバーレイボタン */}
        <div style={{ position: "relative", marginBottom: 6 }}>
          {/* 左上：AI修正・HL設定 */}
          <div style={{ position: "absolute", top: 0, left: 0, display: "flex", gap: 3, pointerEvents: "all", zIndex: 5 }}>
            <button
              onClick={(e) => { e.stopPropagation(); sel(); setAiOpen((p) => !p); setHlOpen(false); }}
              style={{ ...ovBtnBase, background: "rgba(167,139,250,.18)", borderColor: "rgba(167,139,250,.35)", color: "var(--pu)" }}
            >
              ✨ AI修正
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); sel(); setHlOpen((p) => !p); setAiOpen(false); }}
              style={{ ...ovBtnBase, background: "rgba(91,141,239,.18)", borderColor: "rgba(91,141,239,.35)", color: "var(--ac)" }}
            >
              🔦 HL設定
            </button>
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
          {/* テキスト本体（直接編集可） */}
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

        {/* HLサマリーバー */}
        <HlSummaryBar
          hl={hl}
          sent={sent}
          onClick={(e) => { e.stopPropagation(); sel(); setHlOpen((p) => !p); setAiOpen(false); }}
        />

        {/* AIパネル（展開時） */}
        {aiOpen && (
          <AiPanel
            text={sent.text}
            onApply={(t) => dispatch({ type: "UPD_TXT", id: sent.id, text: t })}
            addToast={addToast}
          />
        )}

        {/* HLエディタ（展開時） */}
        {hlOpen && (
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
