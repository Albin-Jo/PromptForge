import { expect, test } from "@playwright/test";
import {
  apiContext,
  apiToken,
  DESKTOP,
  loginViaUi,
  seedPrompt,
  uniqueName,
} from "./helpers";

// Traces + run history. Both are read surfaces fed by the async worker, so the always-on tests
// assert the *empty states* on a fresh prompt (self-seeding, CI-safe). The populated drill-down
// needs a prompt with real traffic seeded — gated on SMOKE_PROMPT, skipped (not failed) otherwise,
// exactly like sprint16-smoke.
test.use({ viewport: DESKTOP });

const SMOKE_PROMPT = process.env.SMOKE_PROMPT ?? "";

test.describe("Traces & runs", () => {
  test("a fresh prompt's traces page shows the empty state", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("tr-empty");
    await seedPrompt(api, token, { name, content: "Summarize {{text}}", inputVariables: ["text"] });

    await loginViaUi(page);
    await page.goto(`/prompts/${name}/traces`);
    await expect(page.getByRole("heading", { name: `${name} — traces` })).toBeVisible();
    await expect(page.getByText(/no executions recorded for this prompt yet/i)).toBeVisible();
  });

  test("a fresh version's runs page shows empty eval + scan history", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("run-empty");
    await seedPrompt(api, token, { name, content: "Summarize {{text}}", inputVariables: ["text"] });

    await loginViaUi(page);
    await page.goto(`/prompts/${name}/versions/1/runs`);
    await expect(page.getByRole("heading", { name: `${name} — v1 runs` })).toBeVisible();
    // Evals need a golden set, so a fresh version has none (genuine empty state). Scans, however,
    // auto-enqueue when a version is created — so the scan section shows a run, not an empty state.
    await expect(page.getByText("Eval runs")).toBeVisible();
    await expect(page.getByText(/no evals have run for this version yet/i)).toBeVisible();
    await expect(page.getByText("Security scans")).toBeVisible();
  });

  test("traces list renders rows and drills into a trace detail", async ({ page }) => {
    test.skip(SMOKE_PROMPT === "", "set SMOKE_PROMPT to a seeded, high-traffic prompt to run this");

    await loginViaUi(page);
    await page.goto(`/prompts/${SMOKE_PROMPT}/traces`);
    await expect(page.getByRole("heading", { name: `${SMOKE_PROMPT} — traces` })).toBeVisible();

    // Before selecting anything, the detail pane prompts you to pick a trace.
    await expect(page.getByText(/select a trace to inspect/i)).toBeVisible();

    // Each execution is a clickable row (role="button"); the newest list at the top.
    const firstRow = page.locator("tbody tr[role='button']").first();
    await expect(firstRow).toBeVisible();
    await firstRow.click();
    // Selecting a row expands it and populates the detail pane.
    await expect(firstRow).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByText(/select a trace to inspect/i)).toHaveCount(0);

    // The version filter is present to re-query the list by version.
    await expect(page.getByLabel(/filter traces by version/i)).toBeVisible();
    await page.screenshot({ path: "e2e/__screenshots__/traces-detail.png", fullPage: true });
  });
});
