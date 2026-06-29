import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { PlaygroundPage } from "./PlaygroundPage";
import { renderVersion, usePrompt } from "../lib/prompts/api";
import { streamCompletion, type StreamHandlers } from "../lib/streaming";

// Mock the data + streaming layers so the test drives the SSE handlers directly and
// asserts the component's stream handling (DoD: component test for playground stream).
vi.mock("../lib/prompts/api", () => ({
  usePrompt: vi.fn(),
  renderVersion: vi.fn(),
}));
vi.mock("../lib/streaming", () => ({ streamCompletion: vi.fn() }));

const mockedUsePrompt = vi.mocked(usePrompt);
const mockedRender = vi.mocked(renderVersion);
const mockedStream = vi.mocked(streamCompletion);

const version = {
  id: "v3",
  version_number: 3,
  parent_version_id: "v2",
  content: "Summarize {{text}}",
  input_variables: ["text"],
  model_settings: { model: "openai/gpt-4o-mini" },
  output_schema: null,
  created_at: "2026-01-03T00:00:00Z",
  blocks: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/prompts/p/versions/3/playground"]}>
      <Routes>
        <Route
          path="/prompts/:name/versions/:versionNumber/playground"
          element={<PlaygroundPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockedUsePrompt.mockReturnValue({
    data: { id: "p", name: "p", description: null, created_at: "", updated_at: "", versions: [version] },
    isPending: false,
    isError: false,
    // The component only reads data/isPending/isError; cast covers the rest of the query result.
  } as unknown as ReturnType<typeof usePrompt>);
  mockedRender.mockResolvedValue({
    prompt: "Summarize hello",
    model_settings: { model: "openai/gpt-4o-mini" },
    output_schema: null,
    prompt_id: "p",
    prompt_version_id: "v3",
    version_number: 3,
  });
});

describe("PlaygroundPage", () => {
  it("accumulates streamed tokens into the output and ends with Done", async () => {
    mockedStream.mockImplementation(async (_body, handlers: StreamHandlers) => {
      handlers.onToken("Hello ");
      handlers.onToken("world");
      handlers.onDone();
    });

    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /^run$/i }));

    await waitFor(() =>
      expect(screen.getByLabelText(/completion output/i)).toHaveTextContent("Hello world"),
    );
    expect(screen.getByText(/done/i)).toBeInTheDocument();
    // The rendered prompt was sent as the user message.
    expect(mockedStream).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [{ role: "user", content: "Summarize hello" }],
        config: expect.objectContaining({ model: "openai/gpt-4o-mini" }),
      }),
      expect.anything(),
      expect.anything(),
    );
  });

  it("shows an error when the stream reports one", async () => {
    mockedStream.mockImplementation(async (_body, handlers: StreamHandlers) => {
      handlers.onError("provider exploded");
    });

    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /^run$/i }));

    await waitFor(() => expect(screen.getByText("provider exploded")).toBeInTheDocument());
  });

  it("surfaces a render failure without calling the stream", async () => {
    mockedRender.mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /^run$/i }));

    await waitFor(() => expect(screen.getByText(/something went wrong/i)).toBeInTheDocument());
    expect(mockedStream).not.toHaveBeenCalled();
  });
});
