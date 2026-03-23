import { API_URL } from "../utils/constants.js";
import { fmt } from "../utils/helpers.js";

const EXPORT_ROWS = [
  ["🎬 ハイライトあり動画", "video_highlight", ".mp4"],
  ["📹 動画（HL無し）",     "video",           ".mp4"],
  ["🔊 音声のみ",           "audio",           ".mp3"],
  ["🗂 編集データ",         "json",            ".json"],
  ["📄 台本テキスト",       "script",          ".txt"],
];

/**
 * 書き出しパネル
 * JSON / テキストはフロントエンドのみで生成
 * 動画 / 音声はバックエンドに委譲
 */
export default function ExportPanel({ state, addToast }) {

  const doExport = async (type) => {
    if (!state.generated) { addToast("er", "先に生成してください"); return; }

    // ── JSON エクスポート（フロントのみ） ──
    if (type === "json") {
      const data = {
        slides:     state.slides.map((s) => ({ id: s.id, title: s.title })),
        sentences:  state.sents,
        highlights: state.hls,
        settings:   { detail: state.detail, level: state.level, mode: state.appMode },
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "lecture_data.json"; a.click();
      addToast("ok", "📦 JSONをエクスポートしました");
      return;
    }

    // ── 台本テキスト（フロントのみ） ──
    if (type === "script") {
      const txt = state.sents.map((s) => `[${fmt(s.start_sec)}-${fmt(s.end_sec)}] ${s.text}`).join("\n");
      const blob = new Blob([txt], { type: "text/plain;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = "lecture_script.txt"; a.click();
      addToast("ok", "📄 台本をエクスポートしました");
      return;
    }

    // ── 動画 / 音声（バックエンド） ──
    addToast("in", "⏳ 生成中...");
    try {
      const res = await fetch(`${API_URL}/api/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, sentences: state.sents, highlights: state.hls }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const ext  = type.includes("audio") ? "mp3" : "mp4";
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = `lecture.${ext}`; a.click();
      addToast("ok", "✅ エクスポート完了");
    } catch {
      addToast("er", "バックエンド未接続。JSON / テキストのみ利用可能です。");
    }
  };

  return (
    <aside style={{ width: 380, background: "var(--sur)", borderLeft: "1px solid var(--bd)", display: "flex", flexDirection: "column", overflow: "hidden", flexShrink: 0 }}>
      <div style={{ padding: 12 }}>
        <div style={{ fontFamily: "var(--ff)", fontSize: 9, fontWeight: 700, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--tm)", marginBottom: 10 }}>書き出し</div>
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
