import { expect, test } from "@playwright/test";

// Sprint 16 smoke: drive the three new read surfaces in a real browser against a stack whose
// read model has been seeded (traces, a completed scan, eval runs). The prompt name is passed in
// via SMOKE_PROMPT. Screenshots land in e2e/__screenshots__/ for visual inspection.
const ADMIN_EMAIL = "admin@promptforge.dev";
const ADMIN_PASSWORD = "devpassword123";
const PROMPT = process.env.SMOKE_PROMPT ?? "";

// This spec needs a prompt whose read model (traces / scan / eval runs) is already seeded, passed
// via SMOKE_PROMPT. It is NOT self-seeding — the async worker pipeline seeds that in a healthy
// stack; here it was seeded directly. Skipped (not failed) when SMOKE_PROMPT is absent, so it
// doesn't break the CI e2e run.
test("dashboards + scan results render seeded data", async ({ page }) => {
  test.skip(PROMPT === "", "set SMOKE_PROMPT to a seeded prompt name to run this smoke spec");

  // --- log in ---
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();

  // --- Dashboard tab: observability + eval ---
  await page.goto(`/prompts/${PROMPT}/dashboard`);
  await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();
  // Observability surfaced: section + per-version rows.
  await expect(page.getByRole("heading", { name: "By version", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "v1", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "v2", exact: true }).first()).toBeVisible();
  // Eval section: scores across versions + scorer breakdown for the selected (newest) version.
  await expect(page.getByRole("heading", { name: "Eval scores" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Quality by version" })).toBeVisible();
  await page.screenshot({ path: "e2e/__screenshots__/s16-dashboard-7d.png", fullPage: true });

  // Switch the window control and confirm it stays rendered (re-keys the metrics query).
  await page.getByRole("button", { name: "24h" }).click();
  await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();

  // Drill the eval detail into v1 (has two scorers).
  await page.getByLabel("Eval detail version").selectOption("1");
  await expect(page.getByText("llm_judge")).toBeVisible();
  await page.screenshot({ path: "e2e/__screenshots__/s16-eval-v1.png", fullPage: true });

  // --- Scan results for v1 (seeded: high risk, 2 findings) ---
  await page.goto(`/prompts/${PROMPT}/versions/1/scan`);
  await expect(page.getByRole("heading", { name: /security scan/i })).toBeVisible();
  await expect(page.getByText("Secrets")).toBeVisible();
  await expect(page.getByText("PII")).toBeVisible();
  await expect(page.getByText(/possible aws access key id/i)).toBeVisible();
  await page.screenshot({ path: "e2e/__screenshots__/s16-scan-v1.png", fullPage: true });

  // --- the version-history "Scan" link wires through to the scan view ---
  await page.goto(`/prompts/${PROMPT}/versions`);
  await expect(page.getByRole("link", { name: "Scan →" }).first()).toBeVisible();
});
