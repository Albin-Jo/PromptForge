import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "../api";
import {
  blockKeys,
  createBlock,
  createBlockVersion,
  deleteBlock,
  getBlockVersion,
  listBlockVersions,
  useCreateBlock,
  useCreateBlockVersion,
  useDeleteBlock,
} from "./api";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

function wrapperWith(client: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
}

describe("block request functions hit the right endpoints", () => {
  it("listBlockVersions GETs the versions collection", async () => {
    mockedFetch.mockResolvedValue([] as never);
    await listBlockVersions("greeting");
    expect(mockedFetch).toHaveBeenCalledWith("/blocks/greeting/versions", { signal: undefined });
  });

  it("getBlockVersion GETs one version by number", async () => {
    mockedFetch.mockResolvedValue({} as never);
    await getBlockVersion("greeting", 2);
    expect(mockedFetch).toHaveBeenCalledWith("/blocks/greeting/versions/2", { signal: undefined });
  });

  it("createBlock POSTs to /blocks", async () => {
    mockedFetch.mockResolvedValue({} as never);
    const body = { name: "greeting", role: "role" as const, content: "Hi", input_variables: [], blocks: [] };
    await createBlock(body);
    expect(mockedFetch).toHaveBeenCalledWith("/blocks", { method: "POST", body });
  });

  it("createBlockVersion POSTs to the versions collection", async () => {
    mockedFetch.mockResolvedValue({} as never);
    const body = { content: "Hi v2", input_variables: [], blocks: [] };
    await createBlockVersion("greeting", body);
    expect(mockedFetch).toHaveBeenCalledWith("/blocks/greeting/versions", { method: "POST", body });
  });

  it("deleteBlock DELETEs the block", async () => {
    mockedFetch.mockResolvedValue(null as never);
    await deleteBlock("greeting");
    expect(mockedFetch).toHaveBeenCalledWith("/blocks/greeting", { method: "DELETE" });
  });
});

describe("block mutations invalidate the catalog", () => {
  it("useCreateBlock invalidates the block list (so the picker sees it)", async () => {
    mockedFetch.mockResolvedValue({} as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateBlock(), { wrapper: wrapperWith(client) });
    result.current.mutate({ name: "g", role: "role", content: "Hi", input_variables: [], blocks: [] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: blockKeys.all });
  });

  it("useCreateBlockVersion invalidates the list, detail, and version history", async () => {
    mockedFetch.mockResolvedValue({} as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateBlockVersion("g"), { wrapper: wrapperWith(client) });
    result.current.mutate({ content: "Hi v2", input_variables: [], blocks: [] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: blockKeys.all });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: blockKeys.detail("g") });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: blockKeys.versions("g") });
  });

  it("useDeleteBlock invalidates the catalog (so the list + picker drop it)", async () => {
    mockedFetch.mockResolvedValue(null as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteBlock(), { wrapper: wrapperWith(client) });
    result.current.mutate("greeting");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: blockKeys.all });
  });
});
