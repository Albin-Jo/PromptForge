import { expect, test } from "@playwright/test";

// The Sprint 14 DoD demo, end to end in a real browser:
//   log in -> see the prompt list -> create a prompt -> see it appear.
//
// Credentials are the dev bootstrap admin seeded by docker-compose.override.yml.
const ADMIN_EMAIL = "admin@promptforge.dev";
const ADMIN_PASSWORD = "devpassword123";

test("log in, create a prompt, and see it in the list", async ({ page }) => {
  // A unique name per run so repeated runs don't collide on the unique-name constraint.
  // (Date.now() is allowed here — this is a Playwright test, not a workflow script.)
  const promptName = `e2e-demo-${Date.now()}`;

  // 1. A protected page bounces an unauthenticated visitor to /login.
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);

  // 2. Sign in as the seeded admin.
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();

  // 3. We land on the prompt list.
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();

  // 4. Create a new prompt (first version).
  await page.getByRole("link", { name: /new prompt/i }).click();
  await expect(page).toHaveURL(/\/prompts\/new$/);
  await page.getByLabel("Name").fill(promptName);
  await page.getByLabel("Description").fill("Created by the E2E watch-it-run demo");
  await page.getByLabel("Content").fill("Summarize the following text.");
  await page.getByRole("button", { name: /create prompt/i }).click();

  // 5. Back on the list, the new prompt is there.
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: promptName })).toBeVisible();
});
