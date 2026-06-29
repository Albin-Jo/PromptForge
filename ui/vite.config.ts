/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Tailwind v4 ships a first-party Vite plugin, so there is no separate
// postcss.config.js / tailwind.config.js — the directives live in src/index.css.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The "@/" alias mirrors the tsconfig path so shadcn-style "@/components/ui/..."
  // imports resolve identically in the bundler, the typechecker, and Vitest
  // (Vitest reads this same config, so no separate test alias is needed).
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: false,
    // Unit/component tests live in src/. The e2e/ specs are Playwright's — keep Vitest out.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
