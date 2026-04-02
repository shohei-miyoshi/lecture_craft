import SentenceCard from "./SentenceCard.jsx";

/**
 * 右パネル — 台本 + HL統合編集
 *
 * 上部にエディタ/書き出しタブを配置
 */
export default function RightPanel({ state, dispatch, addToast, requestConfirm, tab, setTab, rightContent }) {
  const isAudio  = state.appMode === "audio";
  const curSents = isAudio
    ? state.sents
    : state.sents.filter((s) => s.slide_idx === state.curSl);
  const actSent  = state.sents.find(
    (s) => s.start_sec <= state.curT && state.curT < s.end_sec
  );

  const tabSty = (on) => ({
    padding: "5px 14px",
    border: "none",
    borderBottom: `2px solid ${on ? "var(--ac)" : "transparent"}`,
    background: "none",
    color: on ? "var(--ac)" : "var(--ts)",
    fontFamily: "var(--fb)",
    fontSize: 11,
    cursor: "pointer",
    fontWeight: on ? 600 : 400,
    transition: "var(--tr)",
  });

  return (
    <aside style={{ display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0, background: "var(--sur)", borderLeft: "1px solid var(--bd)", minHeight: 0 }}>

      {/* ── タブ ── */}
      <div style={{ display: "flex", alignItems: "flex-end", borderBottom: "1px solid var(--bd)", background: "var(--sur)", flexShrink: 0, paddingLeft: 4 }}>
        <button onClick={() => setTab("editor")} style={tabSty(tab === "editor")}>エディタ</button>
        <button onClick={() => setTab("export")} style={tabSty(tab === "export")}>書き出し</button>
      </div>

      {/* ── エディタタブ ── */}
      {tab === "editor" && (
        <>
          <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
              <span style={{ fontFamily: "var(--ff)", fontSize: 12, fontWeight: 700 }}>
                {isAudio ? "台本編集" : "台本 ＋ ハイライト編集"}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <button onClick={() => dispatch({ type: "UNDO" })} style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>
                  ↶ 戻る
                </button>
                <button onClick={() => dispatch({ type: "REDO" })} style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>
                  ↷ 進む
                </button>
                <button
                  onClick={() => { dispatch({ type: "PUSH_HISTORY" }); dispatch({ type: "ADD_SENT" }); }}
                  style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}
                >
                  ＋ 文追加
                </button>
              </div>
            </div>
            <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.45 }}>
              {isAudio
                ? "文クリックで選択 → テキスト直接編集 or ✨AI修正 ／ ⏱ タイミング編集"
                : "文クリックで選択 → テキスト直接編集 or ✨AI修正 ／ 左帯とボタンでHL設定"}
            </div>
          </div>

          <div style={{ flex: 1, minHeight: 0, overflowY: "auto", scrollbarGutter: "stable", overscrollBehavior: "contain" }}>
            {curSents.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 28, color: "var(--tm)", fontSize: 11, gap: 5, textAlign: "center" }}>
                <div style={{ fontSize: 24, opacity: 0.4 }}>📝</div>
                <p>{state.generated ? (isAudio ? "台本なし" : "このスライドに台本なし") : "生成後に表示されます"}</p>
              </div>
            ) : (
              curSents.map((s, i) => (
                <SentenceCard
                  key={s.id}
                  sent={s}
                  idx={i}
                  hl={state.hls.find((h) => h.sid === s.id)}
                  isSel={s.id === state.selSent}
                  isPlay={!!(actSent && actSent.id === s.id)}
                  drawMode={state.drawMode}
                  drawSentId={state.drawSentId}
                  dispatch={dispatch}
                  addToast={addToast}
                  requestConfirm={requestConfirm}
                  showHl={!isAudio}
                />
              ))
            )}
          </div>
        </>
      )}

      {/* ── 書き出しタブ ── */}
      {tab === "export" && rightContent}
    </aside>
  );
}
