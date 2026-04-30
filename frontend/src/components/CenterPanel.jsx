import { useState } from "react";
import SlideCanvas from "./SlideCanvas.jsx";
import AudioView   from "./AudioView.jsx";
import Playbar     from "./Playbar.jsx";
import { usePlayback } from "../hooks/usePlayback.js";
import { usePreviewAudio } from "../hooks/usePreviewAudio.js";

/**
 * 中央パネル
 * - HLありモード（appMode==="hl"）のときのみ HL/plain 切替を表示
 * - タブ（エディタ/書き出し）は右パネル側に移動したため、ここでは持たない
 */
export default function CenterPanel({ state, dispatch, addToast, requestConfirm }) {
  const {
    audioRef,
    togglePlayback,
    previewAudio,
    previewAudioReady,
    previewAudioStale,
    beginPreviewScrub,
    seekPreview,
    endPreviewScrub,
  } = usePreviewAudio(state, dispatch, addToast);
  usePlayback(state, dispatch, {
    enabled: !state.generated || !state.sents.length || (!previewAudioReady && previewAudio.status !== "loading"),
  });
  const [helpOpen, setHelpOpen] = useState(false);

  const isAudio = state.appMode === "audio";
  const isHl    = state.appMode === "hl";
  const showPreviewAudioBadge = state.generated && state.sents.length > 0;
  const previewAudioBadge = previewAudio.status === "loading"
    ? { label: "音声準備中", color: "var(--am)", background: "rgba(232,169,75,.12)", border: "rgba(232,169,75,.3)" }
    : previewAudioStale
      ? { label: "音声更新待ち", color: "var(--rd)", background: "rgba(224,91,91,.12)", border: "rgba(224,91,91,.28)" }
      : previewAudioReady
        ? { label: "音声同期済み", color: "var(--gr)", background: "rgba(86,190,126,.12)", border: "rgba(86,190,126,.28)" }
        : previewAudio.status === "error"
          ? { label: "音声エラー", color: "var(--rd)", background: "rgba(224,91,91,.12)", border: "rgba(224,91,91,.28)" }
          : { label: "音声未準備", color: "var(--tm)", background: "rgba(255,255,255,.04)", border: "rgba(255,255,255,.08)" };

  return (
    <main style={{ flex: 1, display: "flex", flexDirection: "column", background: "transparent", minWidth: 0, overflow: "hidden", position: "relative" }}>
      <audio ref={audioRef} preload="auto" style={{ display: "none" }} />

      {/* ── ツールバー ── */}
      <div
        style={{
          minHeight: 46,
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 14px",
          background: "linear-gradient(180deg, rgba(19,21,26,.88), rgba(19,21,26,.74))",
          borderBottom: "1px solid rgba(255,255,255,.04)",
          flexShrink: 0,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.4px", textTransform: "uppercase", color: "var(--tm)", padding: "4px 8px", background: "rgba(255,255,255,.03)", borderLeft: "2px solid var(--ac)" }}>Preview</span>

        {isAudio ? (
          <span style={{ fontSize: 10, color: "var(--am)", background: "var(--amd)", border: "1px solid rgba(232,169,75,.3)", padding: "4px 8px", marginLeft: 4 }}>
            🔊 音声のみ
          </span>
        ) : (
          <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", marginLeft: 4, padding: "4px 8px", background: "rgba(255,255,255,.03)" }}>
            {state.slides.length ? `${state.curSl + 1} / ${state.slides.length}` : "— / —"}
          </span>
        )}

        {showPreviewAudioBadge && (
          <span
            title={previewAudio.error || "プレビュー音声の状態"}
            style={{
              fontFamily: "var(--fm)",
              fontSize: 9,
              color: previewAudioBadge.color,
              marginLeft: 2,
              padding: "4px 8px",
              background: previewAudioBadge.background,
              border: `1px solid ${previewAudioBadge.border}`,
              borderRadius: 999,
            }}
          >
            {previewAudioBadge.label}
          </span>
        )}

        <button
          onClick={() => setHelpOpen(true)}
          style={{
            marginLeft: isHl ? "auto" : 10,
            padding: "5px 12px",
            borderRadius: 999,
            border: "1px solid rgba(110,193,255,.24)",
            background: "rgba(91,141,239,.08)",
            color: "var(--tp)",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: ".02em",
          }}
        >
          操作方法
        </button>

        {/* HL / 動画 切替 — HLありモード(appMode==="hl")のときだけ表示 */}
        {isHl && (
          <div style={{ display: "flex", gap: 3 }}>
            {[["hl", "🎬 HL表示"], ["plain", "📹 動画"]].map(([v, l]) => (
              <button key={v} onClick={() => dispatch({ type: "SET", k: "prevMode", v })} style={{
                padding: "3px 9px", border: "1px solid var(--bd2)", borderRadius: 20,
                background:  state.prevMode === v ? "var(--adim)" : "none",
                color:       state.prevMode === v ? "var(--ac)"   : "var(--ts)",
                borderColor: state.prevMode === v ? "var(--ac)"   : "var(--bd2)",
                fontSize: 10,
              }}>{l}</button>
            ))}
          </div>
        )}
      </div>

      {/* ── 描画モードヒントバー ── */}
      {!isAudio && (
        <div style={{
          height: state.drawMode ? 30 : 0, overflow: "hidden",
          background: "rgba(232,169,75,.1)",
          borderBottom: state.drawMode ? "1px solid rgba(232,169,75,.22)" : "none",
          display: "flex", alignItems: "center", justifyContent: "center",
          gap: 8, fontSize: 11, color: "var(--am)",
          transition: "height .2s", flexShrink: 0,
        }}>
          ✏ ドラッグして領域を描く &nbsp;
          <kbd style={{ background: "var(--s3)", padding: "1px 5px", borderRadius: 3, fontSize: 9 }}>Esc</kbd>
          &nbsp; でキャンセル
        </div>
      )}

      {/* ── メインビュー ── */}
      {isAudio ? (
        <AudioView state={state} />
      ) : (
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 18,
            overflow: "hidden",
            position: "relative",
            background:
              "linear-gradient(180deg, rgba(255,255,255,.015), transparent 16%), radial-gradient(circle at 50% 20%, rgba(91,141,239,.08), transparent 36%)",
          }}
        >
          <SlideCanvas state={state} dispatch={dispatch} addToast={addToast} requestConfirm={requestConfirm} />
        </div>
      )}

      {/* ── 再生バー ── */}
      <Playbar
        state={state}
        dispatch={dispatch}
        hideSlideNav={isAudio}
        onTogglePlay={togglePlayback}
        playbackBusy={previewAudio.status === "loading"}
        onSeekStart={beginPreviewScrub}
        onSeekPreview={seekPreview}
        onSeekEnd={endPreviewScrub}
      />

      {helpOpen && (
        <div
          onClick={() => setHelpOpen(false)}
          style={{
            position: "absolute",
            inset: 0,
            background: "rgba(7,8,11,.68)",
            display: "grid",
            placeItems: "center",
            zIndex: 30,
            padding: 22,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(720px, 100%)",
              maxHeight: "min(82vh, 760px)",
              overflow: "auto",
              padding: "18px 18px 16px",
              borderRadius: 24,
              border: "1px solid rgba(110,193,255,.18)",
              background: "linear-gradient(180deg, rgba(19,21,26,.98), rgba(15,16,20,.94))",
              boxShadow: "0 26px 60px rgba(0,0,0,.38)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", gap: 16, alignItems: "flex-start", marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 10, letterSpacing: "1.5px", textTransform: "uppercase", color: "var(--ac)", marginBottom: 6 }}>
                  操作ガイド
                </div>
                <div style={{ fontFamily: "var(--ff)", fontSize: 24, lineHeight: 1.1 }}>
                  編集画面の操作方法
                </div>
              </div>
              <button
                onClick={() => setHelpOpen(false)}
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: "50%",
                  border: "1px solid rgba(255,255,255,.08)",
                  background: "rgba(255,255,255,.04)",
                  color: "var(--tp)",
                  fontSize: 16,
                  lineHeight: 1,
                }}
              >
                ×
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
              {[
                {
                  title: "編集のやり直し",
                  items: [
                    ["Cmd/Ctrl + Z", "1つ戻す"],
                    ["Cmd/Ctrl + Shift + Z", "1つ進める"],
                    ["Cmd/Ctrl + Y", "1つ進める"],
                    ["マウスのサイドボタン", "戻す / 進める"],
                  ],
                },
                {
                  title: "スライド移動",
                  items: [
                    ["Enter / Space / → / ↓", "次のスライドへ"],
                    ["Backspace / ← / ↑", "前のスライドへ"],
                    ["PageDown / N", "次のスライドへ"],
                    ["PageUp / P", "前のスライドへ"],
                    ["Home / End", "最初 / 最後のスライドへ"],
                  ],
                },
                {
                  title: "再生",
                  items: [
                    ["F5", "先頭スライドから再生"],
                    ["Shift + F5", "現在スライドから再生"],
                    ["Esc", "再生停止 / 描画キャンセル"],
                  ],
                },
                {
                  title: "プレビュー操作",
                  items: [
                    ["ホイール", "スライドを切り替える"],
                    ["Cmd/Ctrl + ホイール", "拡大 / 縮小"],
                    ["ドラッグ", "拡大時に表示位置を動かす"],
                    ["ダブルクリック", "選択中の台本に枠を追加"],
                  ],
                },
              ].map((section) => (
                <section
                  key={section.title}
                  style={{
                    padding: "14px 14px 12px",
                    borderRadius: 18,
                    background: "linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.015))",
                    border: "1px solid rgba(255,255,255,.05)",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700, color: "var(--tp)", marginBottom: 10 }}>
                    {section.title}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {section.items.map(([key, text]) => (
                      <div key={`${section.title}-${key}`} style={{ display: "grid", gridTemplateColumns: "minmax(0, 120px) 1fr", gap: 10, alignItems: "start" }}>
                        <div style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--ac)", lineHeight: 1.5 }}>
                          {key}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.65 }}>
                          {text}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
