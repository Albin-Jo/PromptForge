import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { createElement } from "react";

vi.mock("../api", () => ({ apiFetch: vi.fn() }));
import { apiFetch } from "../api";
import {
  createDataset,
  datasetKeys,
  deleteDataset,
  updateDataset,
  useCreateDataset,
  useDeleteDataset,
  useUpdateDataset,
} from "./api";

const mockedFetch = vi.mocked(apiFetch);

beforeEach(() => vi.clearAllMocks());

function wrapperWith(client: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
}

describe("dataset request functions hit the right endpoints", () => {
  it("createDataset POSTs to /datasets", async () => {
    mockedFetch.mockResolvedValue({ name: "gs" } as never);
    await createDataset({ name: "gs", description: null, items: [{ input: "a", reference: null, metadata: null }] });
    expect(mockedFetch).toHaveBeenCalledWith("/datasets", {
      method: "POST",
      body: { name: "gs", description: null, items: [{ input: "a", reference: null, metadata: null }] },
    });
  });

  it("updateDataset PUTs to /datasets/{name}", async () => {
    mockedFetch.mockResolvedValue({ name: "gs" } as never);
    await updateDataset("gs", { description: "x", items: [{ input: "a", reference: null, metadata: null }] });
    expect(mockedFetch).toHaveBeenCalledWith("/datasets/gs", {
      method: "PUT",
      body: { description: "x", items: [{ input: "a", reference: null, metadata: null }] },
    });
  });

  it("deleteDataset DELETEs /datasets/{name} (encoded)", async () => {
    mockedFetch.mockResolvedValue(null as never);
    await deleteDataset("my set");
    expect(mockedFetch).toHaveBeenCalledWith("/datasets/my%20set", { method: "DELETE" });
  });
});

describe("dataset mutations invalidate the list on success", () => {
  it("useCreateDataset invalidates the dataset list", async () => {
    mockedFetch.mockResolvedValue({ name: "gs" } as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useCreateDataset(), { wrapper: wrapperWith(client) });
    result.current.mutate({ name: "gs", description: null, items: [{ input: "a", reference: null, metadata: null }] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: datasetKeys.all });
  });

  it("useUpdateDataset invalidates the list and that set's detail", async () => {
    mockedFetch.mockResolvedValue({ name: "gs" } as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useUpdateDataset("gs"), { wrapper: wrapperWith(client) });
    result.current.mutate({ description: null, items: [{ input: "a", reference: null, metadata: null }] });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: datasetKeys.all });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: datasetKeys.detail("gs") });
  });

  it("useDeleteDataset invalidates the dataset list", async () => {
    mockedFetch.mockResolvedValue(null as never);
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useDeleteDataset(), { wrapper: wrapperWith(client) });
    result.current.mutate("gs");

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: datasetKeys.all });
  });
});
