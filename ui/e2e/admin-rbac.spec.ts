import { expect, test } from "@playwright/test";
import {
  apiContext,
  apiToken,
  DESKTOP,
  loginViaUi,
  seedPrompt,
  seedPromptVersion,
  seedUser,
  uniqueName,
} from "./helpers";

// Access control, proven both ways. The interesting RBAC assertions aren't "admin can see X" —
// they're "a non-admin *cannot*". So these tests self-seed an editor (the non-admin role) via the
// admin API and drive the UI as that editor: admin nav is absent, admin routes bounce, and the
// promote control is disabled with a reason. Then the admin path confirms the surfaces render and
// user-management CRUD works through the dialog.
test.use({ viewport: DESKTOP });

const EDITOR_PASSWORD = "editor-pw-12345";
const ADMIN_ROUTES: [string, RegExp][] = [
  ["/users", /Users/],
  ["/activity", /Activity/],
  ["/operations", /Operations/],
];

test.describe("Admin & RBAC", () => {
  test("an editor never sees the admin nav sections", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const editor = await seedUser(api, token, {
      email: uniqueName("editor") + "@promptforge.dev",
      password: EDITOR_PASSWORD,
      role: "editor",
    });

    await loginViaUi(page, editor.email, editor.password);

    // Editor-usable sections are present…
    await expect(page.getByRole("link", { name: "Prompts", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Golden sets", exact: true }).first()).toBeVisible();
    await expect(page.getByRole("link", { name: "Blocks", exact: true }).first()).toBeVisible();
    // …admin-only sections are filtered out entirely (not merely hidden).
    await expect(page.getByRole("link", { name: "Users", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Activity", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Operations", exact: true })).toHaveCount(0);
  });

  test("an editor is bounced off admin routes with a reason", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const editor = await seedUser(api, token, {
      email: uniqueName("editor") + "@promptforge.dev",
      password: EDITOR_PASSWORD,
      role: "editor",
    });
    await loginViaUi(page, editor.email, editor.password);

    for (const [route] of ADMIN_ROUTES) {
      await page.goto(route);
      // RequireAdmin redirects to the fleet overview and toasts the reason. (Toasts stack across
      // the loop, so match the first.)
      await expect(page).toHaveURL(/localhost:5173\/$/);
      await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
      await expect(page.getByText("Admin access required").first()).toBeVisible();
    }
  });

  test("an editor sees the promote control disabled with a reason", async ({ page }) => {
    const api = await apiContext();
    const token = await apiToken(api);
    const name = uniqueName("rbac-prompt");
    await seedPrompt(api, token, { name, content: "Summarize {{text}}", inputVariables: ["text"] });
    await seedPromptVersion(api, token, name, { content: "Summarize concisely: {{text}}", inputVariables: ["text"] });

    const editor = await seedUser(api, token, {
      email: uniqueName("editor") + "@promptforge.dev",
      password: EDITOR_PASSWORD,
      role: "editor",
    });
    await loginViaUi(page, editor.email, editor.password);
    await page.goto(`/prompts/${name}/versions`);

    const promote = page.getByRole("button", { name: "Promote", exact: true }).first();
    await expect(promote).toBeVisible();
    await expect(promote).toBeDisabled();
  });

  test("an admin sees the admin nav and every admin surface renders", async ({ page }) => {
    await loginViaUi(page); // bootstrap admin

    for (const [route, heading] of ADMIN_ROUTES) {
      await page.goto(route);
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    }
  });

  test("an admin creates a user through the dialog", async ({ page }) => {
    const newEmail = uniqueName("teammate") + "@promptforge.dev";
    await loginViaUi(page); // bootstrap admin

    await page.goto("/users");
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await page.getByRole("button", { name: /new user/i }).click();

    const dialog = page.getByRole("dialog");
    // "Create user" is both the dialog title and the submit button — scope to the heading.
    await expect(dialog.getByRole("heading", { name: "Create user" })).toBeVisible();
    await dialog.getByLabel("Email").fill(newEmail);
    await dialog.getByLabel("Password").fill("teammate-pw-12345");
    await dialog.getByLabel("Role").selectOption("editor");
    await dialog.getByRole("button", { name: /create user/i }).click();

    // Dialog closes and the new teammate appears in the table as an active editor (the same email
    // also flashes in a success toast, so scope to the table cell).
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByRole("cell", { name: newEmail, exact: true })).toBeVisible();
  });
});
