import { useState } from "react";
import { loginUser, registerUser } from "../utils/sessionStore.js";

function panelStyle() {
  return {
    width: "min(420px, 100%)",
    padding: "24px 22px",
    border: "1px solid rgba(255,255,255,.08)",
    background: "linear-gradient(180deg, rgba(19,21,26,.96), rgba(19,21,26,.88))",
    boxShadow: "0 24px 56px rgba(0,0,0,.32)",
  };
}

export default function AuthScreen({ onAuthenticated, addToast }) {
  const [tab, setTab] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      const payload = tab === "login"
        ? await loginUser(username, password)
        : await registerUser(username, password);
      onAuthenticated?.(payload);
      addToast?.("ok", tab === "login" ? "ログインしました" : "アカウントを作成しました");
    } catch (error) {
      addToast?.("er", error.message || "認証に失敗しました");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: 24,
        background:
          "radial-gradient(circle at top left, rgba(91,141,239,.16), transparent 24%), radial-gradient(circle at bottom right, rgba(110,193,255,.1), transparent 20%), var(--bg)",
      }}
    >
      <div style={panelStyle()}>
        <div style={{ fontSize: 11, letterSpacing: "1.8px", textTransform: "uppercase", color: "var(--ac)", marginBottom: 10 }}>
          LectureCraft Access
        </div>
        <div style={{ fontFamily: "var(--ff)", fontSize: 30, lineHeight: 1.05, marginBottom: 10 }}>
          ログイン
        </div>
        <div style={{ fontSize: 12, color: "var(--ts)", lineHeight: 1.7, marginBottom: 18 }}>
          ユーザ名とパスワードでログインして、保存済みプロジェクトや研究ログをユーザ単位で管理します。
        </div>

        <div style={{ display: "inline-flex", padding: 3, borderRadius: 999, background: "var(--s2)", border: "1px solid var(--bd)", marginBottom: 16 }}>
          {[
            ["login", "ログイン"],
            ["register", "新規登録"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                padding: "6px 12px",
                border: "none",
                borderRadius: 999,
                background: tab === key ? "var(--ac)" : "transparent",
                color: tab === key ? "#fff" : "var(--ts)",
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div style={{ display: "grid", gap: 12 }}>
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 11, color: "var(--tm)" }}>ユーザ名</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="例: shohei"
              style={{ padding: "11px 12px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}
            />
          </label>

          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 11, color: "var(--tm)" }}>パスワード</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8文字以上"
              style={{ padding: "11px 12px", border: "1px solid var(--bd2)", background: "var(--sur)", color: "var(--tp)" }}
            />
          </label>

          <button
            onClick={submit}
            disabled={busy || !username.trim() || !password}
            style={{
              marginTop: 4,
              padding: "11px 14px",
              border: "1px solid rgba(130,178,255,.42)",
              background: "linear-gradient(180deg, rgba(122,165,242,.98), rgba(91,141,239,.88))",
              color: "#fff",
              fontSize: 12,
              fontWeight: 700,
              opacity: busy ? 0.7 : 1,
            }}
          >
            {busy ? "処理中..." : tab === "login" ? "ログイン" : "新規登録して開始"}
          </button>
        </div>

        <div style={{ marginTop: 14, fontSize: 10, color: "var(--tm)", lineHeight: 1.7 }}>
          最初に作成されたアカウントは管理者になります。以後のアカウントは通常ユーザとして作成されます。
        </div>
      </div>
    </div>
  );
}
