import React, { useEffect, useState } from "react";

function formatRuntimeError(error) {
  if (!error) return "Unknown runtime error";
  if (typeof error === "string") return error;
  if (error?.message) return error.message;
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function RuntimeErrorPanel({ error, onDismiss }) {
  const message = formatRuntimeError(error);
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "grid",
        placeItems: "center",
        padding: 24,
        background: "rgba(7,8,11,.82)",
        color: "var(--tp, #edf2ff)",
      }}
    >
      <div
        style={{
          width: "min(720px, 100%)",
          padding: 20,
          borderRadius: 14,
          border: "1px solid rgba(224,91,91,.45)",
          background: "linear-gradient(180deg, rgba(48,24,27,.98), rgba(19,21,26,.98))",
          boxShadow: "0 24px 60px rgba(0,0,0,.42)",
        }}
      >
        <div style={{ fontFamily: "var(--ff, sans-serif)", fontSize: 20, marginBottom: 8 }}>
          画面エラーが発生しました
        </div>
        <div style={{ fontSize: 12, color: "var(--ts, #aeb8cc)", lineHeight: 1.8, marginBottom: 14 }}>
          編集内容を守るため、画面の更新を停止しました。下のエラー内容を控えてから再読み込みしてください。
        </div>
        <pre
          style={{
            maxHeight: 220,
            overflow: "auto",
            padding: 12,
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,.08)",
            background: "rgba(0,0,0,.28)",
            color: "#ffd6d6",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            fontSize: 12,
          }}
        >
          {message}
        </pre>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
          <button
            onClick={onDismiss}
            style={{
              padding: "8px 12px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,.16)",
              background: "rgba(255,255,255,.06)",
              color: "inherit",
            }}
          >
            閉じる
          </button>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: "8px 12px",
              borderRadius: 10,
              border: "1px solid rgba(130,178,255,.42)",
              background: "var(--ac, #5b8def)",
              color: "#fff",
              fontWeight: 700,
            }}
          >
            再読み込み
          </button>
        </div>
      </div>
    </div>
  );
}

export class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("LectureCraft render error:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <RuntimeErrorPanel
          error={this.state.error}
          onDismiss={() => this.setState({ error: null })}
        />
      );
    }
    return this.props.children;
  }
}

export function AppRuntimeGuard({ children }) {
  const [error, setError] = useState(null);

  useEffect(() => {
    const onError = (event) => {
      setError(event.error || event.message || "Window error");
    };
    const onUnhandledRejection = (event) => {
      setError(event.reason || "Unhandled promise rejection");
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  return (
    <>
      {children}
      {error && (
        <RuntimeErrorPanel
          error={error}
          onDismiss={() => setError(null)}
        />
      )}
    </>
  );
}
