import { expect, test, type Page } from "@playwright/test";

// ──────────────────────────────────────────────────────────────────────────────────────────
// PromptForge guided dashboard tour.
//
// A *watchable* walkthrough of the dashboard — not an assertion suite. It drives the real UI the
// way a person would (login → overview → a prompt → versions/diff → dashboard → scan → playground
// → command palette + theme) and **pauses 1s before each section** so a viewer (or a screen
// recording) can follow along. The Playwright config already runs headed, maximized, with a
// ~900ms per-action slowMo; this spec layers the 1s section pauses on top.
//
// It is read-only on already-seeded data. Run the seed first (see demo/dashboard-tour.md):
//     docker compose up -d
//     uv run python api/scripts/seed_demo_data.py
//     cd ui && npm run test:e2e:demo
//
// TOUR_PROMPT picks which seeded prompt to tour. The default, `rag-answerer`, is the richest one:
// two versions to diff, a golden set (so eval scores exist), and real security findings on v1.
// ──────────────────────────────────────────────────────────────────────────────────────────
const ADMIN_EMAIL = "admin@promptforge.dev";
const ADMIN_PASSWORD = "devpassword123";
const TOUR_PROMPT = process.env.TOUR_PROMPT ?? "rag-answerer";

// This is a paced tour with many 1s pauses + slowMo, so give it room.
test.describe.configure({ timeout: 240_000 });

// Narrate a section to stdout and pause 1s so each step is easy to follow on screen.
async function step(page: Page, title: string, narration: string): Promise<void> {
  // eslint-disable-next-line no-console
  console.log(`\n▶ ${title}\n  ${narration}`);
  await page.waitForTimeout(1000);
}

test("guided dashboard tour", async ({ page }) => {
  // ── 1. Sign in ─────────────────────────────────────────────────────────────────────────
  await step(
    page,
    "Sign in",
    "The dashboard sits behind JWT auth (roles: viewer / editor / admin). We log in as the admin.",
  );
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  // Fail fast with a clear message if the seed wasn't run — the whole tour depends on it.
  await page.goto("/prompts");
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();
  const promptLink = page.getByRole("link", { name: TOUR_PROMPT, exact: true });
  await expect(
    promptLink,
    `Seed data missing: no "${TOUR_PROMPT}" prompt. Run: uv run python api/scripts/seed_demo_data.py`,
  ).toBeVisible();

  // ── 2. Fleet overview ──────────────────────────────────────────────────────────────────
  await step(
    page,
    "Fleet overview",
    "The landing page: total requests, error rate, and spend across every prompt, with traffic/cost " +
      "trends. 'Needs attention' surfaces prompts tripping a health rule (errors, evals, scans).",
  );
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  // "Needs attention" is a card title (a div), not a semantic heading.
  await expect(page.getByText("Needs attention", { exact: true })).toBeVisible();

  await step(
    page,
    "Change the time window",
    "Every observability surface shares one window control. Switching it re-queries the metrics — " +
      "here we widen the fleet view from 7 days to 30.",
  );
  await page.getByRole("group", { name: "Time window" }).getByRole("button", { name: "30d" }).click();
  await expect(page.getByText("Needs attention", { exact: true })).toBeVisible();

  // ── 3. Prompt registry ─────────────────────────────────────────────────────────────────
  await step(
    page,
    "Prompt registry",
    "Every prompt is a tracked asset. The list is the registry; clicking one opens its editor.",
  );
  await page.getByRole("link", { name: "Prompts", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();

  // ── 4. The editor + composition ────────────────────────────────────────────────────────
  await step(
    page,
    `Open "${TOUR_PROMPT}" in the editor`,
    "Prompts are composed from reusable blocks (roles, guardrails, output formats) pinned to a " +
      "version. Editing here doesn't mutate a version — saving creates the next immutable one.",
  );
  await page.getByRole("link", { name: TOUR_PROMPT, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/prompts/${TOUR_PROMPT}/edit$`));
  await expect(page.getByLabel("Content")).toBeVisible();

  // ── 5. Version history + diff ──────────────────────────────────────────────────────────
  await step(
    page,
    "Version history & diff",
    "Immutable versions, newest first. Pick any two and the diff highlights added/removed lines — " +
      "this is the audit trail of how a prompt evolved.",
  );
  await page.getByRole("link", { name: "Versions", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/prompts/${TOUR_PROMPT}/versions$`));
  await expect(page.getByRole("cell", { name: "v1", exact: true }).first()).toBeVisible();
  await expect(page.locator('[data-diff-type="added"]').first()).toBeVisible();
  await expect(page.locator('[data-diff-type="removed"]').first()).toBeVisible();

  // ── 6. Per-prompt dashboard: observability + eval ──────────────────────────────────────
  await step(
    page,
    "Observability dashboard",
    "Latency (p50/p95/p99), cost, and error rate — broken out per version, so a regression is " +
      "attributable to the exact version that shipped it.",
  );
  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();
  // "By version" is a card title (a div), not a semantic heading.
  await expect(page.getByText("By version", { exact: true })).toBeVisible();

  await step(
    page,
    "Eval scores",
    "Quality is a real number, not a vibe: each version is graded against a golden set by named " +
      "scorers (e.g. llm_judge). Quality-by-version is what the promotion gate checks before a deploy.",
  );
  await expect(page.getByRole("heading", { name: "Eval scores" })).toBeVisible();
  // "Quality by version" is a card title (a div), not a semantic heading.
  await expect(page.getByText("Quality by version", { exact: true })).toBeVisible();

  // ── 7. Security scan results ───────────────────────────────────────────────────────────
  await step(
    page,
    "Security scan results",
    "Every version is scanned for prompt-injection, jailbreaks, PII, and leaked secrets. Findings " +
      "come with a redacted evidence snippet and a risk level. v1 has real findings to show.",
  );
  await page.goto(`/prompts/${TOUR_PROMPT}/versions/1/scan`);
  await expect(page.getByRole("heading", { name: /security scan/i })).toBeVisible();
  await expect(page.getByText("Risk level")).toBeVisible();

  // ── 8. Playground (streaming) ──────────────────────────────────────────────────────────
  await step(
    page,
    "Live playground",
    "Render a version with real inputs and run it through the LiteLLM gateway — tokens stream back " +
      "over SSE. (Without a provider key the stream resolves to a clean 'Error', which still proves " +
      "the gateway + streaming path end to end.)",
  );
  await page.goto(`/prompts/${TOUR_PROMPT}/versions`);
  await page.getByRole("link", { name: "Playground →" }).first().click();
  await expect(page).toHaveURL(/\/playground$/);

  const model = page.getByLabel("Model");
  if ((await model.inputValue()) === "") {
    await model.fill("openai/gpt-4o-mini");
  }
  // Fill whatever input variables this version declares with sample text.
  const inputs = page.locator("textarea");
  const count = await inputs.count();
  for (let i = 0; i < count; i++) {
    await inputs.nth(i).fill("What is PromptForge and why does versioning prompts matter?");
  }
  await page.getByRole("button", { name: /^run$/i }).click();
  await expect(page.getByText(/^(Done|Error)$/)).toBeVisible({ timeout: 30_000 });

  // ── 9. Command palette + theme ─────────────────────────────────────────────────────────
  await step(
    page,
    "Command palette (⌘K) & theme",
    "Press ⌘K from anywhere to jump to a prompt or a section. And the whole app follows a light/dark " +
      "theme toggle.",
  );
  await page.getByRole("button", { name: /search/i }).first().click();
  await page.getByPlaceholder(/type a command or search prompts/i).fill(TOUR_PROMPT);
  await expect(page.getByRole("option", { name: new RegExp(TOUR_PROMPT) }).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /switch to (dark|light) mode/i }).click();

  // ── Honest close: what the API can do that this dashboard can't (yet) ───────────────────
  await step(
    page,
    "What's API-only (not yet in the dashboard)",
    "Honest gaps — these backend features have no UI: promoting a label (the gated deploy), " +
      "triggering an eval or a scan on demand, managing datasets/golden sets, authoring blocks, " +
      "the per-prompt drift alerts feed, and user management. They run via the API / worker / seed.",
  );
});
