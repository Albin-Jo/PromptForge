import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DatasetEditorForm } from "./DatasetEditorForm";
import { fromCsv } from "../lib/csv";
import type { CsvParseResult } from "../lib/csv";

vi.mock("../lib/csv", () => ({
  fromCsv: vi.fn(),
  toCsv: vi.fn(),
  downloadCsv: vi.fn(),
}));

const mockedFromCsv = vi.mocked(fromCsv);

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

beforeEach(() => {
  mockedFromCsv.mockReset();
  mockedFromCsv.mockReturnValue({ rows: [], errors: [] });
});

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

describe("DatasetEditorForm — CSV import", () => {
  function csvFile(content = "input\nhello") {
    return new File([content], "cases.csv", { type: "text/csv" });
  }

  async function uploadCsv(result: CsvParseResult) {
    mockedFromCsv.mockReturnValue(result);
    renderForm();
    const fileInput = screen.getByLabelText("Select CSV file");
    await userEvent.upload(fileInput, csvFile());
  }

  it("renders the Import CSV button", () => {
    renderForm();
    expect(screen.getByRole("button", { name: /import csv/i })).toBeInTheDocument();
  });

  it("shows a preview table after a file is selected", async () => {
    await uploadCsv({
      rows: [{ input: "Hello world", reference: "Expected" }],
      errors: [],
    });
    await waitFor(() =>
      expect(screen.getByRole("table", { name: "CSV preview table" })).toBeInTheDocument(),
    );
    expect(screen.getByText("Hello world")).toBeInTheDocument();
    expect(screen.getByText("Expected")).toBeInTheDocument();
  });

  it("shows parse errors inline when present", async () => {
    await uploadCsv({
      rows: [],
      errors: [{ rowIndex: 0, message: 'Required column "input" not found in header row.' }],
    });
    await waitFor(() =>
      expect(screen.getByRole("list", { name: "Import errors" })).toBeInTheDocument(),
    );
    expect(screen.getByText(/Required column "input"/)).toBeInTheDocument();
  });

  it("populates cases from parsed rows when confirmed", async () => {
    await uploadCsv({
      rows: [
        { input: "First", reference: null },
        { input: "Second", reference: "Ref" },
      ],
      errors: [],
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /populate 2 cases/i })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: /populate 2 cases/i }));
    // Preview collapses; the rows are now in the form.
    expect(screen.getByText("Case 1")).toBeInTheDocument();
    expect(screen.getByText("Case 2")).toBeInTheDocument();
    // Import button reappears (preview dismissed).
    expect(screen.getByRole("button", { name: /import csv/i })).toBeInTheDocument();
  });

  it("cancels the import without changing existing rows", async () => {
    await uploadCsv({
      rows: [{ input: "Imported", reference: null }],
      errors: [],
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("table", { name: "CSV preview table" })).not.toBeInTheDocument();
    // Original single blank row still present.
    expect(screen.getByText("Case 1")).toBeInTheDocument();
  });
});
