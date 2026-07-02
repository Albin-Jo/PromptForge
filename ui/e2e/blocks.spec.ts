import { expect, test } from "@playwright/test";
import {
  API,
  apiContext,
  apiToken,
  DESKTOP,
  loginViaUi,
  seedBlock,
  uniqueName,
} from "./helpers";

// Blocks end to end: the composition primitive. Author one, add an immutable new version, and
// delete it — including the in-use guard that refuses a delete while a prompt still composes it.
test.use({ viewport: DESKTOP });

test.describe("Blocks", () => {
  test("author a block through the UI", async ({ page }) => {
    const name = uniqueName("blk-create");
    await loginViaUi(page);

    await page.goto("/blocks");
    await expect(page.getByRole("heading", { name: "Blocks" })).toBeVisible();
    await page.getByRole("link", { name: /new block/i }).click();

    await page.getByLabel("Name").fill(name);
    // Role is a Radix Select (a combobox button), not a native <select>: open it and pick the option.
    await page.getByLabel("Role").click();
    await page.getByRole("option", { name: "Guardrails" }).click();
    await page.getByLabel("Description").fill("Keep answers concise");
    await page.getByLabel("Content").fill("Be concise. Ground every claim in the input.");
    await page.getByRole("button", { name: "Create block" }).click();

    // Create lands on the block's detail page; the name is the heading and the edit actions appear.
    await expect(page).toHaveURL(new RegExp(`/blocks/${name}$`));
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByRole("link", { name: "New version" })).toBeVisible();
    await expect(page.getByRole("button", { name: `Delete ${name}` })).toBeVisible();
    // v1 shows in the version history.
    await expect(page.getByText("v1", { exact: true })).toBeVisible();

    // And it's listed back on the library.
    await page.goto("/blocks");
    await expect(page.getByRole("link", { name })).toBeVisible();
  });

  test("add a new immutable version to a block", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("blk-version");
    await seedBlock(api, token, { name, content: "First version content." });

    await loginViaUi(page);
    await page.goto(`/blocks/${name}`);
    await page.getByRole("link", { name: "New version" }).click();
    await expect(page).toHaveURL(new RegExp(`/blocks/${name}/versions/new$`));
    await expect(page.getByRole("heading", { name: `New version: ${name}` })).toBeVisible();

    // The version form carries the latest content forward; we change it and save.
    await page.getByLabel("Content").fill("Second version content — tightened.");
    await page.getByRole("button", { name: /save new version/i }).click();

    // Back on the detail page with two versions in the history.
    await expect(page).toHaveURL(new RegExp(`/blocks/${name}$`));
    await expect(page.getByText("v2", { exact: true })).toBeVisible();
    await expect(page.getByText("v1", { exact: true })).toBeVisible();
  });

  test("delete a block", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("blk-delete");
    await seedBlock(api, token, { name, content: "Deletable block." });

    await loginViaUi(page);
    await page.goto(`/blocks/${name}`);
    await page.getByRole("button", { name: `Delete ${name}` }).click();

    const dialog = page.getByRole("dialog");
    await expect(dialog.getByText("Delete block")).toBeVisible();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();

    // Deleting returns to the library, and the block is gone.
    await expect(page).toHaveURL(/\/blocks$/);
    await expect(page.getByRole("link", { name })).toHaveCount(0);
  });

  test("deleting a block is refused while a prompt composes it", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const blockName = uniqueName("blk-inuse");
    const promptName = uniqueName("blk-consumer");
    await seedBlock(api, token, { name: blockName, content: "Referenced guardrail." });

    // A prompt that pins this block v1 into its composition — the reference the guard must catch.
    const created = await api.post(`${API}/prompts`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        name: promptName,
        description: "composes the in-use block",
        content: "Answer the question.",
        input_variables: [],
        blocks: [{ block: blockName, version: 1 }],
      },
    });
    expect(created.ok(), "seed prompt composing the block").toBeTruthy();

    await loginViaUi(page);
    await page.goto(`/blocks/${blockName}`);
    await page.getByRole("button", { name: `Delete ${blockName}` }).click();

    const dialog = page.getByRole("dialog");
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();

    // The 409 surfaces inline as an in-use message; we stay on the block (no navigation to /blocks).
    await expect(dialog.getByText(/in use/i)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/blocks/${blockName}$`));
  });
});
