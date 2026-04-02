import { KIND_LABEL } from "../utils/constants.js";
import { getHighlightRegionMeta } from "../utils/highlightPresentation.js";

const KINDS = ["marker", "arrow", "box"];

export default function HlEditor({
  sid,
  sentence,
  hl,
  slideHighlights,
  dispatch,
  drawMode,
  drawSentId,
}) {
  const curKind = hl?.kind ?? null;
  const isDraw = drawMode && drawSentId === sid;
  const currentRegionMeta = getHighlightRegionMeta(slideHighlights, hl?.id);

  const setKind = (kind) => {
    dispatch({ type: "PUSH_HISTORY" });
    if (hl) {
      dispatch({ type: "SET_HL_KIND", id: hl.id, kind });
      return;
    }
    dispatch({ type: "SET", k: "drawMode", v: true });
    dispatch({ type: "SET", k: "drawSentId", v: sid });
  };

  const selectRegion = (highlightId) => {
    if (!highlightId) {
      if (!hl) return;
      dispatch({ type: "PUSH_HISTORY" });
      dispatch({ type: "UNLINK_SENT_FROM_HL", id: hl.id, sid });
      return;
    }
    if (hl?.id === highlightId) return;
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "LINK_SENT_TO_HL", id: highlightId, sid });
  };

  const kindBtnStyle = (kind) => {
    const active = curKind === kind;
    return {
      flex: 1,
      padding: "7px 4px",
      border: "none",
      borderLeft: kind !== KINDS[0] ? "1px solid var(--bd)" : "none",
      background: active ? "rgba(110,193,255,.16)" : "none",
      color: active ? "var(--tp)" : "var(--ts)",
      fontFamily: "var(--fb)",
      fontSize: 11,
      cursor: "pointer",
      textAlign: "center",
    };
  };

  return (
    <div style={{ marginTop: 8, borderRadius: "var(--r)", overflow: "hidden", border: "1px solid var(--bd2)" }}>
      <div style={{ display: "flex", background: "var(--s3)", borderBottom: "1px solid var(--bd)" }}>
        {KINDS.map((kind) => (
          <button key={kind} onClick={() => setKind(kind)} style={kindBtnStyle(kind)}>
            {KIND_LABEL[kind]}
          </button>
        ))}
      </div>

      <div style={{ background: "var(--s2)", padding: 10 }}>
        {hl ? (
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <span style={{ fontSize: 11, color: currentRegionMeta.color, fontFamily: "var(--fm)" }}>
                {currentRegionMeta.label}
              </span>
              <span style={{ fontSize: 10, color: "var(--ts)" }}>
                {(hl.sentence_ids ?? []).length} 件の台本に対応
              </span>
            </div>
          </div>
        ) : (
          <div style={{ marginBottom: 8, fontSize: 10, color: "var(--tm)" }}>
            この文はまだどの領域にも対応していません。領域を選ぶか、種類を選んで新しい領域を描画してください。
          </div>
        )}

        {isDraw ? (
          <div style={{ marginBottom: 10, padding: "6px 8px", borderRadius: 6, background: "rgba(110,193,255,.12)", border: "1px solid rgba(110,193,255,.24)", fontSize: 10, color: "var(--tp)" }}>
            描画モードです。プレビュー上で新しい領域を描いてください。
          </div>
        ) : null}

        <HighlightRegionPicker
          sentence={sentence}
          current={hl}
          slideHighlights={slideHighlights}
          onSelect={selectRegion}
        />
      </div>
    </div>
  );
}

function HighlightRegionPicker({ sentence, current, slideHighlights, onSelect }) {
  const currentMeta = current ? getHighlightRegionMeta(slideHighlights, current.id) : null;
  const rows = slideHighlights ?? [];

  return (
    <div style={{ borderTop: "1px solid var(--bd)", paddingTop: 8 }}>
      <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>対応付け</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        <button
          onClick={() => onSelect(null)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 8px",
            borderRadius: 999,
            border: current ? "1px solid rgba(255,255,255,.12)" : "1px solid rgba(110,193,255,.35)",
            background: current ? "var(--s3)" : "rgba(110,193,255,.14)",
            color: current ? "var(--ts)" : "var(--tp)",
            fontSize: 10,
          }}
        >
          選択なし
        </button>
        {rows.map((item) => {
          const meta = getHighlightRegionMeta(slideHighlights, item.id);
          const selected = current?.id === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelect(item.id)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 8px",
                borderRadius: 999,
                border: `1px solid ${selected ? meta.border : `${meta.color}55`}`,
                background: selected ? meta.bgStrong : meta.bg,
                color: "var(--tp)",
                fontSize: 10,
              }}
            >
              <span style={{ color: meta.color, fontFamily: "var(--fm)" }}>{meta.label}</span>
            </button>
          );
        })}
      </div>
      {rows.length === 0 ? (
        <div style={{ marginTop: 8, fontSize: 10, color: "var(--tm)" }}>このスライドにはまだ領域がありません</div>
      ) : null}
      {currentMeta ? (
        <div style={{ marginTop: 8, fontSize: 10, color: "var(--ts)" }}>
          現在: <span style={{ color: currentMeta.color, fontFamily: "var(--fm)" }}>{currentMeta.label}</span>
        </div>
      ) : null}
      {sentence ? (
        <div style={{ marginTop: 6, fontSize: 9, color: "var(--tm)", lineHeight: 1.5 }}>
          文: {sentence?.text?.slice(0, 42) ?? ""}{sentence?.text?.length > 42 ? "…" : ""}
        </div>
      ) : null}
    </div>
  );
}
