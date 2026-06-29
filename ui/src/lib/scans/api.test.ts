import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "../api";
import { scanKeys, triggerScan, useTriggerScan } from "./api";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

describe("triggerScan", () => {
  it("POSTs to the version scan endpoint", async () => {
    mockedFetch.mockResolvedValue({ security_scan_id: "s1", status: "pending" } as never);
    await triggerScan("p", 2);
    expect(mockedFetch).toHaveBeenCalledWith("/prompts/p/versions/2/scan", { method: "POST" });
  });
});

describe("useTriggerScan", () => {
  it("invalidates that version's scan status on success", async () => {
    mockedFetch.mockResolvedValue({ security_scan_id: "s1", status: "pending" } as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);

    const { result } = renderHook(() => useTriggerScan("p"), { wrapper });
    result.current.mutate(2);

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: scanKeys.detail("p", 2) });
  });
});
