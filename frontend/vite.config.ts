import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Phones report a tap as a hover that sticks until the next tap elsewhere, so a
// tapped filter row stays blue and a tapped notice stays lifted. Every :hover
// rule is moved into @media (hover: hover) at build time; selectors sharing a
// rule with :hover (e.g. :focus-within) keep applying everywhere.
const HOVER_MEDIA = "(hover: hover)";
const hoverOnlyWithPointer = {
  postcssPlugin: "hover-only-with-pointer",
  Rule(rule: import("postcss").Rule, { AtRule }: { AtRule: typeof import("postcss").AtRule }) {
    if (!rule.selector.includes(":hover")) return;
    const parent = rule.parent;
    if (parent?.type === "atrule" && (parent as import("postcss").AtRule).params.includes("hover")) return;
    const hover = rule.selectors.filter((sel) => sel.includes(":hover"));
    const rest = rule.selectors.filter((sel) => !sel.includes(":hover"));
    const media = new AtRule({ name: "media", params: HOVER_MEDIA });
    media.append(rule.clone({ selectors: hover }));
    if (rest.length) {
      rule.selectors = rest;
      rule.after(media);
    } else {
      rule.replaceWith(media);
    }
  },
};

// The API runs on :8000 in development (`uv run hackmash serve`); in production
// the same origin serves both the API and these static files.
export default defineConfig({
  plugins: [react()],
  css: { postcss: { plugins: [hoverOnlyWithPointer] } },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.HACKMASH_API ?? "http://127.0.0.1:8000", changeOrigin: true },
      "/data": { target: process.env.HACKMASH_API ?? "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { target: "es2022", sourcemap: false, cssMinify: true },
});
