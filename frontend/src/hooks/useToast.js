import { useState, useCallback, useRef } from "react";

/**
 * トースト通知フック
 * type: "ok" | "er" | "ai" | "in"
 */
export function useToast() {
  const [toasts, setToasts] = useState([]);
  const addToast = useCallback((type, msg) => {
    const id = Date.now();
    setToasts((p) => [...p, { id, type, msg }]);
    setTimeout(() => setToasts((p) => p.filter((t) => t.id !== id)), 3200);
  }, []);
  return { toasts, addToast };
}
