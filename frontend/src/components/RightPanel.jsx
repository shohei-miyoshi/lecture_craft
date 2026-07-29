import SentenceCard from "./SentenceCard.jsx";
import { findHighlightForSentence, getSlideHighlights } from "../utils/highlights.js";
import { getHighlightRegionMeta } from "../utils/highlightPresentation.js";

const REGION_KINDS = ["marker", "arrow", "box"];

function tabStyle(on) {
  return {
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
  };
}

function ReviewInfoCard({ title, body, accent = "var(--ac)" }) {
  return (
    <div style={{ margin: "12px 14px 10px", padding: "10px 12px", borderRadius: 12, background: "rgba(91,141,239,.08)", border: `1px solid ${accent}33` }}>
      <div style={{ fontFamily: "var(--ff)", fontSize: 12, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.7 }}>{body}</div>
    </div>
  );
}

function ReviewStageHeader({ banner, actionLabel, disabled, saving, onAdvance }) {
  if (!banner) return null;
  return (
    <div style={{ flexShrink: 0, padding: "12px 14px", borderBottom: "1px solid rgba(255,255,255,.06)", background: "linear-gradient(180deg, rgba(18,24,37,.92), rgba(18,24,37,.72))" }}>
      <div style={{ fontSize: 9, letterSpacing: "1.4px", textTransform: "uppercase", color: "var(--ac)", marginBottom: 5 }}>
        Review Flow
      </div>
      <div style={{ fontFamily: "var(--ff)", fontSize: 15, lineHeight: 1.15, marginBottom: 6 }}>
        {banner.title}
      </div>
      <div style={{ fontSize: 10, color: "var(--ts)", lineHeight: 1.65, marginBottom: 10 }}>
        {banner.description}
      </div>
      <button
        onClick={onAdvance}
        disabled={disabled}
        style={{
          width: "100%",
          padding: "8px 10px",
          borderRadius: 10,
          border: "1px solid rgba(130,178,255,.42)",
          background: disabled
            ? "linear-gradient(180deg, rgba(53,58,70,.88), rgba(38,42,51,.88))"
            : "linear-gradient(180deg, rgba(122,165,242,.98), rgba(91,141,239,.88))",
          color: disabled ? "var(--tm)" : "#fff",
          fontSize: 11,
          fontWeight: 700,
          opacity: saving ? 0.75 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
      >
        {saving ? "保存中..." : actionLabel}
      </button>
    </div>
  );
}

function LayoutReviewPanel({ state, dispatch, requestConfirm }) {
  const curSlideHighlights = getSlideHighlights(state.hls, state.curSl);
  const selected = curSlideHighlights.find((hl) => hl.id === state.selHl) ?? null;

  const addRegion = () => {
    dispatch({ type: "PUSH_HISTORY" });
    dispatch({
      type: "ADD_HL_BOX",
      slide_idx: state.curSl,
      region: { x: 35, y: 35, w: 18, h: 12 },
      kind: "marker",
    });
  };

  const removeRegion = (highlightId) => {
    requestConfirm?.({
      title: "領域を削除",
      message: "この領域を削除しますか？",
      confirmLabel: "削除する",
      onConfirm: () => {
        dispatch({ type: "PUSH_HISTORY" });
        dispatch({ type: "RM_HL_ID", v: highlightId });
      },
    });
  };

  return (
    <>
      <ReviewInfoCard
        title="領域確認"
        body="右パネルでは領域の一覧と種類変更、削除ができます。プレビュー上では枠の移動・リサイズ、ダブルクリックで新規追加ができます。"
      />
      <div style={{ padding: "0 14px 10px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 11, color: "var(--ts)" }}>スライド {state.curSl + 1} の領域数: {curSlideHighlights.length}</div>
        <button
          onClick={addRegion}
          style={{ padding: "5px 9px", border: "1px solid rgba(91,141,239,.35)", borderRadius: 999, background: "rgba(91,141,239,.12)", color: "var(--tp)", fontSize: 10 }}
        >
          ＋ 領域追加
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "0 14px 14px" }}>
        {curSlideHighlights.length === 0 ? (
          <div style={{ padding: 16, borderRadius: 12, background: "var(--s2)", border: "1px solid var(--bd)", fontSize: 11, color: "var(--tm)", lineHeight: 1.7 }}>
            まだ領域がありません。プレビューをダブルクリックすると未対応の領域を追加できます。
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {curSlideHighlights.map((hl) => {
              const meta = getHighlightRegionMeta(curSlideHighlights, hl.id);
              const selectedRow = state.selHl === hl.id;
              return (
                <div key={hl.id} style={{ padding: 12, borderRadius: 12, background: selectedRow ? "rgba(91,141,239,.10)" : "var(--s2)", border: `1px solid ${selectedRow ? "rgba(91,141,239,.28)" : "var(--bd)"}` }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
                    <button
                      onClick={() => dispatch({ type: "SEL_HL", v: hl.id })}
                      style={{ border: "none", background: "none", color: "inherit", padding: 0, textAlign: "left" }}
                    >
                      <div style={{ fontFamily: "var(--fm)", fontSize: 11, color: meta.color }}>{meta.label}</div>
                      <div style={{ fontSize: 10, color: "var(--tm)", marginTop: 3 }}>
                        x:{Math.round(hl.x)} y:{Math.round(hl.y)} w:{Math.round(hl.w)} h:{Math.round(hl.h)}
                      </div>
                    </button>
                    <button
                      onClick={() => removeRegion(hl.id)}
                      style={{ padding: "4px 8px", borderRadius: 999, border: "1px solid rgba(224,91,91,.3)", background: "rgba(224,91,91,.12)", color: "var(--rd)", fontSize: 10 }}
                    >
                      削除
                    </button>
                  </div>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {REGION_KINDS.map((kind) => {
                      const active = hl.kind === kind;
                      return (
                        <button
                          key={kind}
                          onClick={() => {
                            dispatch({ type: "PUSH_HISTORY" });
                            dispatch({ type: "SET_HL_KIND", id: hl.id, kind });
                          }}
                          style={{
                            padding: "4px 8px",
                            borderRadius: 999,
                            border: `1px solid ${active ? meta.border : "var(--bd2)"}`,
                            background: active ? meta.bgStrong : "var(--s3)",
                            color: active ? "var(--tp)" : "var(--ts)",
                            fontSize: 10,
                          }}
                        >
                          {kind}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      {selected && (
        <div style={{ padding: "10px 14px 14px", borderTop: "1px solid rgba(255,255,255,.05)", fontSize: 10, color: "var(--tm)", lineHeight: 1.7 }}>
          選択中の領域はプレビュー上でドラッグ、端点ドラッグでリサイズできます。
        </div>
      )}
    </>
  );
}

function ScriptReviewPanel({ state, dispatch, addToast, requestConfirm }) {
  const isAudio = state.appMode === "audio";
  const usesHighlights = state.appMode === "hl";
  const isGenerating = state.status === "proc";
  const curSents = isAudio
    ? state.sents
    : state.sents.filter((s) => s.slide_idx === state.curSl);
  const actSent = state.previewActiveSentenceId
    ? state.sents.find((s) => String(s.id) === String(state.previewActiveSentenceId))
    : state.sents.find((s) => s.start_sec <= state.curT && state.curT < s.end_sec);

  return (
    <>
      <ReviewInfoCard
        title="台本確認"
        body={usesHighlights
          ? "この段階では台本だけを調整します。文章の書き換えやタイミング調整に集中し、領域は次の対応確認ステップで扱います。"
          : "この段階で台本を確認します。完了後に確認済み台本の音声を先行生成し、そのまま音声付きプレビューへ進みます。"}
        accent="var(--am)"
      />
      <div style={{ padding: "0 14px 10px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <div style={{ fontSize: 11, color: "var(--ts)" }}>
          {isAudio ? `全文 ${state.sents.length} 文` : `スライド ${state.curSl + 1} の台本 ${curSents.length} 文`}
        </div>
        <button
          onClick={() => {
            if (isGenerating) return;
            dispatch({ type: "PUSH_HISTORY" });
            dispatch({ type: "ADD_SENT" });
          }}
          disabled={isGenerating}
          style={{ padding: "5px 9px", border: "1px solid rgba(167,139,250,.35)", borderRadius: 999, background: "rgba(167,139,250,.12)", color: "var(--tp)", fontSize: 10, opacity: isGenerating ? 0.55 : 1, cursor: isGenerating ? "not-allowed" : "pointer" }}
        >
          ＋ 文追加
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", paddingBottom: 12 }}>
        {isGenerating ? (
          <div style={{ margin: "0 14px", padding: 16, borderRadius: 12, background: "var(--amd)", border: "1px solid rgba(232,169,75,.28)", fontSize: 11, color: "var(--am)", lineHeight: 1.7 }}>
            台本生成中は台本編集を一時停止しています。生成完了後に確認してください。
          </div>
        ) : curSents.length === 0 ? (
          <div style={{ margin: "0 14px", padding: 16, borderRadius: 12, background: "var(--s2)", border: "1px solid var(--bd)", fontSize: 11, color: "var(--tm)", lineHeight: 1.7 }}>
            このスライドには台本がありません。必要なら文を追加してください。
          </div>
        ) : (
          curSents.map((s, i) => (
            <SentenceCard
              key={s.id}
              sent={s}
              idx={i}
              hl={findHighlightForSentence(state.hls, s.id)}
              slideHighlights={[]}
              isSel={s.id === state.selSent}
              isPlay={!!(actSent && actSent.id === s.id)}
              drawMode={false}
              drawSentId={null}
              drawKind={state.drawKind}
              dispatch={dispatch}
              addToast={addToast}
              requestConfirm={requestConfirm}
              slide={state.slides[s.slide_idx]}
              showHl={false}
            />
          ))
        )}
      </div>
    </>
  );
}

function LayoutWaitingScriptPanel({ state }) {
  const curSlideHighlights = getSlideHighlights(state.hls, state.curSl);
  return (
    <>
      <ReviewInfoCard
        title="領域確認済み"
        body="領域の確認結果は保持されています。台本生成が完了するまで、この状態のまま待機します。ページをリロードせずにそのまま待ってください。"
        accent="var(--am)"
      />
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "0 14px 14px" }}>
        <div style={{ padding: 14, borderRadius: 12, background: "var(--amd)", border: "1px solid rgba(232,169,75,.28)", color: "var(--am)", fontSize: 11, lineHeight: 1.8, marginBottom: 12 }}>
          台本生成中です。生成が終わると自動で次の確認ステップへ進みます。
        </div>
        <div style={{ fontSize: 11, color: "var(--ts)", marginBottom: 10 }}>
          スライド {state.curSl + 1} の確認済み領域: {curSlideHighlights.length}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {curSlideHighlights.map((hl) => {
            const meta = getHighlightRegionMeta(curSlideHighlights, hl.id);
            return (
              <div key={hl.id} style={{ padding: 10, borderRadius: 12, background: "var(--s2)", border: "1px solid var(--bd)" }}>
                <div style={{ fontFamily: "var(--fm)", fontSize: 11, color: meta.color }}>{meta.label}</div>
                <div style={{ fontSize: 10, color: "var(--tm)", marginTop: 4 }}>
                  x:{Math.round(hl.x)} y:{Math.round(hl.y)} w:{Math.round(hl.w)} h:{Math.round(hl.h)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

export default function RightPanel({
  state,
  dispatch,
  addToast,
  requestConfirm,
  tab,
  setTab,
  rightContent,
  reviewStage = "editor",
  reviewBanner = null,
  reviewActionLabel = "",
  reviewActionDisabled = false,
  reviewSavingStage = null,
  onAdvanceReview = null,
  onPlaySentence = null,
}) {
  const isAudio = state.appMode === "audio";
  const usesHighlights = state.appMode === "hl";
  const curSents = isAudio
    ? state.sents
    : state.sents.filter((s) => s.slide_idx === state.curSl);
  const curSlideHighlights = getSlideHighlights(state.hls, state.curSl);
  const actSent = state.previewActiveSentenceId
    ? state.sents.find((s) => String(s.id) === String(state.previewActiveSentenceId))
    : state.sents.find((s) => s.start_sec <= state.curT && state.curT < s.end_sec);
  const reviewActive = reviewStage !== "editor";
  const showCombinedEditor = reviewStage === "assignment" || reviewStage === "editor";
  const editorLockedByGeneration = state.status === "proc" && reviewStage === "editor";

  return (
    <aside style={{ display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0, background: "linear-gradient(180deg, rgba(19,21,26,.92), rgba(19,21,26,.82))", borderLeft: "1px solid rgba(255,255,255,.05)", minHeight: 0, position: "relative", width: "100%", height: "100%" }}>
      <div style={{ position: "absolute", top: 0, right: 0, width: 90, height: 16, background: "linear-gradient(270deg, rgba(110,193,255,.22), transparent)", pointerEvents: "none" }} />

      {!reviewActive && (
        <div style={{ display: "flex", alignItems: "flex-end", borderBottom: "1px solid rgba(255,255,255,.05)", background: "transparent", flexShrink: 0, padding: "6px 8px 0 8px", gap: 4 }}>
          <button onClick={() => setTab("editor")} style={tabStyle(tab === "editor")}>エディタ</button>
          <button onClick={() => setTab("export")} style={tabStyle(tab === "export")}>書き出し</button>
        </div>
      )}

      {reviewActive && (
        <ReviewStageHeader
          banner={reviewBanner}
          actionLabel={reviewActionLabel}
          disabled={reviewActionDisabled}
          saving={Boolean(reviewSavingStage)}
          onAdvance={onAdvanceReview}
        />
      )}

      {reviewStage === "layout" && (
        <LayoutReviewPanel state={state} dispatch={dispatch} requestConfirm={requestConfirm} />
      )}

      {reviewStage === "layout_waiting_script" && (
        <LayoutWaitingScriptPanel state={state} />
      )}

      {reviewStage === "script" && (
        <ScriptReviewPanel
          state={state}
          dispatch={dispatch}
          addToast={addToast}
          requestConfirm={requestConfirm}
        />
      )}

      {reviewStage === "assignment_generating" && (
        <>
          <ReviewInfoCard
            title="対応付け生成中"
            body="確認済みの領域と台本をバックエンドへ送り、台本と領域の対応関係を生成しています。完了すると対応確認ステップへ進みます。"
            accent="var(--am)"
          />
          <div style={{ padding: 14, color: "var(--tm)", fontSize: 11, lineHeight: 1.8 }}>
            この処理が終わるまで、領域と台本の編集結果は画面上に保持されます。ページをリロードせずにそのまま待ってください。
          </div>
        </>
      )}

      {showCombinedEditor && (tab === "editor" || reviewStage === "assignment") && (
        <>
          {reviewStage === "assignment" ? (
            <ReviewInfoCard
              title="対応確認"
              body="領域確認ステップで確定した枠を基準に、台本との対応だけを確認します。必要に応じて文と既存領域の紐付けを調整してください。"
              accent="var(--gr)"
            />
          ) : (
            <div style={{ padding: "12px 14px 10px", borderBottom: "1px solid rgba(255,255,255,.05)", flexShrink: 0, background: "linear-gradient(180deg, rgba(255,255,255,.02), transparent)" }}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
                <span style={{ fontFamily: "var(--ff)", fontSize: 12, fontWeight: 700, lineHeight: 1.4 }}>
                  {usesHighlights ? "台本 ＋ ハイライト編集" : "台本編集"}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <button
                    onClick={() => {
                      if (editorLockedByGeneration) return;
                      dispatch({ type: "PUSH_HISTORY" });
                      dispatch({ type: "ADD_SENT" });
                    }}
                    disabled={editorLockedByGeneration}
                    style={{ display: "inline-flex", alignItems: "center", gap: 3, padding: "3px 6px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10, whiteSpace: "nowrap", opacity: editorLockedByGeneration ? 0.55 : 1, cursor: editorLockedByGeneration ? "not-allowed" : "pointer" }}
                  >
                    ＋ 文追加
                  </button>
                </div>
              </div>
              <div style={{ fontSize: 10, color: "var(--tm)", lineHeight: 1.55 }}>
                {!usesHighlights
                  ? "文クリックでその位置から再生・選択 → テキスト直接編集 or ✨AI修正 ／ ⏱ タイミング編集"
                  : "文クリックでその位置から再生・選択 → テキスト直接編集 or ✨AI修正 ／ 左帯で状態確認・HL設定"}
              </div>
            </div>
          )}

          <div style={{ flex: 1, minHeight: 0, overflowY: "auto", scrollbarGutter: "stable", overscrollBehavior: "contain", background: "linear-gradient(180deg, rgba(255,255,255,.01), transparent 14%)", paddingBottom: 12 }}>
            {editorLockedByGeneration ? (
              <div style={{ margin: 14, padding: 16, borderRadius: 12, background: "var(--amd)", border: "1px solid rgba(232,169,75,.28)", fontSize: 11, color: "var(--am)", lineHeight: 1.8 }}>
                生成中は通常エディタを一時停止しています。領域確認が表示された場合はそのまま確認できます。台本編集や追加は生成完了後に行ってください。
              </div>
            ) : curSents.length === 0 ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 28, color: "var(--tm)", fontSize: 11, gap: 5, textAlign: "center" }}>
                <div style={{ fontSize: 24, opacity: 0.4 }}>📝</div>
                <p>{state.generated ? (isAudio ? "台本なし" : "このスライドに台本なし") : "まだ台本がありません。必要なら文を追加してください。"}</p>
              </div>
            ) : (
              curSents.map((s, i) => (
                <SentenceCard
                  key={s.id}
                  sent={s}
                  idx={i}
                  hl={findHighlightForSentence(state.hls, s.id)}
                  slideHighlights={curSlideHighlights}
                  isSel={s.id === state.selSent}
                  isPlay={!!(actSent && actSent.id === s.id)}
                  drawMode={state.drawMode}
                  drawSentId={state.drawSentId}
                  drawKind={state.drawKind}
                  dispatch={dispatch}
                  addToast={addToast}
                  requestConfirm={requestConfirm}
                  slide={state.slides[s.slide_idx]}
                  showHl={usesHighlights}
                  highlightLinkOnly={reviewStage === "assignment"}
                  playOnSelect={reviewStage === "editor"}
                  onPlaySentence={onPlaySentence}
                />
              ))
            )}
          </div>
        </>
      )}

      {!reviewActive && tab === "export" && rightContent}
    </aside>
  );
}
