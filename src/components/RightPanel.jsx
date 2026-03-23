import SentenceCard from "./SentenceCard.jsx";

/**
 * 右パネル — 台本 + HL統合編集
 * - appMode === "audio" のとき showHl=false でHL UIを隠す
 * - 全文を表示（音声モードはスライド区切りなし）
 */
export default function RightPanel({ state, dispatch, addToast }) {
  const isAudio  = state.appMode === "audio";
  // 音声モード：全文表示。動画系：現在スライドの文のみ
  const curSents = isAudio
    ? state.sents
    : state.sents.filter((s) => s.slide_idx === state.curSl);

  const actSent = state.sents.find(
    (s) => s.start_sec <= state.curT && state.curT < s.end_sec
  );

  return (
    <aside style={{ width: 380, minWidth: 340, background: "var(--sur)", borderLeft: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0 }}>

      {/* ヘッダー */}
      <div style={{ padding: "10px 12px 8px", borderBottom: "1px solid var(--bd)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
          <span style={{ fontFamily: "var(--ff)", fontSize: 12, fontWeight: 700 }}>
            {isAudio ? "台本編集" : "台本 ＋ ハイライト編集"}
          </span>
          <button onClick={() => dispatch({ type: "ADD_SENT" })} style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>
            ＋ 文追加
          </button>
        </div>
        <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.45 }}>
          {isAudio
            ? "文クリックで選択 → テキスト直接編集 or ✨AI修正 ／ ⏱ タイミング編集"
            : "文クリックで選択 → テキスト直接編集 or ✨AI修正 ／ バッジでHL設定"}
        </div>
      </div>

      {/* 文カード一覧 */}
      <div style={{ flex: 1, overflowY: "auto" }}>
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
              showHl={!isAudio}
            />
          ))
        )}
      </div>
    </aside>
  );
}
