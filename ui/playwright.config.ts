import { defineConfig } from "@playwright/test";

// E2E config tuned for *watching* the flow: a visible browser, slowed down.
// Assumes the API stack is already up (docker compose) and lets Playwright start
// the UI dev server itself.
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    headless: false, // open a real window so the run is visible
    // A *pinned* viewport sizes the page to that box no matter how big the window is — which is
    // why the window looked un-maximized. Instead, let the page follow the real window size
    // (viewport: null) and tell Chromium to open maximized. Now headed runs and full-page
    // screenshots use the whole monitor, the way the app looks in real use.
    viewport: null,
    launchOptions: {
      args: ["--start-maximized"],
      slowMo: 900, // pause ~0.9s between actions so each step is easy to follow
    },
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      // A real maximized window, not an emulated device: the "Desktop Chrome" descriptor pins a
      // deviceScaleFactor, which Playwright rejects alongside viewport: null. Plain chromium with
      // a null viewport follows the maximized window instead.
      use: { viewport: null },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
