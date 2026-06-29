import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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
    // Content references both placeholders so declared == detected (Save stays enabled).
    // Set via fireEvent: userEvent.type treats "{{" as a key-descriptor escape.
    fireEvent.change(screen.getByLabelText(/content/i), {
      target: { value: "Summarize {{text}} in a {{tone}} tone" },
    });
    await user.type(screen.getByLabelText(/input variables/i), " text , tone , text ");
    await user.click(screen.getByRole("button", { name: /create prompt/i }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const values = onSubmit.mock.calls[0][0];
    expect(values.name).toBe("summarize");
    expect(values.content).toBe("Summarize {{text}} in a {{tone}} tone");
    // Trimmed + de-duped ("text" appears twice -> once).
    expect(values.inputVariables).toEqual(["text", "tone"]);
  });

  it("shows detected variables and blocks Save on a declared/detected mismatch", async () => {
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

    // A placeholder with no matching declaration -> undeclared warning + disabled Save.
    fireEvent.change(screen.getByLabelText(/content/i), { target: { value: "Use {{text}}" } });
    expect(screen.getByText("{{text}}")).toBeInTheDocument(); // detected chip
    const save = screen.getByRole("button", { name: /create prompt/i });
    expect(save).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/not declared/i);

    // Declaring it clears the mismatch and re-enables Save.
    await user.type(screen.getByLabelText(/input variables/i), "text");
    expect(save).toBeEnabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("soft-warns (does not block Save) when a composed block can't be resolved", () => {
    const onSubmit = vi.fn<(v: PromptFormValues) => void>();
    render(
      <PromptEditorForm
        mode="create"
        initial={{ ...emptyInitial, inputVariables: ["extra"] }}
        // version 1 isn't in the mocked catalog (only version 2 is) -> unresolved block.
        blocks={[{ block: "guardrails", version: 1 }]}
        submitting={false}
        errorMessage={null}
        onSubmit={onSubmit}
      />,
    );

    // "extra" is declared but used by neither the (empty) body nor a resolvable block.
    // Because a block couldn't be resolved, this is a *soft* warning, not a hard block.
    const warning = screen.getByRole("status");
    expect(warning).toHaveTextContent(/possibly unused/i);
    expect(warning).toHaveTextContent(/couldn.t be resolved/i);
    expect(screen.getByRole("button", { name: /create prompt/i })).toBeEnabled();
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
