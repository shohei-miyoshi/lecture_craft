import { useState, useCallback } from "react";

/**
 * ConfirmModal — アプリ内カスタム確認ダイアログ
 * ブラウザの confirm() の代替。
 *
 * useConfirm() フックを使って Promise ベースで呼び出す：
 *   const { confirm, modal } = useConfirm();
 *   const ok = await confirm({ title, message, confirmLabel, confirmColor });
 *   if (ok) { ... }
 *
 * modal を JSX に配置するだけで使える。
 */
export function useConfirm() {
  const [state, setState] = useState({ open: false });

  const confirm = useCallback((opts) =>
    new Promise((resolve) => setState({ ...opts, open: true, resolve })),
  []);

  const handleOk = () => {
    state.resolve(true);
    setState((s) => ({ ...s, open: false }));
  };
  const handleCancel = () => {
    state.resolve(false);
    setState((s) => ({ ...s, open: false }));
  };

  const modal = (
    <ConfirmModal
      open={state.open}
      title={state.title ?? "確認"}
      message={state.message ?? ""}
      confirmLabel={state.confirmLabel ?? "実行"}
      confirmColor={state.confirmColor ?? "var(--ac)"}
      onConfirm={handleOk}
      onCancel={handleCancel}
    />
  );

  return { confirm, modal };
}

function ConfirmModal({ open, title, message, confirmLabel, confirmColor, onConfirm, onCancel }) {
  if (!open) return null;
  return (
    <div
      onClick={onCancel}
      style={{ position:"fixed", inset:0, background:"rgba(0,0,0,.65)", display:"flex", alignItems:"center", justifyContent:"center", zIndex:10000 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ background:"var(--sur)", border:"1px solid var(--bd2)", borderRadius:"var(--rl)", padding:"22px 26px", minWidth:300, maxWidth:400, animation:"lc-modal-in .15s ease" }}
      >
        <div style={{ fontFamily:"var(--ff)", fontSize:14, fontWeight:700, marginBottom:8 }}>{title}</div>
        <p style={{ fontSize:12, color:"var(--ts)", lineHeight:1.65, marginBottom:22, whiteSpace:"pre-line" }}>{message}</p>
        <div style={{ display:"flex", gap:8, justifyContent:"flex-end" }}>
          <button onClick={onCancel} style={{ padding:"7px 16px", border:"1px solid var(--bd2)", borderRadius:"var(--r)", background:"var(--s2)", color:"var(--tp)", fontSize:12, cursor:"pointer" }}>
            キャンセル
          </button>
          <button onClick={onConfirm} style={{ padding:"7px 16px", border:"none", borderRadius:"var(--r)", background:confirmColor, color:"#fff", fontSize:12, fontWeight:600, cursor:"pointer" }}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
