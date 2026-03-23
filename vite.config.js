import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
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
});
