import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

// UX / UI review suite. Where the other specs prove *flows* work, this one pins down how the app
// *looks and behaves as a UI*: full-width layout on the data-dense dashboard, responsive
// breakpoints (mobile vs desktop), active-tab state, and the observability window toggle's
// pressed state. It is self-seeding — it creates its own prompt via the API — so it runs in CI
// without SMOKE_PROMPT or the async worker pipeline.
const ADMIN_EMAIL = "admin@promptforge.dev";
const ADMIN_PASSWORD = "devpassword123";
const API = "http://localhost:8001";

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 375, height: 812 }; // iPhone-ish portrait

// The widened dashboard/versions shell caps at the 2xl breakpoint, 1536px.
const MAX_W_2XL = 1536;
// max-w-5xl (the reading-width pages) is 64rem = 1024px.
const MAX_W_5XL = 1024;
// A viewport wider than the 1536 cap, so the cap actually binds and we can measure it.
const WIDE = { width: 1700, height: 1000 };

// These specs assert exact widths and flip between desktop/mobile, so they need a deterministic
// viewport — they opt out of the config's maximized (viewport: null) default, which would make
// page.setViewportSize() throw. The watch-it-run demo specs keep the maximized window.
test.use({ viewport: DESKTOP });

async function seedPrompt(api: APIRequestContext, name: string): Promise<void> {
  const login = await api.post(`${API}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const { access_token } = await login.json();
  const res = await api.post(`${API}/prompts`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      name,
      description: "UX review seed prompt",
      content: "Summarize {{text}}",
      input_variables: ["text"],
      blocks: [],
    },
  });
  expect(res.ok()).toBeTruthy();
}

async function loginViaUi(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  // Login lands on the Overview index; assert the authed shell (each test navigates on from here).
  await expect(page.getByRole("link", { name: "Prompts", exact: true }).first()).toBeVisible();
}

test.describe("UX review", () => {
  test("login card stays centered and readable on mobile and desktop", async ({ page }) => {
    // The login form is a max-w-sm card centered in a full-height flex container. It should look
    // the same (centered, never overflowing) at both ends of the viewport range.
    await page.goto("/login");
    const card = page.locator("form");

    for (const [label, size] of [
      ["mobile", MOBILE],
      ["desktop", DESKTOP],
    ] as const) {
      await page.setViewportSize(size);
      // "Sign in" is a card title (not a heading) after the restyle; the submit button is the
      // reliable "login card rendered" signal.
      await expect(page.getByRole("button", { name: /sign in/i })).toBeVisible();
      const box = await card.boundingBox();
      expect(box, "login card should be laid out").not.toBeNull();
      // Never wider than the viewport (no horizontal overflow), and horizontally centered.
      expect(box!.width).toBeLessThanOrEqual(size.width);
      const cardCenter = box!.x + box!.width / 2;
      expect(Math.abs(cardCenter - size.width / 2)).toBeLessThan(2);
      await page.screenshot({ path: `e2e/__screenshots__/ux-login-${label}.png` });
    }
  });

  test("dashboard uses the widened (1536px) shell, not the 1024px reading width", async ({
    page,
  }) => {
    const api = await request.newContext();
    const name = `ux-dash-${Date.now()}`;
    await seedPrompt(api, name);

    // Use a viewport wider than the 1536 cap so the cap binds and we can measure it precisely.
    await page.setViewportSize(WIDE);
    await loginViaUi(page);
    await page.goto(`/prompts/${name}/dashboard`);

    await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();

    // On the dashboard the shell's <main> expands to the 1536 cap: far wider than the 5xl reading
    // width, and bounded by 1536 — proving the route-aware widening kicked in.
    const main = page.locator("main");
    const box = await main.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(MAX_W_5XL); // would have failed before the widening
    expect(box!.width).toBeLessThanOrEqual(MAX_W_2XL + 1);
    expect(box!.width).toBeGreaterThan(MAX_W_2XL - 50); // actually reaches ~1536, not stuck at 1280

    await page.screenshot({ path: "e2e/__screenshots__/ux-dashboard-desktop.png", fullPage: true });
  });

  test("the prompt list keeps the narrower reading width", async ({ page }) => {
    // Counterpart to the dashboard test: non-dense pages must NOT widen, so prose/tables stay
    // comfortable to read on a big monitor.
    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);

    const main = page.locator("main");
    const box = await main.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeLessThanOrEqual(MAX_W_5XL + 1);
  });

  test("the observability window toggle reflects the selected window via aria-pressed", async ({
    page,
  }) => {
    const api = await request.newContext();
    const name = `ux-toggle-${Date.now()}`;
    await seedPrompt(api, name);

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);
    await page.goto(`/prompts/${name}/dashboard`);

    const sevenDay = page.getByRole("button", { name: "7d", exact: true });
    const dayWindow = page.getByRole("button", { name: "24h", exact: true });

    // Default selection is 7d.
    await expect(sevenDay).toHaveAttribute("aria-pressed", "true");
    await expect(dayWindow).toHaveAttribute("aria-pressed", "false");

    // Selecting 24h moves the pressed state; only one window is ever pressed.
    await dayWindow.click();
    await expect(dayWindow).toHaveAttribute("aria-pressed", "true");
    await expect(sevenDay).toHaveAttribute("aria-pressed", "false");
  });

  test("the prompt sub-nav marks the active tab as the route changes", async ({ page }) => {
    const api = await request.newContext();
    const name = `ux-tabs-${Date.now()}`;
    await seedPrompt(api, name);

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);

    // Editor is active on the edit route.
    await page.goto(`/prompts/${name}/edit`);
    const editorTab = page.getByRole("link", { name: "Editor", exact: true });
    const versionsTab = page.getByRole("link", { name: "Versions", exact: true });
    const dashboardTab = page.getByRole("link", { name: "Dashboard", exact: true });
    await expect(editorTab).toHaveAttribute("aria-current", "page");
    await expect(versionsTab).not.toHaveAttribute("aria-current", "page");

    // Clicking through moves the active marker with the route.
    await versionsTab.click();
    await expect(page).toHaveURL(new RegExp(`/prompts/${name}/versions$`));
    await expect(versionsTab).toHaveAttribute("aria-current", "page");
    await expect(editorTab).not.toHaveAttribute("aria-current", "page");

    await dashboardTab.click();
    await expect(page).toHaveURL(new RegExp(`/prompts/${name}/dashboard$`));
    await expect(dashboardTab).toHaveAttribute("aria-current", "page");
  });

  test("the playground is two-column on desktop and stacks on mobile", async ({ page }) => {
    const api = await request.newContext();
    const name = `ux-play-${Date.now()}`;
    await seedPrompt(api, name);

    await loginViaUi(page);
    await page.goto(`/prompts/${name}/versions/1/playground`);

    const inputs = page.getByRole("heading", { name: "Inputs" });
    const output = page.getByRole("heading", { name: "Output" });
    await expect(inputs).toBeVisible();
    await expect(output).toBeVisible();

    // Desktop (md:grid-cols-2): Output sits to the RIGHT of Inputs (same row).
    await page.setViewportSize(DESKTOP);
    const inDesk = await inputs.boundingBox();
    const outDesk = await output.boundingBox();
    expect(outDesk!.x).toBeGreaterThan(inDesk!.x + 100);
    await page.screenshot({ path: "e2e/__screenshots__/ux-playground-desktop.png" });

    // Mobile (single column): Output stacks BELOW Inputs.
    await page.setViewportSize(MOBILE);
    const inMob = await inputs.boundingBox();
    const outMob = await output.boundingBox();
    expect(outMob!.y).toBeGreaterThan(inMob!.y + 50);
    await page.screenshot({ path: "e2e/__screenshots__/ux-playground-mobile.png" });
  });
});
