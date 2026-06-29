import { expect, request, test } from "@playwright/test";

// The Sprint 15 DoD demo, end to end in a real browser:
//   compose a prompt from a block -> save a second version -> diff the two versions ->
//   open the playground and run it (streaming).
//
// The happy-path token stream needs a provider key (OPENAI_API_KEY) on the API. Without
// one, /complete streams back an `error` event — which still exercises the full SSE
// consumption path, so this test asserts the playground renders whichever the stack
// returns: streamed output, or the streamed error.
const ADMIN_EMAIL = "admin@promptforge.dev";
const ADMIN_PASSWORD = "devpassword123";
const API = "http://localhost:8000";

test("compose, diff two versions, and run the playground", async ({ page }) => {
  const stamp = Date.now();
  const promptName = `e2e-s15-${stamp}`;
  const blockName = `e2e-block-${stamp}`;

  // --- setup: seed a block via the API so the composition picker has something to add ---
  const api = await request.newContext();
  const login = await api.post(`${API}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  const { access_token } = await login.json();
  const block = await api.post(`${API}/blocks`, {
    headers: { Authorization: `Bearer ${access_token}` },
    data: {
      name: blockName,
      role: "guardrails",
      description: "e2e seed block",
      content: "Be concise.",
      input_variables: [],
      blocks: [],
    },
  });
  expect(block.ok()).toBeTruthy();

  // --- log in via the UI ---
  await page.goto("/login");
  await page.getByLabel("Email").fill(ADMIN_EMAIL);
  await page.getByLabel("Password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();

  // --- create the prompt (version 1) ---
  await page.getByRole("link", { name: /new prompt/i }).click();
  await page.getByLabel("Name").fill(promptName);
  await page.getByLabel("Content").fill("Summarize {{text}}");
  await page.getByLabel("Input variables").fill("text");
  await page.getByRole("button", { name: /create prompt/i }).click();
  await expect(page).toHaveURL(/\/$/);

  // --- edit: compose the block in + change content -> save version 2 ---
  await page.getByRole("link", { name: promptName }).click();
  await page.getByLabel("Add a block").selectOption(blockName);
  await page.getByRole("button", { name: /add block/i }).click();
  await expect(page.getByLabel(`Pinned version for ${blockName}`)).toBeVisible();
  await page.getByLabel("Content").fill("Summarize concisely: {{text}}");
  await page.getByRole("button", { name: /save new version/i }).click();
  await expect(page).toHaveURL(/\/$/);

  // --- version history: the two versions diff with added + removed rows ---
  await page.getByRole("link", { name: promptName }).click();
  // Sprint 16 replaced the ad-hoc "Version history →" link with the PromptTabs "Versions" tab.
  await page.getByRole("link", { name: "Versions", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/prompts/${promptName}/versions$`));
  await expect(page.locator('[data-diff-type="added"]').first()).toBeVisible();
  await expect(page.locator('[data-diff-type="removed"]').first()).toBeVisible();

  // --- playground: run the newest version and watch the stream resolve ---
  await page.getByRole("link", { name: /playground/i }).first().click();
  await expect(page).toHaveURL(/\/playground$/);

  const modelInput = page.getByLabel("Model");
  if ((await modelInput.inputValue()) === "") {
    await modelInput.fill("openai/gpt-4o-mini");
  }
  await page.getByLabel("text", { exact: true }).fill("hello world");
  await page.getByRole("button", { name: /^run$/i }).click();

  // The stream resolves to a terminal status: "Done" (with a provider key) or "Error"
  // (without one). Either proves the SSE consumption path ran end to end.
  await expect(page.getByText(/^(Done|Error)$/)).toBeVisible({ timeout: 30_000 });
});
