import { useState } from "react";

const PRESETS = [
  ["簡潔に",     "もっと簡潔にまとめて"],
  ["詳しく",     "もっと詳しく説明して"],
  ["わかりやすく","専門用語を避けてわかりやすく"],
  ["学術的に",   "より学術的な表現に変えて"],
  ["音声向け",   "音声で聞きやすい文体に変えて"],
];

/** Claude API が使えないときのデモ修正 */
function demoRewrite(text, instr) {
  if (instr.includes("簡潔"))       return text.length > 30 ? text.substring(0, Math.floor(text.length * 0.62)) + "。" : text;
  if (instr.includes("詳しく"))      return text + "　この点は特に重要で、背景知識も参照するとより理解が深まります。";
  if (instr.includes("学術"))        return `本節において、${text}`;
  if (instr.includes("音声"))        return text.replace(/。/g, "。 ");
  return text;
}

/**
 * AI修正パネル（SentenceCard 内に展開）
 * - プリセットチップまたは自由入力で修正方針を指定
 * - Claude API を呼び出し、結果を適用 or 破棄
 */
export default function AiPanel({ text, onApply, addToast }) {
  const [instr,   setInstr]   = useState("");
  const [result,  setResult]  = useState(null);
  const [loading, setLoading] = useState(false);

  const send = async () => {
    if (!instr.trim()) { addToast("er", "修正方針を入力してください"); return; }
    setLoading(true); setResult(null);
    addToast("ai", "✨ AI修正中...");
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514",
          max_tokens: 1000,
          messages: [{
            role: "user",
            content: `あなたは講義台本の編集アシスタントです。\n\n【元の文】\n${text}\n\n【修正指示】\n${instr}\n\n修正後の文のみを出力してください。講義台本として自然な日本語で、元の要旨を大きく外れないようにしてください。`,
          }],
        }),
      });
      const d = await res.json();
      const r = d.content?.[0]?.text?.trim() ?? "";
      if (!r) throw new Error("empty response");
      setResult(r);
      addToast("ai", "✨ 修正案を生成しました");
    } catch {
      // API未接続のときはデモ修正にフォールバック
      setResult(demoRewrite(text, instr));
      addToast("in", "🔧 デモ修正案（Claude API未接続）");
    }
    setLoading(false);
  };

  return (
    <div style={{ marginTop: 8, border: "1px solid rgba(167,139,250,.2)", borderRadius: "var(--r)", overflow: "hidden" }}>

      {/* ヘッダー */}
      <div style={{ padding: "5px 9px", background: "var(--pud)", borderBottom: "1px solid rgba(167,139,250,.18)", fontSize: 10, color: "var(--pu)" }}>
        ✨ AI修正 — 修正方針を指定してください
      </div>

      {/* プリセットチップ */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 3, padding: "6px 9px", borderBottom: "1px solid var(--bd)" }}>
        {PRESETS.map(([lbl, val]) => (
          <button key={lbl} onClick={() => setInstr(val)} style={{
            padding: "2px 8px",
            border: `1px solid ${instr === val ? "var(--pu)" : "var(--bd2)"}`,
            borderRadius: 20,
            background: instr === val ? "var(--pud)" : "none",
            color: instr === val ? "var(--pu)" : "var(--ts)",
            fontSize: 10,
          }}>
            {lbl}
          </button>
        ))}
      </div>

      {/* テキストエリア + 送信 */}
      <div style={{ display: "flex", gap: 5, padding: "6px 9px" }}>
        <textarea
          value={instr}
          onChange={(e) => setInstr(e.target.value)}
          rows={2}
          placeholder='例：「重要な点を強調して」「例え話を加えて」…'
          style={{ flex: 1, padding: "5px 7px", background: "var(--s3)", border: "1px solid var(--bd2)", borderRadius: "var(--r)", color: "var(--tp)", fontFamily: "var(--fb)", fontSize: 11, resize: "none", lineHeight: 1.5, outline: "none" }}
        />
        <button onClick={send} disabled={loading} style={{
          padding: "5px 10px", background: "var(--pu)", border: "none", borderRadius: "var(--r)",
          color: "#fff", fontSize: 11, opacity: loading ? 0.5 : 1,
          alignSelf: "flex-end", flexShrink: 0,
        }}>
          {loading ? ".." : "送信"}
        </button>
      </div>

      {/* 結果 */}
      {result && (
        <div style={{ padding: "6px 9px" }}>
          <div style={{ fontSize: 11, lineHeight: 1.6, color: "var(--tp)", background: "var(--s3)", padding: "7px 9px", borderRadius: "var(--r)", border: "1px solid var(--bd)", marginBottom: 7, whiteSpace: "pre-wrap" }}>
            {result}
          </div>
          <div style={{ display: "flex", gap: 5 }}>
            <button onClick={() => { onApply(result); setResult(null); setInstr(""); addToast("ok", "✅ 修正を適用しました"); }}
              style={{ padding: "4px 10px", background: "var(--gd)", border: "1px solid var(--gr)", borderRadius: 4, color: "var(--gr)", fontSize: 10 }}>
              ✅ 適用
            </button>
            <button onClick={() => setResult(null)}
              style={{ padding: "4px 10px", background: "var(--s3)", border: "1px solid var(--bd2)", borderRadius: 4, color: "var(--ts)", fontSize: 10 }}>
              ✕ 破棄
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
