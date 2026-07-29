/**
 * トースト通知レイヤー
 * props: toasts — useToast() から受け取った配列
 */
export default function ToastLayer({ toasts }) {
  const colors = {
    ok: ["#182a22", "#4caf82"],
    er: ["#2a1818", "#e05b5b"],
    ai: ["#1e182a", "#a78bfa"],
    in: ["#181e2a", "#5b8def"],
  };
  return (
    <div style={{ position: "fixed", bottom: 12, right: 12, display: "flex", flexDirection: "column", gap: 4, zIndex: 9999, pointerEvents: "none" }}>
      {toasts.map((t) => {
        const [bg, c] = colors[t.type] ?? colors.in;
        return (
          <div key={t.id} style={{ padding: "7px 11px", borderRadius: "var(--r)", fontSize: 11, background: bg, border: `1px solid ${c}`, color: c, maxWidth: 240, animation: "lc-fade .15s ease" }}>
            {t.msg}
          </div>
        );
      })}
    </div>
  );
}
