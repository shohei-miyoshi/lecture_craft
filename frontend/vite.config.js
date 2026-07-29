import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function assertNoSecretLikeClientEnv(mode) {
  const env = loadEnv(mode, process.cwd(), "");
  const blockedNames = Object.keys(env).filter(
    (name) =>
      name.startsWith("VITE_") &&
      /(OPENAI|ANTHROPIC|GEMINI|CLAUDE|DEEPSEEK|API_KEY|SECRET|PASSWORD|PRIVATE)/i.test(name),
  );

  if (!blockedNames.length) {
    return;
  }

  const details = blockedNames.map((name) => `- ${name}`).join("\n");
  throw new Error(
    [
      "Secret-like VITE_ variables were found in frontend/.env*.",
      details,
      "",
      "VITE_* values are bundled into the browser and visible to users.",
      "Keep API keys only in backend environment variables such as OPENAI_API_KEY.",
    ].join("\n"),
  );
}

export default defineConfig(({ mode }) => {
  assertNoSecretLikeClientEnv(mode);
  const env = loadEnv(mode, process.cwd(), "");

  return {
    base: env.VITE_BASE_PATH || "/",
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        // バックエンド（localhost:8000）へのプロキシ
        // Vercel本番環境では環境変数 VITE_API_URL を使用
        "/api": {
          target: "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
