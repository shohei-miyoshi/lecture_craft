import { API_URL, DETAIL_VALS, DIFF_VALS } from "../utils/constants.js";
import { fmt } from "../utils/helpers.js";

const EXPORT_ROWS = [
  ["🎬 ハイライトあり動画", "video_highlight", ".mp4"],
  ["📹 動画（HL無し）",     "video",           ".mp4"],
  ["🔊 音声のみ",           "audio",           ".mp3"],
  ["🗂 編集データ",         "json",            ".json"],
  ["📄 台本テキスト",       "script",          ".txt"],
  ["🧾 操作ログ",           "log",             ".json"],
];

/**
 * 書き出しパネル
 * JSON / テキストはフロントエンドのみで生成
 * 動画 / 音声はバックエンドに委譲
 */
export default function ExportPanel({ state, dispatch, addToast }) {

  const doExport = async (type) => {
    if (!state.generated) { addToast("er", "先に生成してください"); return; }

    // ── JSON エクスポート（フロントのみ） ──
    if (type === "json") {
      const data = {
        slides:     state.slides.map((s) => ({ id: s.id, title: s.title })),
        sentences:  state.sents,
        highlights: state.hls,
        settings:   { detail: state.detail, level: state.level, mode: state.appMode },
        operation_logs: state.opLogs,
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "lecture_data.json"; a.click();
      dispatch({ type: "APP_LOG", message: "編集データ(JSON)をエクスポートしました", meta: { type: "export_json" } });
      addToast("ok", "📦 JSONをエクスポートしました");
      return;
    }

    // ── 操作ログ（フロントのみ） ──
    if (type === "log") {
      const data = {
        exported_at: new Date().toISOString(),
        mode: state.appMode,
        counts: {
          slides: state.slides.length,
          sentences: state.sents.length,
          highlights: state.hls.length,
          logs: state.opLogs.length,
        },
        operation_logs: state.opLogs,
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "operation_log.json"; a.click();
      dispatch({ type: "APP_LOG", message: `操作ログをエクスポートしました（logs=${state.opLogs.length}）`, meta: { type: "export_log", count: state.opLogs.length } });
      addToast("ok", "🧾 操作ログをエクスポートしました");
      return;
    }

    // ── 台本テキスト（フロントのみ） ──
    if (type === "script") {
      const txt = state.sents.map((s) => `[${fmt(s.start_sec)}-${fmt(s.end_sec)}] ${s.text}`).join("\n");
      const blob = new Blob([txt], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "lecture_script.txt"; a.click();
      dispatch({ type: "APP_LOG", message: "台本テキストをエクスポートしました", meta: { type: "export_script" } });
      addToast("ok", "📄 台本をエクスポートしました");
      return;
    }

    // ── 動画 / 音声（バックエンド） ──
    addToast("in", "⏳ 生成中...");
    dispatch({ type: "APP_LOG", message: `メディア書き出しを開始しました（type=${type}）`, meta: { type: "export_start", export_type: type } });
    try {
      const res = await fetch(`${API_URL}/api/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type,
          mode: state.appMode,
          slides: state.slides,
          sentences: state.sents,
          highlights: state.hls,
          settings: {
            detail: DETAIL_VALS[state.detail],
            difficulty: DIFF_VALS[state.level],
          },
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const ext  = type.includes("audio") ? "mp3" : "mp4";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = `lecture.${ext}`; a.click();
      dispatch({ type: "APP_LOG", message: `メディア書き出しが完了しました（type=${type}, ext=${ext}）`, meta: { type: "export_success", export_type: type, ext } });
      addToast("ok", "✅ エクスポート完了");
    } catch (err) {
      dispatch({ type: "APP_LOG", message: `メディア書き出しに失敗しました（type=${type}, reason=${err.message ?? "unknown"}）`, meta: { type: "export_error", export_type: type, reason: err.message ?? "unknown" } });
      addToast("er", "バックエンド未接続。JSON / テキストのみ利用可能です。");
    }
  };

  return (
    <aside style={{ width: 380, background: "var(--sur)", borderLeft: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0 }}>
      <div style={{ padding: 12 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 10 }}>書き出し</div>
        <div style={{ padding: "8px 10px", marginBottom: 8, background: "var(--s2)", border: "1px solid var(--bd)", borderRadius: "var(--r)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: "var(--ts)" }}>操作ログ</span>
            <span style={{ fontFamily: "var(--fm)", fontSize: 9, color: "var(--ac)" }}>{state.opLogs.length}件</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 88, overflowY: "auto" }}>
            {state.opLogs.length === 0 ? (
              <span style={{ fontSize: 10, color: "var(--tm)" }}>まだログはありません</span>
            ) : (
              state.opLogs.slice(-4).reverse().map((log) => (
                <div key={log.id} style={{ fontSize: 9, color: "var(--tm)", lineHeight: 1.45 }}>
                  <div style={{ fontFamily: "var(--fm)", color: "var(--ac)" }}>{new Date(log.at).toLocaleTimeString("ja-JP", { hour12: false })}</div>
                  <div style={{ color: "var(--ts)" }}>{log.message}</div>
                </div>
              ))
            )}
          </div>
        </div>
        {EXPORT_ROWS.map(([nm, tp, ext]) => (
          <div
            key={tp}
            onClick={() => doExport(tp)}
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "9px 11px", border: "1px solid var(--bd)", borderRadius: "var(--r)", marginBottom: 5, cursor: "pointer", transition: "var(--tr)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--s2)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "")}
          >
            <div>
              <div style={{ fontSize: 12, fontWeight: 500 }}>{nm}</div>
              <div style={{ fontSize: 9, color: "var(--tm)" }}>{ext}</div>
            </div>
            <span>↓</span>
          </div>
        ))}
      </div>
    </aside>
  );
}
