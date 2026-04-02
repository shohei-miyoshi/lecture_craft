import MiniSlide from "./MiniSlide.jsx";
import { KIND_LABEL, KIND_COLOR } from "../utils/constants.js";
import { rn } from "../utils/helpers.js";

const KINDS = ["none", "marker", "arrow", "box"];

/**
 * HL設定パネル（SentenceCard 内に展開）
 * - 種別選択（なし / マーカー / 矢印 / 囲み）
 * - ミニスライドで位置調整
 * - 座標入力
 * - 再描画ボタン
 */
export default function HlEditor({ sid, hl, dispatch, drawMode, drawSentId }) {
  const curKind = hl?.kind ?? null;
  const isDraw  = drawMode && drawSentId === sid;

  const setKind = (k) => {
    dispatch({ type: "PUSH_HISTORY" });
    if (k === "none") { dispatch({ type: "RM_HL_SID", v: sid }); return; }
    if (hl)           dispatch({ type: "SET_HL_KIND", id: hl.id, kind: k });
    // HL未設定の場合は「領域を描く」を促す（トースト通知はApp層で行う）
  };

  const startDraw = () => {
    dispatch({ type: "SET", k: "drawMode",   v: true });
    dispatch({ type: "SET", k: "drawSentId", v: sid  });
  };

  const kindBtnStyle = (k) => {
    const on = curKind === k || (!curKind && k === "none");
    const colorMap = {
      marker: [KIND_COLOR.marker, "rgba(91,141,239,.18)"],
      arrow:  [KIND_COLOR.arrow,  "rgba(76,175,130,.18)"],
      box:    [KIND_COLOR.box,    "rgba(232,169,75,.18)"],
      none:   ["var(--ts)",       "var(--s4)"],
    };
    const [c, bg] = colorMap[k] ?? ["var(--ts)", "none"];
    return {
      flex: 1, padding: "7px 4px", border: "none",
      borderLeft: k !== "none" ? "1px solid var(--bd)" : "none",
      background: on ? bg : "none",
      color: on ? c : "var(--ts)",
      fontFamily: "var(--fb)", fontSize: 11, cursor: "pointer",
      position: "relative", textAlign: "center",
    };
  };

  return (
    <div style={{ marginTop: 8, borderRadius: "var(--r)", overflow: "hidden", border: "1px solid var(--bd2)" }}>

      {/* 種別選択バー */}
      <div style={{ display: "flex", background: "var(--s3)", borderBottom: "1px solid var(--bd)" }}>
        {KINDS.map((k) => (
          <button key={k} onClick={() => setKind(k)} style={kindBtnStyle(k)}>
            {k === "none" ? "なし" : KIND_LABEL[k]}
            {curKind === k && k !== "none" && (
              <div style={{ position: "absolute", bottom: 0, left: "50%", transform: "translateX(-50%)", width: 16, height: 2, borderRadius: 1, background: KIND_COLOR[k] }} />
            )}
          </button>
        ))}
      </div>

      {/* 領域設定ボディ */}
      <div style={{ background: "var(--s2)", padding: 10 }}>
        {hl ? (
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <MiniSlide hl={hl} dispatch={dispatch} />
            <div style={{ flex: 1 }}>
              {/* 座標入力グリッド */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 8 }}>
                {[["x","X"],["y","Y"],["w","W"],["h","H"]].map(([f, lbl]) => (
                  <div key={f}>
                    <div style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginBottom: 3 }}>{lbl} %</div>
                    <input
                      type="number"
                      value={rn(hl[f])}
                      min={f === "w" || f === "h" ? 4 : 0}
                      max={f === "w" || f === "h" ? 100 : 95}
                      onChange={(e) =>
                        dispatch({ type: "UPD_HL", id: hl.id,
                          x: f==="x" ? +e.target.value : hl.x,
                          y: f==="y" ? +e.target.value : hl.y,
                          w: f==="w" ? +e.target.value : hl.w,
                          hv: f==="h" ? +e.target.value : hl.h })
                      }
                      style={{ width: "100%", padding: "4px 6px", background: "var(--s3)", border: "1px solid var(--bd)", borderRadius: 4, color: "var(--tp)", fontFamily: "var(--fm)", fontSize: 11, outline: "none" }}
                    />
                  </div>
                ))}
              </div>
              {/* アクションボタン */}
              <div style={{ display: "flex", gap: 5 }}>
                <button onClick={startDraw} style={{
                  padding: "4px 9px",
                  border: `1px solid ${isDraw ? "var(--am)" : "rgba(232,169,75,.35)"}`,
                  borderRadius: 4,
                  background: isDraw ? "rgba(232,169,75,.25)" : "var(--amd)",
                  color: "var(--am)", fontSize: 10,
                }}>
                  ✏ {isDraw ? "描画中…" : "再描画"}
                </button>
                <button onClick={() => { dispatch({ type: "PUSH_HISTORY" }); dispatch({ type: "RM_HL_SID", v: sid }); }} style={{ padding: "4px 9px", border: "1px solid rgba(224,91,91,.2)", borderRadius: 4, background: "var(--rdd)", color: "var(--rd)", fontSize: 10 }}>
                  🗑 HL削除
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 10, color: "var(--tm)", marginBottom: 8 }}>種別を選択してから「描く」ボタンを押してください</div>
            <button onClick={startDraw} style={{
              padding: "4px 9px",
              border: `1px solid ${isDraw ? "var(--am)" : "rgba(232,169,75,.35)"}`,
              borderRadius: 4, background: "var(--amd)", color: "var(--am)", fontSize: 10,
            }}>
              ✏ {isDraw ? "描画中…" : "スライドに領域を描く"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
