import { expect, request, type APIRequestContext, type Page } from "@playwright/test";

// ──────────────────────────────────────────────────────────────────────────────────────────
// Shared e2e helpers.
//
// The specs in this folder repeatedly (a) sign in through the real login form and (b) seed
// fixtures straight through the API (JWT) so a UI flow has something to act on without waiting
// on the async worker pipeline. Both live here so the specs stay about the *behaviour under
// test*, not the plumbing. This file is imported by the specs; it is deliberately not named
// `*.spec.ts` so Playwright never treats it as a test file.
//
// Everything targets the local dev stack the other specs assume:
//   docker compose up -d      # API on :8001, its deps
//   cd ui && npm run test:e2e  # Playwright starts the UI dev server on :5173 itself
// ──────────────────────────────────────────────────────────────────────────────────────────

// The dev bootstrap admin seeded by docker-compose.override.yml.
export const ADMIN_EMAIL = "admin@promptforge.dev";
export const ADMIN_PASSWORD = "devpassword123";

// The API base the UI talks to. Overridable so a non-default stack still works.
export const API = process.env.API_BASE_URL ?? "http://localhost:8001";

// Common viewports, shared by the layout/responsive assertions.
export const MOBILE = { width: 375, height: 812 } as const; // iPhone-ish portrait
export const TABLET = { width: 768, height: 1024 } as const; // iPad-ish portrait
export const DESKTOP = { width: 1440, height: 900 } as const;
export const WIDE = { width: 1700, height: 1000 } as const; // wider than the 1536 dashboard cap

// A per-run-unique suffix so repeated runs never collide on a unique-name constraint. Date.now()
// alone can repeat within the same millisecond across fast back-to-back seeds, so mix in a counter.
let seq = 0;
export function uniqueName(prefix: string): string {
  seq += 1;
  return `${prefix}-${Date.now()}-${seq}`;
}

// ── API seeding ─────────────────────────────────────────────────────────────────────────────

/** A fresh API request context (its own cookie/header jar). Remember to dispose it if long-lived. */
export function apiContext(): Promise<APIRequestContext> {
  return request.newContext();
}

/** Log in via the API and return a bearer access token. Defaults to the bootstrap admin. */
export async function apiToken(
  api: APIRequestContext,
  email = ADMIN_EMAIL,
  password = ADMIN_PASSWORD,
): Promise<string> {
  const res = await api.post(`${API}/auth/login`, { data: { email, password } });
  expect(res.ok(), `API login for ${email}`).toBeTruthy();
  const { access_token } = await res.json();
  return access_token as string;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

/** Create a prompt (version 1). Returns the name. */
export async function seedPrompt(
  api: APIRequestContext,
  token: string,
  opts: { name: string; content: string; inputVariables?: string[]; description?: string },
): Promise<string> {
  const res = await api.post(`${API}/prompts`, {
    headers: authHeaders(token),
    data: {
      name: opts.name,
      description: opts.description ?? "e2e seed prompt",
      content: opts.content,
      input_variables: opts.inputVariables ?? [],
      blocks: [],
    },
  });
  expect(res.ok(), `seed prompt ${opts.name}`).toBeTruthy();
  return opts.name;
}

/** Append a new immutable version to an existing prompt. */
export async function seedPromptVersion(
  api: APIRequestContext,
  token: string,
  name: string,
  opts: { content: string; inputVariables?: string[] },
): Promise<void> {
  const res = await api.post(`${API}/prompts/${encodeURIComponent(name)}/versions`, {
    headers: authHeaders(token),
    data: { content: opts.content, input_variables: opts.inputVariables ?? [], blocks: [] },
  });
  expect(res.ok(), `seed version for ${name}`).toBeTruthy();
}

/** Create a composable block. Returns the name. */
export async function seedBlock(
  api: APIRequestContext,
  token: string,
  opts: {
    name: string;
    role?: "role" | "context" | "guardrails" | "output_format" | "other";
    content: string;
    description?: string;
  },
): Promise<string> {
  const res = await api.post(`${API}/blocks`, {
    headers: authHeaders(token),
    data: {
      name: opts.name,
      role: opts.role ?? "guardrails",
      description: opts.description ?? "e2e seed block",
      content: opts.content,
      input_variables: [],
      blocks: [],
    },
  });
  expect(res.ok(), `seed block ${opts.name}`).toBeTruthy();
  return opts.name;
}

/** Create a golden set (dataset) with N cases. Returns the name. */
export async function seedDataset(
  api: APIRequestContext,
  token: string,
  opts: {
    name: string;
    items: { input: string; reference?: string }[];
    description?: string;
  },
): Promise<string> {
  const res = await api.post(`${API}/datasets`, {
    headers: authHeaders(token),
    data: {
      name: opts.name,
      description: opts.description ?? "e2e seed golden set",
      items: opts.items.map((i) => ({ input: i.input, reference: i.reference ?? null, metadata: null })),
    },
  });
  expect(res.ok(), `seed dataset ${opts.name}`).toBeTruthy();
  return opts.name;
}

/**
 * Create a user with a role. Roles the UI/API accept are "editor" and "admin"; "editor" is the
 * non-admin role we use to prove admin-gating. Returns the created credentials for a UI login.
 */
export async function seedUser(
  api: APIRequestContext,
  token: string,
  opts: { email: string; password: string; role: "editor" | "admin" },
): Promise<{ email: string; password: string; role: "editor" | "admin" }> {
  const res = await api.post(`${API}/auth/users`, {
    headers: authHeaders(token),
    data: { email: opts.email, password: opts.password, role: opts.role },
  });
  expect(res.ok(), `seed ${opts.role} ${opts.email}`).toBeTruthy();
  return opts;
}

// ── UI login ─────────────────────────────────────────────────────────────────────────────────

/**
 * Sign in through the real login form.
 *
 * The landing page depends on how you arrived: a direct visit to /login returns to "/" (the
 * Overview), while a guard-bounced visit returns to the page you were denied. So instead of
 * asserting a specific heading, we wait for the authenticated app *shell* — the "Prompts" sidebar
 * link, which every signed-in role sees — to confirm we're through.
 */
export async function loginViaUi(
  page: Page,
  email = ADMIN_EMAIL,
  password = ADMIN_PASSWORD,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in/i }).click();
  // A generous timeout: the login round-trip + first authed render can occasionally run past the
  // default 5s under back-to-back logins across a suite.
  await expect(page).not.toHaveURL(/\/login$/, { timeout: 15_000 });
  await expect(page.getByRole("link", { name: "Prompts", exact: true }).first()).toBeVisible({
    timeout: 15_000,
  });
}

// ── Layout assertions ──────────────────────────────────────────────────────────────────────────

/**
 * The whole-page overflow check: content must wrap/contain, never push the layout wider than the
 * viewport (which would produce a horizontal scrollbar and a broken-looking page). A 1px slack
 * absorbs sub-pixel rounding.
 */
export async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, "page should not scroll horizontally").toBeLessThanOrEqual(1);
}
