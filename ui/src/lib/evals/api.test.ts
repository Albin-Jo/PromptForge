import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "../api";
import { evalKeys, triggerEval, useTriggerEval } from "./api";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

describe("triggerEval", () => {
  it("POSTs to the version evaluate endpoint", async () => {
    mockedFetch.mockResolvedValue({ eval_run_id: "r1", status: "pending" } as never);
    await triggerEval("p", 2);
    expect(mockedFetch).toHaveBeenCalledWith("/prompts/p/versions/2/evaluate", { method: "POST" });
  });
});

describe("useTriggerEval", () => {
  it("invalidates that version's eval status on success", async () => {
    mockedFetch.mockResolvedValue({ eval_run_id: "r1", status: "pending" } as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);

    const { result } = renderHook(() => useTriggerEval("p"), { wrapper });
    result.current.mutate(2);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: evalKeys.detail("p", 2) });
  });
});
