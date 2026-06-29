import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

// Replace apiFetch but keep the real ApiError so the classifiers' `instanceof` checks still work.
import { ApiError } from "../api";
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  apiFetch: vi.fn(),
}));
import { apiFetch } from "../api";
import {
  asPromotionBlocked,
  asPromotionPending,
  promptKeys,
  resolveLabel,
  setLabel,
  useSetGoldenSet,
  useSetLabel,
} from "./api";
import type { PromotionBlockedBody, PromotionPendingBody } from "./types";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

describe("setLabel", () => {
  it("PUTs the version number to the label endpoint", async () => {
    mockedFetch.mockResolvedValue({} as never);
    await setLabel("my prompt", "production", 3);
    expect(mockedFetch).toHaveBeenCalledWith("/prompts/my%20prompt/labels/production", {
      method: "PUT",
      body: { version_number: 3 },
    });
  });
});

describe("resolveLabel", () => {
  it("returns null when the label is unset (404)", async () => {
    mockedFetch.mockRejectedValue(new ApiError(404, "not found", null));
    await expect(resolveLabel("p", "production")).resolves.toBeNull();
  });

  it("rethrows non-404 errors", async () => {
    mockedFetch.mockRejectedValue(new ApiError(500, "boom", null));
    await expect(resolveLabel("p", "production")).rejects.toThrow();
  });
});

describe("promotion 409 classifiers", () => {
  const promotion = {
    allowed: false,
    reasons: ["llm_judge dropped below floor"],
    regression_checked: true,
    deltas: [
      { scorer: "llm_judge", candidate: 0.6, baseline: 0.9, drop: 0.3, floor_ok: false, regression: true },
    ],
    eval_run_id: "run-1",
    candidate_summary: null,
    production_eval_run_id: "run-0",
    from_version: 2,
    to_version: 3,
  };

  it("recognises a blocked body (has `promotion`)", () => {
    const body: PromotionBlockedBody = { detail: "blocked", promotion };
    const err = new ApiError(409, "blocked", body);
    expect(asPromotionBlocked(err)?.promotion.deltas[0].scorer).toBe("llm_judge");
    expect(asPromotionPending(err)).toBeNull();
  });

  it("recognises a pending body (has a run id, no `promotion`)", () => {
    const body: PromotionPendingBody = { detail: "still running", eval_run_id: "run-9" };
    const err = new ApiError(409, "pending", body);
    expect(asPromotionPending(err)?.eval_run_id).toBe("run-9");
    expect(asPromotionBlocked(err)).toBeNull();
  });

  it("treats non-409s as neither", () => {
    const err = new ApiError(403, "forbidden", { detail: "nope" });
    expect(asPromotionBlocked(err)).toBeNull();
    expect(asPromotionPending(err)).toBeNull();
  });
});

describe("useSetLabel", () => {
  it("invalidates this prompt's label-badge queries on success", async () => {
    mockedFetch.mockResolvedValue({ name: "production", version: {} } as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);

    const { result } = renderHook(() => useSetLabel("p"), { wrapper });
    result.current.mutate({ label: "production", versionNumber: 2 });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // Label badges are invalidated by predicate (matches ["label", "p", <label>]).
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({ predicate: expect.any(Function) }),
    );
    // And the predicate matches this prompt's label keys (and not another prompt's).
    const call = invalidate.mock.calls.find((c) => typeof c[0]?.predicate === "function");
    const predicate = call![0]!.predicate!;
    expect(predicate({ queryKey: ["label", "p", "production"] } as never)).toBe(true);
    expect(predicate({ queryKey: ["label", "other", "production"] } as never)).toBe(false);
  });
});

describe("useSetGoldenSet", () => {
  function setup() {
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    return { client, invalidate, wrapper };
  }

  it("attaches via PUT and invalidates the prompt detail", async () => {
    mockedFetch.mockResolvedValue({ name: "p", golden_set_id: "id-gs" } as never);
    const { invalidate, wrapper } = setup();

    const { result } = renderHook(() => useSetGoldenSet("p"), { wrapper });
    result.current.mutate("gs");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedFetch).toHaveBeenCalledWith("/prompts/p/golden-set", {
      method: "PUT",
      body: { dataset: "gs" },
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: promptKeys.detail("p") });
  });

  it("detaches via DELETE when given null", async () => {
    mockedFetch.mockResolvedValue({ name: "p", golden_set_id: null } as never);
    const { invalidate, wrapper } = setup();

    const { result } = renderHook(() => useSetGoldenSet("p"), { wrapper });
    result.current.mutate(null);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedFetch).toHaveBeenCalledWith("/prompts/p/golden-set", { method: "DELETE" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: promptKeys.detail("p") });
  });
});
