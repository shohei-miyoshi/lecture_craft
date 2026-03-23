import { useEffect, useRef } from "react";

/**
 * カスタム確認ダイアログ
 *
 * props:
 *   open     : boolean
 *   title    : string
 *   message  : string
 *   confirmLabel : string  (デフォルト "削除")
 *   confirmColor : string  (デフォルト "var(--rd)")
 *   onConfirm : () => void
 *   onCancel  : () => void
 */
export default function ConfirmDialog({
  open,
  title    = "確認",
  message  = "この操作は取り消せません。",
  confirmLabel = "削除",
  confirmColor = "var(--rd)",
  confirmBg    = "var(--rdd)",
  confirmBorder= "rgba(224,91,91,.35)",
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null);

  // Escキーでキャンセル、Enterで確定
  useEffect(() => {
    if (!open) return;
    // フォーカスをキャンセルボタンに当てる（Enterで誤確定しないよう）
    setTimeout(() => cancelRef.current?.focus(), 0);
    const h = (e) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open]);

  if (!open) return null;

  return (
    // オーバーレイ
    <div
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0, zIndex: 10000,
        background: "rgba(0,0,0,.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      {/* ダイアログ本体 */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--sur)",
          border: "1px solid var(--bd2)",
          borderRadius: "var(--rl)",
          padding: "20px 24px",
          width: 320,
          boxShadow: "0 20px 60px rgba(0,0,0,.6)",
          animation: "lc-fade .15s ease",
        }}
      >
        {/* タイトル */}
        <div style={{ fontFamily: "var(--ff)", fontSize: 14, fontWeight: 700, color: "var(--tp)", marginBottom: 8 }}>
          {title}
        </div>
        {/* メッセージ */}
        <div style={{ fontSize: 12, color: "var(--ts)", lineHeight: 1.65, marginBottom: 20 }}>
          {message}
        </div>
        {/* ボタン行 */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button
            ref={cancelRef}
            onClick={onCancel}
            style={{
              padding: "7px 16px",
              border: "1px solid var(--bd2)",
              borderRadius: "var(--r)",
              background: "var(--s2)",
              color: "var(--ts)",
              fontFamily: "var(--fb)",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            キャンセル
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: "7px 16px",
              border: `1px solid ${confirmBorder}`,
              borderRadius: "var(--r)",
              background: confirmBg,
              color: confirmColor,
              fontFamily: "var(--fb)",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
