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
    variant: "confirm",
    title: "確認",
    message: "",
    confirmLabel: "削除",
    confirmColor: "var(--rd)",
    confirmBg: "var(--rdd)",
    confirmBorder: "rgba(224,91,91,.35)",
    inputLabel: "",
    inputPlaceholder: "",
    inputInitialValue: "",
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
    setState({
      open: true,
      variant: "confirm",
      title,
      message,
      confirmLabel,
      confirmColor,
      confirmBg,
      confirmBorder,
      inputLabel: "",
      inputPlaceholder: "",
      inputInitialValue: "",
      onConfirm,
    });
  }, []);

  const requestPrompt = useCallback(({
    title = "入力",
    message = "",
    confirmLabel = "保存",
    confirmColor = "var(--ac)",
    confirmBg    = "var(--adim)",
    confirmBorder= "rgba(91,141,239,.35)",
    inputLabel = "入力",
    inputPlaceholder = "",
    inputInitialValue = "",
    onConfirm,
  }) => {
    setState({
      open: true,
      variant: "prompt",
      title,
      message,
      confirmLabel,
      confirmColor,
      confirmBg,
      confirmBorder,
      inputLabel,
      inputPlaceholder,
      inputInitialValue,
      onConfirm,
    });
  }, []);

  const onCancel  = useCallback(() => setState((s) => ({ ...s, open: false })), []);
  const onConfirm = useCallback((value) => {
    state.onConfirm?.(value);
    setState((s) => ({ ...s, open: false }));
  }, [state.onConfirm]);

  return {
    confirmProps: { ...state, onCancel, onConfirm },
    requestConfirm,
    requestPrompt,
  };
}
