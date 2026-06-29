import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DatasetEditorForm } from "./DatasetEditorForm";

function renderForm(onSubmit = vi.fn()) {
  render(
    <DatasetEditorForm
      mode="create"
      initial={{ name: "", description: "", items: [] }}
      submitting={false}
      errorMessage={null}
      onSubmit={onSubmit}
    />,
  );
  return { onSubmit };
}

describe("DatasetEditorForm", () => {
  it("starts with one case row and can add more", async () => {
    renderForm();
    expect(screen.getByText("Case 1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add case" }));
    expect(screen.getByText("Case 2")).toBeInTheDocument();
  });

  it("can remove a row (but not the last one)", async () => {
    renderForm();
    // The single starting row's remove button is disabled.
    expect(screen.getByRole("button", { name: "Remove case 1" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Add case" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove case 2" }));
    expect(screen.queryByText("Case 2")).not.toBeInTheDocument();
  });

  it("submits only rows with a non-blank input, reference null when empty", async () => {
    const { onSubmit } = renderForm();
    await userEvent.type(screen.getByPlaceholderText("summarization-golden"), "gs");
    const inputs = screen.getAllByPlaceholderText("Summarize: …");
    await userEvent.type(inputs[0], "hello");
    // Add a second, blank row that should be dropped on submit.
    await userEvent.click(screen.getByRole("button", { name: "Add case" }));

    await userEvent.click(screen.getByRole("button", { name: "Create golden set" }));

    expect(onSubmit).toHaveBeenCalledWith({
      name: "gs",
      description: "",
      items: [{ input: "hello", reference: null, metadata: null }],
    });
  });

  it("disables submit when there are no usable cases", () => {
    renderForm();
    expect(screen.getByRole("button", { name: "Create golden set" })).toBeDisabled();
  });
});
