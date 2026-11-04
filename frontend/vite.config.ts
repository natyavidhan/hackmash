import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on :8000 in development (`uv run hackmash serve`); in production
// the same origin serves both the API and these static files.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.HACKMASH_API ?? "http://127.0.0.1:8000", changeOrigin: true },
      "/data": { target: process.env.HACKMASH_API ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { target: "es2022", sourcemap: false, cssMinify: true },
});
