import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// Keep the real ApiError so useSetLabel's onError classifiers work; stub only the network call.
import { ApiError } from "../lib/api";
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  apiFetch: vi.fn(),
}));
import { apiFetch } from "../lib/api";
import { PromoteDialog } from "./PromoteDialog";

const mockedFetch = vi.mocked(apiFetch);

function renderDialog(canPromote: boolean) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return render(<PromoteDialog name="p" versionNumber={3} canPromote={canPromote} />, { wrapper });
}

beforeEach(() => vi.clearAllMocks());

describe("PromoteDialog gating", () => {
  it("disables Promote for non-admins", () => {
    renderDialog(false);
    expect(screen.getByRole("button", { name: /promote/i })).toBeDisabled();
  });

  it("enables Promote for admins", () => {
    renderDialog(true);
    expect(screen.getByRole("button", { name: /promote/i })).toBeEnabled();
  });
});

describe("PromoteDialog 409-blocked", () => {
  it("renders the per-metric gate detail instead of a generic error", async () => {
    // The gate refuses with a 409 carrying the per-scorer deltas.
    mockedFetch.mockRejectedValue(
      new ApiError(409, "candidate regressed", {
        detail: "candidate regressed",
        promotion: {
          allowed: false,
          reasons: ["llm_judge regressed vs production"],
          regression_checked: true,
          deltas: [
            { scorer: "llm_judge", candidate: 0.6, baseline: 0.9, drop: 0.3, floor_ok: true, regression: true },
          ],
          eval_run_id: "run-1",
          candidate_summary: null,
          production_eval_run_id: "run-0",
          from_version: 2,
          to_version: 3,
        },
      }),
    );

    const user = userEvent.setup();
    renderDialog(true);

    await user.click(screen.getByRole("button", { name: /promote/i }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^promote$/i }));

    // The blocked state: a refusal banner + the offending scorer + reason, not a thrown error.
    expect(await within(dialog).findByText(/blocked by gate/i)).toBeInTheDocument();
    expect(within(dialog).getByText("llm_judge")).toBeInTheDocument();
    expect(within(dialog).getByText(/regressed vs production/i)).toBeInTheDocument();
    // The per-metric status badge for the failing scorer (exact text, distinct from the reason line).
    expect(within(dialog).getByText("regressed")).toBeInTheDocument();
  });
});
