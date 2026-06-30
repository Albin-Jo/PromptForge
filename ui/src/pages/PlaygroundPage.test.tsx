import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { PlaygroundPage } from "./PlaygroundPage";
import { renderVersion, usePrompt } from "../lib/prompts/api";
import { useModels } from "../lib/gateway/api";
import { streamCompletion, type StreamHandlers } from "../lib/streaming";

// Mock the data + streaming layers so the test drives the SSE handlers directly and
// asserts the component's stream handling (DoD: component test for playground stream).
vi.mock("../lib/prompts/api", () => ({
  usePrompt: vi.fn(),
  renderVersion: vi.fn(),
}));
vi.mock("../lib/gateway/api", () => ({ useModels: vi.fn() }));
vi.mock("../lib/streaming", () => ({ streamCompletion: vi.fn() }));

const mockedUsePrompt = vi.mocked(usePrompt);
const mockedRender = vi.mocked(renderVersion);
const mockedStream = vi.mocked(streamCompletion);
const mockedUseModels = vi.mocked(useModels);

const version = {
  id: "v3",
  version_number: 3,
  parent_version_id: "v2",
  content: "Summarize {{text}}",
  input_variables: ["text"],
  model_settings: { model: "openai/gpt-4o-mini" } as Record<string, unknown>,
  output_schema: null,
  created_at: "2026-01-03T00:00:00Z",
  blocks: [],
};
// Same version with no saved model, so nothing prefills the field (used to test Run gating).
const versionNoModel = { ...version, model_settings: {} };

function setPrompt(v: typeof version) {
  mockedUsePrompt.mockReturnValue({
    data: { id: "p", name: "p", description: null, created_at: "", updated_at: "", versions: [v] },
    isPending: false,
    isError: false,
    // The component only reads data/isPending/isError; cast covers the rest of the query result.
  } as unknown as ReturnType<typeof usePrompt>);
}

function setModels(models: string[]) {
  mockedUseModels.mockReturnValue({
    data: { models },
  } as unknown as ReturnType<typeof useModels>);
}

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
  setPrompt(version);
  // Default: the gateway has models configured, so the field is a picker.
  setModels(["openai/gpt-4o-mini", "anthropic/claude-sonnet-4-6"]);
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
    // The rendered prompt was sent as the user message, with the version's saved model.
    expect(mockedStream).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [{ role: "user", content: "Summarize hello" }],
        config: expect.objectContaining({ model: "openai/gpt-4o-mini" }),
      }),
      expect.anything(),
      expect.anything(),
    );
  });

  it("lists the fetched models in the picker and gates Run until one is chosen", async () => {
    // No saved model -> nothing prefilled -> Run starts disabled even with a picker.
    setPrompt(versionNoModel);
    const user = userEvent.setup();
    renderPage();

    const runButton = screen.getByRole("button", { name: /^run$/i });
    expect(runButton).toBeDisabled();

    // Open the picker and confirm both fetched models are offered.
    await user.click(screen.getByRole("combobox", { name: /model/i }));
    expect(await screen.findByRole("option", { name: "openai/gpt-4o-mini" })).toBeInTheDocument();
    const choice = screen.getByRole("option", { name: "anthropic/claude-sonnet-4-6" });

    await user.click(choice);

    expect(runButton).toBeEnabled();
  });

  it("falls back to a required free-text field when no models are configured", async () => {
    // Empty list (unconfigured gateway) + no saved model -> free-text input, Run gated on it.
    setPrompt(versionNoModel);
    setModels([]);
    const user = userEvent.setup();
    renderPage();

    const modelInput = screen.getByLabelText(/model/i);
    expect(modelInput).toBeRequired();
    expect(screen.getByText(/required —/i)).toBeInTheDocument();

    const runButton = screen.getByRole("button", { name: /^run$/i });
    expect(runButton).toBeDisabled();

    await user.type(modelInput, "openai/gpt-4o-mini");
    expect(runButton).toBeEnabled();
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
