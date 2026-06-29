import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PromptEditorForm } from "./PromptEditorForm";
import type { PromptFormValues } from "./PromptEditorForm";

// The form renders CompositionEditor, which fetches the block catalog. Mock the data
// hooks so these tests stay focused on form behavior and need no QueryClient/network.
vi.mock("../lib/blocks/api", () => ({
  useBlocks: () => ({
    data: [
      {
        id: "blk-1",
        name: "guardrails",
        role: "guardrails",
        description: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        versions: [
          {
            id: "bv-2",
            version_number: 2,
            parent_version_id: "bv-1",
            content: "be safe",
            input_variables: [],
            created_at: "2026-01-02T00:00:00Z",
          },
        ],
      },
    ],
    isPending: false,
    isError: false,
    error: null,
  }),
  useBlockImpact: () => ({ data: undefined, isFetching: false, isError: false }),
}));

const emptyInitial = { name: "", description: "", content: "", inputVariables: [] };

describe("PromptEditorForm", () => {
  it("shows name + description in create mode", () => {
    render(
      <PromptEditorForm
        mode="create"
        initial={emptyInitial}
        submitting={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create prompt/i })).toBeInTheDocument();
  });

  it("hides name + description in edit mode", () => {
    render(
      <PromptEditorForm
        mode="edit"
        initial={{ name: "x", description: "", content: "hi", inputVariables: [] }}
        submitting={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText(/name/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save new version/i })).toBeInTheDocument();
  });

  it("parses comma-separated variables (trim + dedupe) on submit", async () => {
    const onSubmit = vi.fn<(v: PromptFormValues) => void>();
    const user = userEvent.setup();
    render(
      <PromptEditorForm
        mode="create"
        initial={emptyInitial}
        submitting={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    await user.type(screen.getByLabelText(/name/i), "summarize");
    await user.type(screen.getByLabelText(/content/i), "Summarize the document");
    await user.type(screen.getByLabelText(/input variables/i), " text , tone , text ");
    await user.click(screen.getByRole("button", { name: /create prompt/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const values = onSubmit.mock.calls[0][0];
    expect(values.name).toBe("summarize");
    expect(values.content).toBe("Summarize the document");
    // Trimmed + de-duped ("text" appears twice -> once).
    expect(values.inputVariables).toEqual(["text", "tone"]);
  });

  it("renders the existing composition as editable rows", () => {
    render(
      <PromptEditorForm
        mode="edit"
        initial={{ name: "x", description: "", content: "hi", inputVariables: [] }}
        blocks={[{ block: "guardrails", version: 2 }]}
        submitting={false}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    // "guardrails" appears as both the block name and its role badge.
    expect(screen.getAllByText("guardrails").length).toBeGreaterThan(0);
    // Composition is now editable: each row exposes a pinned-version control + remove.
    expect(screen.getByLabelText(/pinned version for guardrails/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove guardrails/i })).toBeInTheDocument();
  });

  it("includes the composition (default empty) in the submitted values", async () => {
    const onSubmit = vi.fn<(v: PromptFormValues) => void>();
    const user = userEvent.setup();
    render(
      <PromptEditorForm
        mode="edit"
        initial={{ name: "x", description: "", content: "hi", inputVariables: [] }}
        submitting={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );
    await user.click(screen.getByRole("button", { name: /save new version/i }));
    expect(onSubmit.mock.calls[0][0].blocks).toEqual([]);
  });

  it("disables the submit button while submitting", () => {
    render(
      <PromptEditorForm
        mode="create"
        initial={emptyInitial}
        submitting={true}
        errorMessage={null}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
  });
});
