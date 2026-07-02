import { defineConfig } from "@playwright/test";

// E2E config with two modes, one knob:
//   • default (watching): a real maximized window, slowed down, so a person/recording can follow.
//   • PW_HEADED=0 (fast/CI/iteration): headless, no slowMo — same specs, just quick.
// Override the pace with PW_SLOWMO=<ms>. Assumes the API stack is already up (docker compose) and
// lets Playwright start the UI dev server itself.
const HEADED = process.env.PW_HEADED !== "0";
const SLOW_MO = Number(process.env.PW_SLOWMO ?? (HEADED ? 900 : 0));

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  // Fast/CI runs share one dev server + API, so a long back-to-back run occasionally trips a
  // contention blip (a slow render or a transient seed 5xx). Retry once there. Headed watch-runs
  // stay retry-free so a failure is seen immediately (and doesn't re-run a slow, slow-mo test).
  retries: HEADED ? 0 : 1,
  reporter: "list",
  use: {
    baseURL: "http://localhost:5173",
    headless: !HEADED, // headed opens a real window so the run is visible
    // A *pinned* viewport sizes the page to that box no matter how big the window is — which is
    // why the window looked un-maximized. Instead, let the page follow the real window size
    // (viewport: null) and tell Chromium to open maximized. Now headed runs and full-page
    // screenshots use the whole monitor, the way the app looks in real use. (Specs that assert
    // exact widths opt into a fixed viewport via test.use.)
    viewport: null,
    launchOptions: {
      args: HEADED ? ["--start-maximized"] : [],
      slowMo: SLOW_MO, // pause between actions so each step is easy to follow (headed only by default)
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
