import { KIND_LABEL } from "../utils/constants.js";
import { getHighlightRegionMeta } from "../utils/highlightPresentation.js";

const KINDS = ["none", "marker", "arrow", "box"];

export default function HlEditor({
  sid,
  sentence,
  hl,
  slideHighlights,
  dispatch,
  drawMode,
  drawSentId,
  requestConfirm,
}) {
  const curKind = hl?.kind ?? null;
  const isDraw = drawMode && drawSentId === sid;
  const availableHighlights = (slideHighlights ?? []).filter((item) => item.id !== hl?.id);
  const currentRegionMeta = getHighlightRegionMeta(slideHighlights, hl?.id);

  const setKind = (k) => {
    dispatch({ type: "PUSH_HISTORY" });
    if (k === "none") {
      dispatch({ type: "RM_HL_SID", v: sid });
      return;
    }
    if (hl) {
      dispatch({ type: "SET_HL_KIND", id: hl.id, kind: k });
      return;
    }
    dispatch({ type: "SET", k: "drawMode", v: true });
    dispatch({ type: "SET", k: "drawSentId", v: sid });
  };

  const startDraw = () => {
    dispatch({ type: "SET", k: "drawMode", v: true });
    dispatch({ type: "SET", k: "drawSentId", v: sid });
  };

  const linkExisting = (highlightId) => {
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "LINK_SENT_TO_HL", id: highlightId, sid });
  };

  const unlinkCurrent = () => {
    if (!hl) return;
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({ type: "UNLINK_SENT_FROM_HL", id: hl.id, sid });
  };

  const removeCurrentBox = () => {
    if (!hl) return;
    const linkedCount = (hl.sentence_ids ?? []).length;
    const run = () => {
      dispatch({ type: "PUSH_HISTORY" });
      dispatch({ type: "RM_HL_ID", v: hl.id });
    };
    if (linkedCount > 1) {
      requestConfirm?.({
        title: "共有ハイライト枠を削除",
        message: `この枠は ${linkedCount} 個の台本と対応しています。\n削除すると関連する対応も一緒に消えますが、大丈夫ですか？`,
        confirmLabel: "削除する",
        onConfirm: run,
      });
      return;
    }
    run();
  };

  const kindBtnStyle = (k) => {
    const on = curKind === k || (!curKind && k === "none");
    return {
      flex: 1,
      padding: "7px 4px",
      border: "none",
      borderLeft: k !== "none" ? "1px solid var(--bd)" : "none",
      background: on ? "rgba(110,193,255,.16)" : "none",
      color: on ? "var(--tp)" : "var(--ts)",
      fontFamily: "var(--fb)",
      fontSize: 11,
      cursor: "pointer",
      position: "relative",
      textAlign: "center",
    };
  };

  return (
    <div style={{ marginTop: 8, borderRadius: "var(--r)", overflow: "hidden", border: "1px solid var(--bd2)" }}>
      <div style={{ display: "flex", background: "var(--s3)", borderBottom: "1px solid var(--bd)" }}>
        {KINDS.map((k) => (
          <button key={k} onClick={() => setKind(k)} style={kindBtnStyle(k)}>
            {k === "none" ? "対応なし" : KIND_LABEL[k]}
          </button>
        ))}
      </div>

      <div style={{ background: "var(--s2)", padding: 10 }}>
        {hl ? (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              <span style={{ fontSize: 11, color: currentRegionMeta.color, fontFamily: "var(--fm)" }}>
                {currentRegionMeta.label}
              </span>
              <span style={{ fontSize: 10, color: "var(--ts)" }}>
                {(hl.sentence_ids ?? []).length} 件の台本に対応
              </span>
            </div>

            <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginBottom: 10 }}>
              <button onClick={startDraw} style={{ padding: "4px 9px", border: "1px solid rgba(110,193,255,.35)", borderRadius: 4, background: isDraw ? "rgba(110,193,255,.24)" : "rgba(110,193,255,.12)", color: "var(--tp)", fontSize: 10 }}>
                ✏ {isDraw ? "描画中…" : "再描画"}
              </button>
              <button onClick={unlinkCurrent} style={{ padding: "4px 9px", border: "1px solid var(--bd)", borderRadius: 4, background: "var(--s3)", color: "var(--ts)", fontSize: 10 }}>
                この文との対応だけ解除
              </button>
              <button onClick={removeCurrentBox} style={{ padding: "4px 9px", border: "1px solid rgba(224,91,91,.2)", borderRadius: 4, background: "var(--rdd)", color: "var(--rd)", fontSize: 10 }}>
                枠ごと削除
              </button>
            </div>

            <HighlightLinkPanel
              sentence={sentence}
              current={hl}
              slideHighlights={slideHighlights}
              availableHighlights={availableHighlights}
              onLink={linkExisting}
            />
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 8 }}>
              この文はまだどのハイライト領域にも対応していません。既存の領域を選ぶか、新規に作成してください。
            </div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: availableHighlights.length ? 10 : 0 }}>
              <button onClick={startDraw} style={{ padding: "4px 9px", border: "1px solid rgba(110,193,255,.35)", borderRadius: 4, background: "rgba(110,193,255,.12)", color: "var(--tp)", fontSize: 10 }}>
                ✏ {isDraw ? "描画中…" : "新規枠を描く"}
              </button>
            </div>
            <HighlightLinkPanel
              sentence={sentence}
              current={null}
              slideHighlights={slideHighlights}
              availableHighlights={availableHighlights}
              onLink={linkExisting}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function HighlightLinkPanel({ sentence, current, slideHighlights, availableHighlights, onLink }) {
  const currentMeta = current ? getHighlightRegionMeta(slideHighlights, current.id) : null;
  return (
    <div style={{ borderTop: "1px solid var(--bd)", paddingTop: 8 }}>
      <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 6 }}>
        {current ? "別の領域に切り替える" : "既存の領域に対応させる"}
      </div>
      {current && currentMeta && (
        <div style={{ padding: "6px 8px", borderRadius: 6, background: currentMeta.bg, border: `1px solid ${currentMeta.color}55`, fontSize: 10, color: "var(--tp)", marginBottom: 6 }}>
          現在の領域: <span style={{ color: currentMeta.color, fontFamily: "var(--fm)" }}>{currentMeta.label}</span> / {(current.sentence_ids ?? []).length} 文に対応
        </div>
      )}
      {availableHighlights.length === 0 ? (
        <div style={{ fontSize: 10, color: "var(--tm)" }}>使える既存の領域はありません</div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {availableHighlights.map((item) => {
            const meta = getHighlightRegionMeta(slideHighlights, item.id);
            return (
              <button
                key={item.id}
                onClick={() => onLink(item.id)}
                style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 8px", borderRadius: 999, border: `1px solid ${meta.color}55`, background: meta.bg, color: "var(--tp)", fontSize: 10 }}
              >
                <span style={{ color: meta.color, fontFamily: "var(--fm)" }}>{meta.label}</span>
                <span style={{ color: "var(--tm)" }}>{(item.sentence_ids ?? []).length} 文</span>
              </button>
            );
          })}
        </div>
      )}
      {sentence && (
        <div style={{ marginTop: 6, fontSize: 9, color: "var(--tm)", lineHeight: 1.5 }}>
          文: {sentence?.text?.slice(0, 42) ?? ""}{sentence?.text?.length > 42 ? "…" : ""}
        </div>
      )}
    </div>
  );
}
