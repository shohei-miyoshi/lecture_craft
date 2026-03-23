import { useState } from "react";
import Seg from "./Seg.jsx";
import { DETAIL_LABELS, DIFF_LABELS, DETAIL_VALS, DIFF_VALS, API_URL } from "../utils/constants.js";
import { toB64, makeDemo } from "../utils/helpers.js";

/**
 * 左パネル
 * - PDFアップロード（クリック / ドラッグ＆ドロップ）
 * - 学習者要求3軸の設定
 * - 講義メディア生成ボタン
 * - 進捗ステータス
 * - スライド一覧
 */
export default function LeftPanel({ state, dispatch, pdfFile, setPdfFile, addToast }) {
  const [drag, setDrag] = useState(false);

  const handleFile = (f) => {
    if (!f || f.type !== "application/pdf") return;
    setPdfFile(f);
    addToast("in", `📑 ${f.name}`);
  };

  const startGen = async () => {
    if (!pdfFile) { addToast("er", "PDFをアップロードしてください"); return; }
    dispatch({ type: "SET", k: "status",    v: "proc"           });
    dispatch({ type: "SET", k: "statusMsg", v: "スライドを解析中..." });
    dispatch({ type: "SET", k: "showProg",  v: true             });
    dispatch({ type: "SET", k: "progress",  v: 10               });
    try {
      const b64 = await toB64(pdfFile);
      dispatch({ type: "SET", k: "progress",  v: 30        });
      dispatch({ type: "SET", k: "statusMsg", v: "台本を生成中..." });
      const res = await fetch(`${API_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          pdf_base64:  b64,
          filename:    pdfFile.name,
          detail:      DETAIL_VALS[state.detail],
          difficulty:  DIFF_VALS[state.level],
          mode:        state.appMode,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      dispatch({ type: "SET", k: "progress",  v: 85             });
      dispatch({ type: "SET", k: "statusMsg", v: "データを読み込み中..." });
      dispatch({ type: "LOAD", d: await res.json() });
      dispatch({ type: "SET", k: "progress",  v: 100   });
      dispatch({ type: "SET", k: "status",    v: "done" });
      dispatch({ type: "SET", k: "statusMsg", v: "生成完了" });
      addToast("ok", "✅ 講義メディアを生成しました");
    } catch (err) {
      console.warn("Backend unavailable, using demo data:", err.message);
      dispatch({ type: "SET", k: "progress",  v: 60            });
      dispatch({ type: "SET", k: "statusMsg", v: "デモデータを準備中..." });
      await new Promise((r) => setTimeout(r, 300));
      dispatch({ type: "LOAD", d: makeDemo() });
      dispatch({ type: "SET", k: "progress",  v: 100              });
      dispatch({ type: "SET", k: "status",    v: "done"            });
      dispatch({ type: "SET", k: "statusMsg", v: "生成完了（デモ）" });
      addToast("in", "🔧 バックエンド未接続 — デモデータで表示");
    }
    setTimeout(() => dispatch({ type: "SET", k: "showProg", v: false }), 800);
  };

  const statusStyle = {
    idle: { background: "var(--s2)",  color: "var(--tm)" },
    proc: { background: "var(--amd)", border: "1px solid rgba(232,169,75,.28)", color: "var(--am)" },
    done: { background: "var(--gd)",  border: "1px solid rgba(76,175,130,.28)",  color: "var(--gr)" },
    err:  { background: "var(--rdd)", border: "1px solid rgba(224,91,91,.28)",   color: "var(--rd)" },
  }[state.status];

  return (
    <aside style={{ width: 250, minWidth: 210, background: "var(--sur)", borderRight: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0 }}>
      <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>

        {/* ─── アップロード ─── */}
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>入力スライド</div>
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true);  }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e)    => { e.preventDefault(); setDrag(false); handleFile(e.dataTransfer.files[0]); }}
          style={{ border: `2px dashed ${drag ? "var(--ac)" : "var(--bd2)"}`, borderRadius: "var(--rl)", padding: "14px 10px", textAlign: "center", cursor: "pointer", transition: "var(--tr)", position: "relative", marginBottom: 8, background: drag ? "var(--adim)" : "none" }}
        >
          <input type="file" accept=".pdf" onChange={(e) => handleFile(e.target.files[0])} style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }} />
          <div style={{ fontSize: 20, marginBottom: 4 }}>📑</div>
          <p style={{ fontSize: 11, color: "var(--ts)", lineHeight: 1.45 }}>
            <strong style={{ color: "var(--ac)" }}>クリック or ドロップ</strong><br />PDFを選択
          </p>
          <small style={{ fontSize: 9, color: "var(--tm)" }}>PDF / max 50MB</small>
        </div>

        {pdfFile && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 8px", background: "var(--gd)", border: "1px solid var(--gr)", borderRadius: "var(--r)", marginBottom: 8 }}>
            <span>✅</span>
            <span style={{ fontFamily: "var(--fm)", fontSize: 10, color: "var(--gr)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{pdfFile.name}</span>
            <button onClick={() => setPdfFile(null)} style={{ padding: "1px 5px", border: "1px solid var(--bd2)", borderRadius: "var(--r)", background: "var(--s2)", color: "var(--tp)", fontSize: 10 }}>×</button>
          </div>
        )}

        {/* ─── 学習者要求3軸 ─── */}
        <div style={{ height: 12 }} />
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>学習者要求</div>

        {[
          ["詳細度", "detail", DETAIL_LABELS, ["要約", "標準", "精緻"]],
          ["難易度", "level",  DIFF_LABELS,   ["入門", "基礎", "発展"]],
        ].map(([lbl, key, fullLabels, shortLabels]) => (
          <div key={key} style={{ marginBottom: 10 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
              <span style={{ fontSize: 11, color: "var(--ts)" }}>{lbl}</span>
              <span style={{ fontFamily: "var(--fm)", fontSize: 9, padding: "1px 5px", borderRadius: 20, background: "var(--adim)", color: "var(--ac)", border: "1px solid rgba(91,141,239,.22)" }}>
                {fullLabels[state[key]]}
              </span>
            </div>
            <Seg
              opts={shortLabels.map((l, i) => ({ v: i, l }))}
              val={state[key]}
              onChange={(v) => dispatch({ type: "SET", k: key, v })}
            />
          </div>
        ))}

        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: "var(--ts)" }}>提示形態</span>
            <span style={{ fontFamily: "var(--fm)", fontSize: 9, padding: "1px 5px", borderRadius: 20, background: "var(--adim)", color: "var(--ac)", border: "1px solid rgba(91,141,239,.22)" }}>
              {{ audio: "音声", video: "動画", hl: "HL動画" }[state.appMode]}
            </span>
          </div>
          <Seg
            opts={[{ v: "audio", l: "音声" }, { v: "video", l: "動画" }, { v: "hl", l: "HL動画" }]}
            val={state.appMode}
            onChange={(v) => dispatch({ type: "SET", k: "appMode", v })}
          />
        </div>

        {/* ─── 生成ボタン ─── */}
        <button onClick={startGen} style={{ width: "100%", padding: 9, background: "var(--ac)", border: "none", borderRadius: "var(--r)", color: "#fff", fontFamily: "var(--fb)", fontSize: 12, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 5, marginBottom: 10 }}>
          ⚡ 講義メディア生成
        </button>

        {/* ─── ステータス ─── */}
        <div style={{ ...statusStyle, padding: "6px 8px", borderRadius: "var(--r)", fontSize: 10, display: "flex", alignItems: "center", gap: 5, marginBottom: 4 }}>
          {state.status === "proc" && (
            <div style={{ width: 9, height: 9, border: "1.5px solid rgba(232,169,75,.22)", borderTopColor: "var(--am)", borderRadius: "50%", animation: "lc-spin .8s linear infinite", flexShrink: 0 }} />
          )}
          <span>{{ idle: "⏸ ", done: "✅ ", err: "❌ ", proc: "" }[state.status]}{state.statusMsg}</span>
        </div>
        {state.showProg && (
          <div style={{ height: 2, background: "var(--s2)", borderRadius: 1, overflow: "hidden", marginTop: 3 }}>
            <div style={{ height: "100%", background: "var(--ac)", width: state.progress + "%", transition: "width .3s ease" }} />
          </div>
        )}

        {/* ─── スライド一覧 ─── */}
        <div style={{ height: 10 }} />
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 8 }}>スライド一覧</div>

        {state.slides.length === 0 ? (
          <div style={{ color: "var(--tm)", fontSize: 10, textAlign: "center", padding: "10px 0" }}>生成後に表示</div>
        ) : (
          state.slides.map((sl, i) => {
            const ct = state.hls.filter((h) => h.slide_idx === i).length;
            return (
              <div key={sl.id} onClick={() => dispatch({ type: "SET_SL", v: i })} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 7px", borderRadius: "var(--r)", border: `1px solid ${i === state.curSl ? "var(--ac)" : "var(--bd)"}`, cursor: "pointer", background: i === state.curSl ? "var(--adim)" : "var(--s2)", marginBottom: 3 }}>
                <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--tm)", width: 15, textAlign: "right", flexShrink: 0 }}>{i + 1}</span>
                <div style={{ width: 36, height: 22, background: sl.color ?? "var(--s3)", borderRadius: 3, overflow: "hidden", flexShrink: 0, display: "grid", placeItems: "center", fontSize: 9, color: "var(--tm)" }}>
                  {sl.image_base64 ? <img src={`data:image/png;base64,${sl.image_base64}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} alt="" /> : "🖼"}
                </div>
                <span style={{ fontSize: 10, color: "var(--ts)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{sl.title}</span>
                {ct > 0 && <span style={{ fontFamily: "var(--fm)", fontSize: 9, padding: "1px 4px", borderRadius: 7, background: "var(--adim)", color: "var(--ac)", flexShrink: 0 }}>{ct}</span>}
              </div>
            );
          })
        )}
      </div>
    </aside>
  );
}
