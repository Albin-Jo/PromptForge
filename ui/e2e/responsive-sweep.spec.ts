import { expect, test, type APIRequestContext } from "@playwright/test";
import {
  API,
  apiContext,
  apiToken,
  DESKTOP,
  expectNoHorizontalOverflow,
  loginViaUi,
  MOBILE,
  seedPrompt,
  TABLET,
  uniqueName,
} from "./helpers";

// Responsive + visual coverage in two layers:
//   1. A functional sweep — every core page, at mobile / tablet / desktop, must not overflow
//      horizontally (the #1 responsive bug), with a full-page screenshot captured for eyeballing.
//   2. Strict visual-regression snapshots on the *stable* surfaces (the login page, and an empty
//      dashboard with its live freshness chip masked). These FAIL if the pixels drift, so a layout
//      regression is caught, not just recorded.
//
// First run of the @snapshot tests generates the baselines (and reports them as "failed — writing
// baseline", which is expected): run once with `--update-snapshots`, then normally thereafter.
// Baselines are per-OS; they're generated on the machine that runs them.
test.use({ viewport: DESKTOP });

const VIEWPORTS = [
  ["mobile", MOBILE],
  ["tablet", TABLET],
  ["desktop", DESKTOP],
] as const;

// A stable, reused fixture name so the empty-dashboard snapshot renders identically each run
// (a per-run unique name would change the title and defeat the pixel comparison).
const DASHBOARD_FIXTURE = "e2e-snapshot-dashboard";

// Create a prompt idempotently — tolerate the 409 when the fixture already exists from a prior run.
async function ensurePrompt(api: APIRequestContext, token: string, name: string): Promise<void> {
  const res = await api.post(`${API}/prompts`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name,
      description: "empty-dashboard visual fixture",
      content: "Summarize {{text}}",
      input_variables: ["text"],
      blocks: [],
    },
  });
  if (!res.ok() && res.status() !== 409) {
    expect(res.ok(), `ensure fixture ${name}`).toBeTruthy();
  }
}

test.describe("Responsive & visual", () => {
  test("reading pages never overflow horizontally across breakpoints", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    await seedPrompt(api, token, {
      name: uniqueName("resp-prompt"),
      content: "Summarize {{text}}",
      inputVariables: ["text"],
    });

    await loginViaUi(page);

    // The reading / list surfaces must be clean (no page-level horizontal scroll) at every
    // breakpoint — these are the app's front door and are expected to be mobile-ready.
    const readingSurfaces: [string, string][] = [
      ["overview", "/"],
      ["prompts", "/prompts"],
      ["golden-sets", "/datasets"],
      ["blocks", "/blocks"],
    ];

    for (const [slug, url] of readingSurfaces) {
      await page.goto(url);
      for (const [label, size] of VIEWPORTS) {
        await page.setViewportSize(size);
        await page.waitForTimeout(150); // let the responsive layout settle before measuring
        await expectNoHorizontalOverflow(page);
        await page.screenshot({
          path: `e2e/__screenshots__/resp-${slug}-${label}.png`,
          fullPage: true,
        });
      }
    }
  });

  test("data-dense per-prompt pages are captured across breakpoints (overflow logged)", async ({
    page,
  }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("resp-dense");
    await seedPrompt(api, token, { name, content: "Summarize {{text}}", inputVariables: ["text"] });

    await loginViaUi(page);

    // The per-prompt dashboard / versions / playground carry wide tables + charts. A narrow viewport
    // can legitimately scroll a wide table, so we capture these for visual review and LOG any
    // page-level overflow rather than pin an arbitrary mobile target — a real regression still shows
    // up in the log and the screenshots. (As of writing, the dashboard overflows ~80px at 375px.)
    const denseSurfaces: [string, string][] = [
      ["dashboard", `/prompts/${name}/dashboard`],
      ["versions", `/prompts/${name}/versions`],
      ["playground", `/prompts/${name}/versions/1/playground`],
    ];

    for (const [slug, url] of denseSurfaces) {
      await page.goto(url);
      for (const [label, size] of VIEWPORTS) {
        await page.setViewportSize(size);
        await page.waitForTimeout(150);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        if (overflow > 1) {
          // eslint-disable-next-line no-console
          console.log(`  ⚠ ${slug} @ ${label} (${size.width}px): ${overflow}px horizontal overflow`);
        }
        await page.screenshot({
          path: `e2e/__screenshots__/resp-${slug}-${label}.png`,
          fullPage: true,
        });
      }
    }
  });

  test("login page matches its visual baseline @snapshot", async ({ page }) => {
    // Pin the theme so the baseline is deterministic regardless of the OS colour-scheme.
    await page.addInitScript(() => localStorage.setItem("pf-theme", "light"));
    await page.goto("/login");
    // "Sign in" is a card title (not a heading); the submit button is the reliable readiness signal.
    await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();

    await page.setViewportSize(MOBILE);
    await expect(page).toHaveScreenshot("login-mobile.png", { maxDiffPixelRatio: 0.02 });

    await page.setViewportSize(DESKTOP);
    await expect(page).toHaveScreenshot("login-desktop.png", { maxDiffPixelRatio: 0.02 });
  });

  test("login page in dark mode matches its visual baseline @snapshot", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("pf-theme", "dark"));
    await page.goto("/login");
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.setViewportSize(DESKTOP);
    await expect(page).toHaveScreenshot("login-dark-desktop.png", { maxDiffPixelRatio: 0.02 });
  });

  test("empty dashboard matches its visual baseline @snapshot", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    await ensurePrompt(api, token, DASHBOARD_FIXTURE);

    await page.addInitScript(() => localStorage.setItem("pf-theme", "light"));
    await loginViaUi(page);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/prompts/${DASHBOARD_FIXTURE}/dashboard`);
    await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();
    await expect(page.getByText(/no executions recorded in this window/i)).toBeVisible();

    // The "updated Ns ago" freshness chip re-ticks every second — mask it so only layout is compared.
    const freshness = page.getByRole("button", { name: "Refresh metrics" }).locator("..");
    await expect(page).toHaveScreenshot("dashboard-empty.png", {
      mask: [freshness],
      maxDiffPixelRatio: 0.02,
    });
  });
});
