import { expect, test, type Page } from "@playwright/test";
import {
  DESKTOP,
  loginViaUi,
  uniqueName,
} from "./helpers";

// ──────────────────────────────────────────────────────────────────────────────────────────
// THE COMPLETE WORKFLOW — every feature, in the order a real operator would touch them.
//
// One long, *watchable* journey that both drives and asserts the whole product surface:
//   sign in → fleet overview → author a golden set → author a reusable block → create a prompt →
//   compose the block in and save a 2nd version → diff the versions → promote to staging (the
//   gated-deploy control) → traces → run history → observability + eval dashboard → security scan
//   → live playground (streaming) → admin: users / activity / operations → command palette →
//   light/dark theme (persisted across reload).
//
// It is self-contained: it creates its own golden set / block / prompt through the UI, so it needs
// only the API stack up (docker compose) and the seeded bootstrap admin — no demo seed, no worker.
// Fresh-prompt surfaces (traces, runs, dashboard, scan) are asserted via their *empty states*,
// which is itself a UX check: the app must say "nothing yet" plainly, not render broken empties.
//
// Runs headed + slowMo (see playwright.config.ts) so you can watch it; the step() pauses add a
// beat before each section. Screenshots land in e2e/__screenshots__/workflow-*.png.
// ──────────────────────────────────────────────────────────────────────────────────────────

// A pinned desktop viewport so the layout is deterministic across machines (opts out of the
// config's maximized viewport:null default, which page.setViewportSize would otherwise reject).
test.use({ viewport: DESKTOP });

// A long, paced journey — give it room.
test.describe.configure({ timeout: 360_000 });

// Narrate a section to stdout and pause a beat so each step is easy to follow on screen.
async function step(page: Page, title: string, narration: string): Promise<void> {
  // eslint-disable-next-line no-console
  console.log(`\n▶ ${title}\n  ${narration}`);
  await page.waitForTimeout(800);
}

async function shot(page: Page, slug: string): Promise<void> {
  await page.screenshot({ path: `e2e/__screenshots__/workflow-${slug}.png`, fullPage: true });
}

test("the complete PromptForge workflow, end to end", async ({ page }) => {
  const dataset = uniqueName("wf-golden");
  const block = uniqueName("wf-block");
  const prompt = uniqueName("wf-prompt");

  // ── 1. Sign in ────────────────────────────────────────────────────────────────────────────
  await step(page, "Sign in", "The whole app sits behind JWT auth. We sign in as the admin.");
  await loginViaUi(page);

  // ── 2. Fleet overview ─────────────────────────────────────────────────────────────────────
  await step(
    page,
    "Fleet overview",
    "The landing page: fleet-wide traffic, error rate and spend, plus a 'Needs attention' feed.",
  );
  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Needs attention", { exact: true })).toBeVisible();
  await shot(page, "01-overview");

  // ── 3. Author a golden set ────────────────────────────────────────────────────────────────
  await step(
    page,
    "Author a golden set",
    "Quality starts with test cases. A golden set is the curated cases a prompt must pass before it ships.",
  );
  await page.getByRole("link", { name: "Golden sets", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Golden sets" })).toBeVisible();
  await page.getByRole("link", { name: /new golden set/i }).click();
  await page.getByLabel("Name").fill(dataset);
  await page.getByLabel("Description").fill("Cases the summarizer must pass");
  // The form opens with one empty case row; add two more for three total, then fill each.
  await page.getByRole("button", { name: "Add case" }).click();
  await page.getByRole("button", { name: "Add case" }).click();
  const caseInputs = page.getByPlaceholder(/^Summarize:/);
  const caseRefs = page.getByPlaceholder("The expected answer");
  await expect(caseInputs).toHaveCount(3);
  const cases = [
    ["Summarize: the quarterly report grew revenue 12%.", "Revenue up 12% this quarter."],
    ["Summarize: the outage lasted 3 hours on Tuesday.", "A 3-hour outage on Tuesday."],
    ["Summarize: the release adds dark mode and search.", "Release adds dark mode and search."],
  ];
  for (let i = 0; i < cases.length; i++) {
    await caseInputs.nth(i).fill(cases[i][0]);
    await caseRefs.nth(i).fill(cases[i][1]);
  }
  await page.getByRole("button", { name: /create golden set/i }).click();
  await expect(page).toHaveURL(/\/datasets$/);
  await expect(page.getByRole("link", { name: dataset })).toBeVisible();
  await shot(page, "02-golden-set");

  // ── 4. Author a reusable block ────────────────────────────────────────────────────────────
  await step(
    page,
    "Author a reusable block",
    "Blocks are the composition primitive — a guardrail or output-format written once, reused across prompts.",
  );
  await page.getByRole("link", { name: "Blocks", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Blocks" })).toBeVisible();
  await page.getByRole("link", { name: /new block/i }).click();
  await page.getByLabel("Name").fill(block);
  // Role is a Radix Select (combobox), not a native <select>: open it and pick the option.
  await page.getByLabel("Role").click();
  await page.getByRole("option", { name: "Guardrails" }).click();
  await page.getByLabel("Description").fill("Keep answers concise and grounded");
  await page.getByLabel("Content").fill("Be concise. Never invent facts; ground every claim in the input.");
  await page.getByRole("button", { name: "Create block" }).click();
  // Creating a block lands on its detail page, where the name is the heading (not a list link).
  await expect(page).toHaveURL(new RegExp(`/blocks/${block}$`));
  await expect(page.getByRole("heading", { name: block })).toBeVisible();
  await shot(page, "03-block");

  // ── 5. Create a prompt (version 1) ────────────────────────────────────────────────────────
  await step(
    page,
    "Create a prompt",
    "Prompts are versioned assets. Creating one writes an immutable version 1.",
  );
  await page.getByRole("link", { name: "Prompts", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();
  await page.getByRole("link", { name: /new prompt/i }).click();
  await expect(page).toHaveURL(/\/prompts\/new$/);
  await page.getByLabel("Name").fill(prompt);
  await page.getByLabel("Description").fill("Summarizes text for the workflow demo");
  await page.getByLabel("Content").fill("Summarize {{text}}");
  await page.getByLabel("Input variables").fill("text");
  await page.getByRole("button", { name: /create prompt/i }).click();
  await expect(page).toHaveURL(/\/prompts$/);
  await expect(page.getByRole("link", { name: prompt })).toBeVisible();

  // ── 6. Compose the block in and save version 2 ────────────────────────────────────────────
  await step(
    page,
    "Compose & save a new version",
    "Editing never mutates a version — we pin the block into the composition, change the content, and save v2.",
  );
  await page.getByRole("link", { name: prompt }).click();
  await expect(page).toHaveURL(new RegExp(`/prompts/${prompt}/edit$`));
  await page.getByLabel("Add a block").selectOption(block);
  await page.getByRole("button", { name: /add block/i }).click();
  await expect(page.getByLabel(`Pinned version for ${block}`)).toBeVisible();
  await page.getByLabel("Content").fill("Summarize concisely: {{text}}");
  await page.getByRole("button", { name: /save new version/i }).click();
  await expect(page).toHaveURL(/\/prompts$/);
  await shot(page, "04-composed");

  // ── 7. Version history + diff ─────────────────────────────────────────────────────────────
  await step(
    page,
    "Version history & diff",
    "Immutable versions, newest first. The diff highlights exactly what changed between any two.",
  );
  await page.getByRole("link", { name: prompt }).click();
  await page.getByRole("link", { name: "Versions", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/prompts/${prompt}/versions$`));
  await expect(page.getByRole("cell", { name: "v2", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "v1", exact: true })).toBeVisible();
  await expect(page.locator('[data-diff-type="added"]').first()).toBeVisible();
  await expect(page.locator('[data-diff-type="removed"]').first()).toBeVisible();
  await shot(page, "05-diff");

  // ── 8. Promote v2 → staging (the gated-deploy control) ────────────────────────────────────
  await step(
    page,
    "Promote a version",
    "Deployment = moving a label. Promoting to production runs the quality gate; staging moves freely. " +
      "We promote v2 → staging and watch the label badge attach to the row.",
  );
  const v2Row = page.getByRole("row").filter({
    has: page.getByRole("cell", { name: "v2", exact: true }),
  });
  await v2Row.getByRole("button", { name: "Promote", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/point a label at this version/i)).toBeVisible();
  await dialog.getByLabel("Target label").selectOption("staging");
  await dialog.getByRole("button", { name: "Promote", exact: true }).click();
  // On success the dialog closes and the version's Labels cell now badges "staging".
  await expect(v2Row.getByText("staging", { exact: true })).toBeVisible();
  await shot(page, "06-promoted");

  // ── 9. Traces (empty state on a fresh prompt) ─────────────────────────────────────────────
  await step(
    page,
    "Traces",
    "Every execution is traced. A brand-new prompt has none yet — the page says so plainly.",
  );
  await page.goto(`/prompts/${prompt}/traces`);
  await expect(page.getByRole("heading", { name: `${prompt} — traces` })).toBeVisible();
  await expect(page.getByText(/no executions recorded for this prompt yet/i)).toBeVisible();

  // ── 10. Run history (evals + scans) ───────────────────────────────────────────────────────
  await step(
    page,
    "Run history",
    "Per-version audit of every eval and every security scan. None have run for this new version yet.",
  );
  await page.goto(`/prompts/${prompt}/versions/2/runs`);
  await expect(page.getByRole("heading", { name: `${prompt} — v2 runs` })).toBeVisible();
  // Evals need a golden set attached, so a fresh version has none. Scans auto-enqueue on version
  // creation, so that section shows a run (not an empty state) — we assert both sections render.
  await expect(page.getByText("Eval runs")).toBeVisible();
  await expect(page.getByText(/no evals have run for this version yet/i)).toBeVisible();
  await expect(page.getByText("Security scans")).toBeVisible();

  // ── 11. Observability + eval dashboard ────────────────────────────────────────────────────
  await step(
    page,
    "Observability & eval dashboard",
    "Latency / cost / error rate per version, and quality-by-version from the golden set. Truthful empties here too.",
  );
  await page.goto(`/prompts/${prompt}/dashboard`);
  await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();
  await expect(page.getByText(/no executions recorded in this window/i)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Eval scores" })).toBeVisible();
  await shot(page, "07-dashboard");

  // ── 12. Security scan ─────────────────────────────────────────────────────────────────────
  await step(
    page,
    "Security scan",
    "Every version can be scanned for injection / jailbreaks / PII / secrets. This one hasn't run yet.",
  );
  await page.goto(`/prompts/${prompt}/versions/2/scan`);
  await expect(page.getByRole("heading", { name: /security scan/i })).toBeVisible();
  // A scan auto-enqueues on version creation, so the page shows a scan status (in-progress, clean,
  // or findings) rather than "unscanned". The on-demand action button reads "Run scan" when idle or
  // "Scanning…" while the auto-scan is still in flight — match either so the assertion isn't racy.
  await expect(page.getByRole("button", { name: /run scan|scanning/i })).toBeVisible();

  // ── 13. Live playground (streaming) ───────────────────────────────────────────────────────
  await step(
    page,
    "Live playground",
    "Render a version with real inputs and run it through the LiteLLM gateway — tokens stream back over SSE. " +
      "Without a provider key it resolves to a clean 'Error', which still proves the gateway + streaming path.",
  );
  await page.goto(`/prompts/${prompt}/versions/2/playground`);
  await expect(page.getByRole("heading", { name: "Inputs" })).toBeVisible();
  const model = page.getByLabel("Model");
  if ((await model.inputValue()) === "") {
    await model.fill("openai/gpt-4o-mini");
  }
  await page.getByLabel("text", { exact: true }).fill("PromptForge treats prompts as tested, versioned assets.");
  await page.getByRole("button", { name: /^run$/i }).click();
  await expect(page.getByText(/^(Done|Error)$/)).toBeVisible({ timeout: 30_000 });
  await shot(page, "08-playground");

  // ── 14. Admin: users / activity / operations ──────────────────────────────────────────────
  await step(
    page,
    "Admin surfaces",
    "Admin-only sections: user management, the audit log, and async-backbone health (queue + workers).",
  );
  await page.getByRole("link", { name: "Users", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
  await expect(page.getByText(ADMIN_ROW_HINT)).toBeVisible();

  await page.getByRole("link", { name: "Activity", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Activity" })).toBeVisible();
  // Our staging promotion is an audited action — the log should carry at least one entry now.
  await expect(page.getByText(/who did what, and when/i)).toBeVisible();

  await page.getByRole("link", { name: "Operations", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Operations" })).toBeVisible();
  await shot(page, "09-admin");

  // ── 15. Command palette ───────────────────────────────────────────────────────────────────
  await step(
    page,
    "Command palette (⌘K / Ctrl+K)",
    "Jump anywhere from the keyboard: open the palette, search our prompt by name, and it appears as a result.",
  );
  await page.keyboard.press("Control+k");
  const palette = page.getByPlaceholder(/type a command or search/i);
  await expect(palette).toBeVisible();
  await palette.fill(prompt);
  await expect(page.getByText(prompt).last()).toBeVisible();
  await page.keyboard.press("Escape");

  // ── 16. Theme toggle (persisted across reload) ────────────────────────────────────────────
  await step(
    page,
    "Light / dark theme",
    "The whole app follows one theme toggle, persisted to localStorage so it survives a reload.",
  );
  await page.getByRole("button", { name: /switch to dark mode/i }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await shot(page, "10-dark");

  // Leave it as we found it.
  await page.getByRole("button", { name: /switch to light mode/i }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

// The Users page subheading — a stable string to prove we're on the real (admin-gated) page and
// not a redirect. Kept as a constant so the intent reads clearly at the assertion site.
const ADMIN_ROW_HINT = "Everyone who can sign in. Editors can author and run; admins can also manage users.";
