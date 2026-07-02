import { expect, test } from "@playwright/test";
import {
  apiContext,
  apiToken,
  DESKTOP,
  loginViaUi,
  seedDataset,
  uniqueName,
} from "./helpers";

// Golden sets (datasets) end to end: author one through the real form, edit it (name is immutable;
// cases are replaced wholesale), and delete it. These are the curated cases a prompt must pass
// before promotion, so the CRUD around them is load-bearing for the whole quality story.
test.use({ viewport: DESKTOP });

test.describe("Golden sets", () => {
  test("author a golden set through the UI", async ({ page }) => {
    const name = uniqueName("ds-create");
    await loginViaUi(page);

    await page.goto("/datasets");
    await expect(page.getByRole("heading", { name: "Golden sets" })).toBeVisible();
    await page.getByRole("link", { name: /new golden set/i }).click();

    await page.getByLabel("Name").fill(name);
    await page.getByLabel("Description").fill("Two cases the summarizer must pass");

    // The form opens with one empty case; add a second, then fill both inputs (references optional).
    // Case fields are targeted by placeholder (each case repeats the label "Input"/"Reference",
    // and the wrapping-label association is unreliable to drive by nth-of-label).
    await page.getByRole("button", { name: "Add case" }).click();
    const inputs = page.getByPlaceholder(/^Summarize:/);
    await expect(inputs).toHaveCount(2);
    await inputs.nth(0).fill("Summarize: revenue grew 12% last quarter.");
    await inputs.nth(1).fill("Summarize: the outage lasted three hours.");
    await page.getByPlaceholder("The expected answer").nth(0).fill("Revenue up 12%.");

    // The case counter reflects usable (non-blank input) cases.
    await expect(page.getByText("2 cases")).toBeVisible();

    await page.getByRole("button", { name: /create golden set/i }).click();
    await expect(page).toHaveURL(/\/datasets$/);
    await expect(page.getByRole("link", { name })).toBeVisible();
  });

  test("edit a golden set: change the description and add a case", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("ds-edit");
    await seedDataset(api, token, {
      name,
      items: [{ input: "Summarize: A.", reference: "A." }, { input: "Summarize: B.", reference: "B." }],
    });

    await loginViaUi(page);
    await page.goto("/datasets");
    await page.getByRole("link", { name }).click();
    await expect(page).toHaveURL(new RegExp(`/datasets/${name}/edit$`));

    // Wait for the form to hydrate from the fetched dataset, then assert its shape:
    // name is immutable in edit mode (no Name field) and the two seeded cases are prefilled.
    await expect(page.getByPlaceholder(/^Summarize:/).first()).toBeVisible();
    await expect(page.getByLabel("Name")).toHaveCount(0);
    await expect(page.getByPlaceholder(/^Summarize:/)).toHaveCount(2);

    await page.getByLabel("Description").fill("Now three cases");
    await page.getByRole("button", { name: "Add case" }).click();
    const inputs = page.getByPlaceholder(/^Summarize:/);
    await expect(inputs).toHaveCount(3);
    await inputs.nth(2).fill("Summarize: C.");
    // The "N cases" counter only counts non-blank inputs — wait for it to register all three so we
    // don't save before React has committed the new row's value.
    await expect(page.getByText("3 cases")).toBeVisible();

    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page).toHaveURL(/\/datasets$/);

    // Re-open with a full navigation (fresh fetch, no SPA cache) to confirm all three persisted.
    await page.goto(`/datasets/${name}/edit`);
    await expect(page.getByPlaceholder(/^Summarize:/).first()).toBeVisible();
    await expect(page.getByPlaceholder(/^Summarize:/)).toHaveCount(3);
  });

  test("delete a golden set", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("ds-delete");
    await seedDataset(api, token, { name, items: [{ input: "Summarize: X.", reference: "X." }] });

    await loginViaUi(page);
    await page.goto("/datasets");
    await expect(page.getByRole("link", { name })).toBeVisible();

    await page.getByRole("button", { name: `Delete ${name}` }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Delete golden set")).toBeVisible();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();

    await expect(page.getByRole("link", { name })).toHaveCount(0);
  });
});
