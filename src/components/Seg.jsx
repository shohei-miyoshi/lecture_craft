/**
 * セグメントコントロール（詳細度・難易度・提示形態の選択に使用）
 * props:
 *   opts: [{ v: value, l: label }]
 *   val:  現在の値
 *   onChange: (value) => void
 */
export default function Seg({ opts, val, onChange }) {
  return (
    <div style={{ display: "flex", background: "var(--s2)", border: "1px solid var(--bd)", borderRadius: "var(--r)", overflow: "hidden" }}>
      {opts.map((o, i) => (
        <button
          key={o.v}
          onClick={() => onChange(o.v)}
          style={{
            flex: 1, padding: "5px 2px", border: "none",
            borderLeft: i > 0 ? "1px solid var(--bd)" : "none",
            background: val === o.v ? "var(--ac)" : "none",
            color:      val === o.v ? "#fff" : "var(--ts)",
            fontFamily: "var(--fb)", fontSize: 10,
            fontWeight: val === o.v ? 600 : 400,
          }}
        >
          {o.l}
        </button>
      ))}
    </div>
  );
}
