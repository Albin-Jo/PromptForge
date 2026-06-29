import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";

vi.mock("../lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("../lib/auth/AuthContext", () => ({ useCan: vi.fn() }));

import { apiFetch } from "../lib/api";
import { useCan } from "../lib/auth/AuthContext";
import { GoldenSetSelect } from "./GoldenSetSelect";

const mockedFetch = vi.mocked(apiFetch);
const mockedUseCan = vi.mocked(useCan);

const DATASETS = [
  { id: "id-gs", name: "summarization-golden", description: null, created_at: "", item_count: 3 },
  { id: "id-qa", name: "qa-golden", description: null, created_at: "", item_count: 1 },
];

function renderSelect(attachedId: string | null) {
  // The only network call this component makes on mount is listDatasets (GET /datasets).
  mockedFetch.mockImplementation((path: string) => {
    if (path === "/datasets") return Promise.resolve(DATASETS as never);
    return Promise.resolve({} as never);
  });
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return render(<GoldenSetSelect promptName="p" attachedId={attachedId} />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  // Default: an editor who can change the gate. Individual tests override for the non-editor case.
  mockedUseCan.mockReturnValue(true);
});

describe("GoldenSetSelect", () => {
  it("reflects the currently-attached golden set", async () => {
    renderSelect("id-gs");
    // The trigger shows the name of the dataset whose id matches the attached id.
    await waitFor(() =>
      expect(screen.getByLabelText("Golden set")).toHaveTextContent("summarization-golden"),
    );
  });

  it("shows 'None — no gate' when nothing is attached", async () => {
    renderSelect(null);
    await waitFor(() =>
      expect(screen.getByLabelText("Golden set")).toHaveTextContent("None — no gate"),
    );
  });

  it("disables the select for a non-editor and explains why", async () => {
    mockedUseCan.mockReturnValue(false);
    renderSelect(null);
    const trigger = await screen.findByLabelText("Golden set");
    expect(trigger).toBeDisabled();
    // The disabled trigger can't receive focus, so the wrapper span carries it. Focusing the span
    // opens the tooltip (delayDuration 0) and reveals the role reason — the whole point of the span.
    fireEvent.focus(trigger.parentElement as HTMLElement);
    // Radix renders the open tooltip plus a visually-hidden a11y copy, so there can be >1 match.
    expect((await screen.findAllByText("Requires the editor role")).length).toBeGreaterThan(0);
  });
});
