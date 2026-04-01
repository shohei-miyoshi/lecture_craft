import { useState, useCallback } from "react";

/**
 * カスタム確認ダイアログ用フック
 *
 * 使い方:
 *   const { confirmProps, requestConfirm } = useConfirm();
 *   // ダイアログを開く
 *   requestConfirm({ title, message, confirmLabel, onConfirm });
 *   // JSXに <ConfirmDialog {...confirmProps} /> を置く
 */
export function useConfirm() {
  const [state, setState] = useState({
    open: false,
    title: "確認",
    message: "",
    confirmLabel: "削除",
    confirmColor: "var(--rd)",
    confirmBg: "var(--rdd)",
    confirmBorder: "rgba(224,91,91,.35)",
    onConfirm: () => {},
  });

  const requestConfirm = useCallback(({
    title = "確認",
    message = "",
    confirmLabel = "削除",
    confirmColor = "var(--rd)",
    confirmBg    = "var(--rdd)",
    confirmBorder= "rgba(224,91,91,.35)",
    onConfirm,
  }) => {
    setState({ open: true, title, message, confirmLabel, confirmColor, confirmBg, confirmBorder, onConfirm });
  }, []);

  const onCancel  = useCallback(() => setState((s) => ({ ...s, open: false })), []);
  const onConfirm = useCallback(() => {
    state.onConfirm?.();
    setState((s) => ({ ...s, open: false }));
  }, [state.onConfirm]);

  return {
    confirmProps: { ...state, onCancel, onConfirm },
    requestConfirm,
  };
}
