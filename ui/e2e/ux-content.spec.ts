import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

// UX under *realistic, heavy content*: a long multi-line system prompt, edited many times with
// multi-line changes, then viewed across the editor / version-history / diff / dashboard surfaces.
// The point is to catch layout failures that only show up with real content — long lines blowing
// out the page width, version lists losing their order, diffs not rendering — none of which the
// short-string flow specs would surface.
//
// Self-seeding via the API (JWT, same as the other specs); no SMOKE_PROMPT or worker needed,
// except the final eval-detail test which is skipped unless a fully-seeded prompt is provided.
const ADMIN_EMAIL = "admin@promptforge.dev";
const ADMIN_PASSWORD = "devpassword123";
const API = "http://localhost:8001";

const DESKTOP = { width: 1440, height: 900 };

// This spec asserts layout under a fixed width and calls page.setViewportSize, so it pins a
// deterministic viewport rather than inheriting the config's maximized (viewport: null) default.
test.use({ viewport: DESKTOP });

// A long, multi-line prompt whose lines 4 and 7 carry the revision number (so each new version is
// a multi-line change) and which grows by one line per revision (so a v1->vN diff has many added
// rows). The 400-char unbroken token stresses word-wrap: if it ever stops wrapping, the page
// overflows horizontally and the overflow assertions below fail.
function longContent(rev: number): string {
  const lines: string[] = [
    "You are PromptForge Assistant, a meticulous senior engineer.",
    "Operate under the following standing rules:",
    "",
    `1. Cite file:line for every code reference (revision ${rev}).`,
    "2. Prefer clarity over cleverness; spell out the trade-offs.",
    "3. Never invent APIs; verify against the provided context first.",
    `4. When unsure, say so and stop — no bluffing (since revision ${rev}).`,
    "5. Keep each answer scoped to exactly what was asked.",
    "",
    `Reference token (wrap stress): ${"x".repeat(400)}`,
    "",
    "Worked example:",
    "  Input: summarize the change log below.",
    "  Output: a three-bullet summary, newest first.",
  ];
  for (let i = 1; i <= rev; i++) {
    lines.push(`Revision note ${i}: tightened guidance and added an example.`);
  }
  return lines.join("\n");
}

// A line unique to v1's content, used to prove the editor actually loaded the long version.
const MARKER = "meticulous senior engineer";

async function adminToken(api: APIRequestContext): Promise<string> {
  const res = await api.post(`${API}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const { access_token } = await res.json();
  return access_token;
}

// Seed a prompt with `revisions` versions of progressively-edited long content. Returns the name.
async function seedLongPrompt(
  api: APIRequestContext,
  name: string,
  revisions: number,
): Promise<void> {
  const token = await adminToken(api);
  const headers = { Authorization: `Bearer ${token}` };

  const create = await api.post(`${API}/prompts`, {
    headers,
    data: {
      name,
      description: "Long-content UX seed",
      content: longContent(1),
      input_variables: [],
      blocks: [],
    },
  });
  expect(create.ok(), "seed v1").toBeTruthy();

  for (let rev = 2; rev <= revisions; rev++) {
    const res = await api.post(`${API}/prompts/${name}/versions`, {
      headers,
      data: { content: longContent(rev), input_variables: [], blocks: [] },
    });
    expect(res.ok(), `seed v${rev}`).toBeTruthy();
  }
}

async function loginViaUi(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();
}

// The whole-page overflow check: long content must wrap, not push the layout wider than the
// viewport (which would produce a horizontal scrollbar and a broken-looking page).
async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "page should not scroll horizontally").toBeLessThanOrEqual(1);
}

test.describe("UX with heavy content", () => {
  test("a long multi-line prompt loads into the editor and wraps without horizontal overflow", async ({
    page,
  }) => {
    const api = await request.newContext();
    const name = `ux-long-${Date.now()}`;
    await seedLongPrompt(api, name, 1);

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);
    await page.goto(`/prompts/${name}/edit`);

    const content = page.getByLabel("Content");
    await expect(content).toBeVisible();
    const value = await content.inputValue();
    expect(value).toContain(MARKER);
    expect(value).toContain("x".repeat(400)); // the long unbroken token survived the round-trip

    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: "e2e/__screenshots__/ux-long-editor.png", fullPage: true });
  });

  test("many updates list newest-first in version history", async ({ page }) => {
    const api = await request.newContext();
    const name = `ux-many-${Date.now()}`;
    await seedLongPrompt(api, name, 5);

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);
    await page.goto(`/prompts/${name}/versions`);

    // The first table on the page is the version list (the diff renders its own table lower down).
    const rows = page.locator("table").first().locator("tbody > tr");
    await expect(rows).toHaveCount(5);
    // Newest-first: v5 at the top, v1 at the bottom.
    await expect(rows.first().locator("td").first()).toHaveText("v5");
    await expect(rows.last().locator("td").first()).toHaveText("v1");

    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: "e2e/__screenshots__/ux-many-versions.png", fullPage: true });
  });

  test("multi-line edits render as multiple added/removed diff rows, contained to the page width", async ({
    page,
  }) => {
    const api = await request.newContext();
    const name = `ux-diff-${Date.now()}`;
    await seedLongPrompt(api, name, 5);

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);
    await page.goto(`/prompts/${name}/versions`);

    const added = page.locator('[data-diff-type="added"]');
    const removed = page.locator('[data-diff-type="removed"]');

    // Default diff is the latest two versions (v4 vs v5): two changed lines + one appended line.
    await expect(added.first()).toBeVisible();
    await expect(removed.first()).toBeVisible();
    expect(await added.count()).toBeGreaterThanOrEqual(2);
    expect(await removed.count()).toBeGreaterThanOrEqual(2);

    // Widen the comparison to v1 -> v5: four appended lines + the two changed lines.
    await page.getByLabel("Diff from version").selectOption("1");
    await expect.poll(() => added.count()).toBeGreaterThanOrEqual(5);

    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: "e2e/__screenshots__/ux-multiline-diff.png", fullPage: true });
  });

  test("a fresh long prompt's dashboard shows truthful empty states (no runs, nothing to evaluate)", async ({
    page,
  }) => {
    // With no traces seeded, observability and eval both have nothing to show. The UI should say so
    // plainly rather than render empty tables — this pins those copy/empty states.
    const api = await request.newContext();
    const name = `ux-empty-${Date.now()}`;
    await seedLongPrompt(api, name, 3);

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);
    await page.goto(`/prompts/${name}/dashboard`);

    await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();
    await expect(page.getByText(/no executions recorded in this window/i)).toBeVisible();
    await expect(page.getByRole("heading", { name: "Eval scores" })).toBeVisible();
    await expect(page.getByText(/no versions to evaluate yet/i)).toBeVisible();

    await page.screenshot({ path: "e2e/__screenshots__/ux-dashboard-empty.png", fullPage: true });
  });

  test("eval scorer breakdown steps through every evaluated version", async ({ page }) => {
    // The populated eval surface needs a prompt whose traces + eval runs are already seeded (the
    // async worker pipeline does that in a healthy stack). Skipped, not failed, when SMOKE_PROMPT
    // is absent — so it doesn't break the self-seeding CI e2e run.
    const prompt = process.env.SMOKE_PROMPT ?? "";
    test.skip(prompt === "", "set SMOKE_PROMPT to a seeded prompt to run the eval-detail test");

    await page.setViewportSize(DESKTOP);
    await loginViaUi(page);
    await page.goto(`/prompts/${prompt}/dashboard`);

    await expect(page.getByRole("heading", { name: "Quality by version" })).toBeVisible();

    // Step the detail selector through every version and confirm the breakdown re-renders each time.
    const selector = page.getByLabel("Eval detail version");
    const values = await selector.locator("option").evaluateAll((opts) =>
      (opts as HTMLOptionElement[]).map((o) => o.value),
    );
    expect(values.length).toBeGreaterThan(0);
    for (const v of values) {
      await selector.selectOption(v);
      await expect(page.getByRole("heading", { name: "Scorer breakdown" })).toBeVisible();
    }
    await page.screenshot({ path: "e2e/__screenshots__/ux-eval-stepthrough.png", fullPage: true });
  });
});
