import { expect, test } from "@playwright/test";
import {
  apiContext,
  apiToken,
  DESKTOP,
  loginViaUi,
  seedPrompt,
  seedPromptVersion,
  uniqueName,
} from "./helpers";

// Promotion — the gated deploy. Moving a label *is* a deployment: staging moves freely, while
// production runs the quality gate. The always-on tests cover the deterministic paths (staging
// success + the confirm dialog's UI); the gate-BLOCKED path needs a seeded prompt whose
// production promotion is known to be refused, so it's gated on GATE_PROMPT/GATE_VERSION.
test.use({ viewport: DESKTOP });

const GATE_PROMPT = process.env.GATE_PROMPT ?? "";
const GATE_VERSION = process.env.GATE_VERSION ?? "2";

async function seedTwoVersionPrompt(name: string): Promise<void> {
  const api = await apiContext();
  const token = await apiToken(api);
  await seedPrompt(api, token, { name, content: "Summarize {{text}}", inputVariables: ["text"] });
  await seedPromptVersion(api, token, name, { content: "Summarize concisely: {{text}}", inputVariables: ["text"] });
}

test.describe("Promotion", () => {
  test("promote a version to staging (no gate) attaches the label", async ({ page }) => {
    const name = uniqueName("promo-staging");
    await seedTwoVersionPrompt(name);

    await loginViaUi(page); // bootstrap admin — promotion is admin-only
    await page.goto(`/prompts/${name}/versions`);

    const v2Row = page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "v2", exact: true }),
    });
    // No label badge before we promote.
    await expect(v2Row.getByText("staging", { exact: true })).toHaveCount(0);

    await v2Row.getByRole("button", { name: "Promote", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Promote v2" })).toBeVisible();
    await dialog.getByLabel("Target label").selectOption("staging");
    await dialog.getByRole("button", { name: "Promote", exact: true }).click();

    // Success closes the dialog and the version's row now badges "staging".
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(v2Row.getByText("staging", { exact: true })).toBeVisible();
  });

  test("the promote dialog explains the gate and defaults to production", async ({ page }) => {
    const name = uniqueName("promo-dialog");
    await seedTwoVersionPrompt(name);

    await loginViaUi(page);
    await page.goto(`/prompts/${name}/versions`);

    const v1Row = page.getByRole("row").filter({
      has: page.getByRole("cell", { name: "v1", exact: true }),
    });
    await v1Row.getByRole("button", { name: "Promote", exact: true }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Promote v1" })).toBeVisible();
    await expect(dialog.getByText(/runs the quality gate/i)).toBeVisible();
    // Target defaults to production (the gated label) and staging is selectable.
    const target = dialog.getByLabel("Target label");
    await expect(target).toHaveValue("production");
    await target.selectOption("staging");
    await expect(target).toHaveValue("staging");
    // Close without deploying.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("promoting a regressed version to production is blocked by the gate", async ({ page }) => {
    test.skip(
      GATE_PROMPT === "",
      "set GATE_PROMPT (and optionally GATE_VERSION) to a seeded prompt whose production promote is refused",
    );

    await loginViaUi(page);
    await page.goto(`/prompts/${GATE_PROMPT}/versions`);

    const row = page.getByRole("row").filter({
      has: page.getByRole("cell", { name: `v${GATE_VERSION}`, exact: true }),
    });
    await row.getByRole("button", { name: "Promote", exact: true }).click();

    const dialog = page.getByRole("dialog");
    // Default target is production; confirm the gated promote.
    await dialog.getByRole("button", { name: "Promote", exact: true }).click();

    // The gate refuses with a per-metric breakdown rather than a raw error.
    await expect(dialog.getByText("Blocked by gate")).toBeVisible({ timeout: 30_000 });
    await expect(dialog.getByText("Scorer")).toBeVisible(); // the per-metric breakdown table header
    await page.screenshot({ path: "e2e/__screenshots__/promote-blocked.png", fullPage: true });
  });
});
