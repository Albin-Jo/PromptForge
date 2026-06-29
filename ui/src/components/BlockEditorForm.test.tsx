import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

// CompositionEditor reads useBlocks() -> apiFetch; stub the network so it mounts cleanly.
vi.mock("../lib/api", () => ({ apiFetch: vi.fn().mockResolvedValue([]) }));

import { BlockEditorForm } from "./BlockEditorForm";

function renderForm(mode: "create" | "version", onSubmit = vi.fn()) {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(
    <BlockEditorForm
      mode={mode}
      initial={{ name: "", role: "role", description: "", content: "", inputVariables: [] }}
      submitting={false}
      errorMessage={null}
      onSubmit={onSubmit}
    />,
    { wrapper },
  );
  return { onSubmit };
}

describe("BlockEditorForm", () => {
  it("shows identity fields (name + role) only in create mode", () => {
    renderForm("create");
    expect(screen.getByPlaceholderText("safety-guardrails")).toBeInTheDocument();
    expect(screen.getByLabelText("Role")).toBeInTheDocument();
  });

  it("hides identity fields in version mode (only the body is editable)", () => {
    renderForm("version");
    expect(screen.queryByPlaceholderText("safety-guardrails")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Role")).not.toBeInTheDocument();
  });

  it("submits the form values including the default role", async () => {
    const { onSubmit } = renderForm("create");
    await userEvent.type(screen.getByPlaceholderText("safety-guardrails"), "greeting");
    // Avoid `{{ }}` here — userEvent.type reads braces as special-key escapes.
    await userEvent.type(screen.getByPlaceholderText("Always answer in {{tone}}."), "Be concise.");
    await userEvent.type(screen.getByPlaceholderText("tone"), "tone");

    await userEvent.click(screen.getByRole("button", { name: "Create block" }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: "greeting",
      role: "role",
      description: "",
      content: "Be concise.",
      inputVariables: ["tone"],
      blocks: [],
    });
  });
});
