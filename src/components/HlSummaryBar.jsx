import { KIND_LABEL, KIND_COLOR, KIND_BG } from "../utils/constants.js";
import { fmt, rn } from "../utils/helpers.js";

/**
 * 台本カード下部のHL状態サマリー（1行）
 * クリックするとHLEditorが開く
 */
export default function HlSummaryBar({ hl, sent, onClick }) {
  const c = hl ? KIND_COLOR[hl.kind] : null;

  return (
    <div onClick={onClick} style={{
      display: "flex", alignItems: "center", gap: 5,
      padding: "4px 6px", borderRadius: 4,
      fontFamily: "var(--fm)", fontSize: 9, marginTop: 2, cursor: "pointer",
      border: `1px solid ${hl ? c + "33" : "var(--bd)"}`,
      background: hl ? KIND_BG[hl.kind] : "var(--s2)",
    }}>
      {hl ? (
        <>
          <div style={{ width: 7, height: 7, borderRadius: "50%", background: c, flexShrink: 0 }} />
          <span style={{ fontWeight: 500, color: c }}>{KIND_LABEL[hl.kind]}</span>
          <span style={{ color: "var(--tm)", marginLeft: 2 }}>
            X:{rn(hl.x)}% Y:{rn(hl.y)}% W:{rn(hl.w)}% H:{rn(hl.h)}%
          </span>
          {sent && (
            <span style={{ color: "var(--ts)", marginLeft: "auto" }}>
              {fmt(sent.start_sec)}–{fmt(sent.end_sec)}
            </span>
          )}
        </>
      ) : (
        <>
          <span style={{ color: "var(--tm)" }}>HL なし</span>
          <span style={{ color: "var(--tm)", fontStyle: "italic", marginLeft: 4 }}>— クリックして設定</span>
        </>
      )}
    </div>
  );
}
