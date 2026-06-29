import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { Card } from "./ui/card";
import type { DatasetItem } from "../lib/datasets/types";

export interface DatasetFormValues {
  name: string;
  description: string;
  items: DatasetItem[];
}

interface DatasetEditorFormProps {
  mode: "create" | "edit";
  initial: {
    name: string;
    description: string;
    items: DatasetItem[];
  };
  submitting: boolean;
  errorMessage: string | null;
  onSubmit: (values: DatasetFormValues) => void;
}

// A case row's editable state. `id` is a stable client-side key so removing a middle row doesn't
// reassign React identities by index (which can mis-route focus). `metadata` is carried through
// unchanged (the form doesn't expose it, but PUT replaces cases wholesale, so we must round-trip
// it — see types.ts).
interface RowState {
  id: number;
  input: string;
  reference: string;
  metadata: Record<string, unknown> | null;
}

export function DatasetEditorForm({
  mode,
  initial,
  submitting,
  errorMessage,
  onSubmit,
}: DatasetEditorFormProps) {
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  // Monotonic source of stable row ids (never an array index). Seeded once; bumped on every new row.
  const nextRowId = useRef(0);
  const makeRow = (item?: DatasetItem): RowState => ({
    id: nextRowId.current++,
    input: item?.input ?? "",
    reference: item?.reference ?? "",
    metadata: item?.metadata ?? null,
  });
  // Start with one empty row on create so there's always something to fill in.
  const [rows, setRows] = useState<RowState[]>(() =>
    initial.items.length > 0 ? initial.items.map((item) => makeRow(item)) : [makeRow()],
  );

  function updateRow(index: number, patch: Partial<RowState>) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addRow() {
    setRows((current) => [...current, makeRow()]);
  }

  function removeRow(index: number) {
    setRows((current) => current.filter((_, i) => i !== index));
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    // Drop rows with a blank input — an empty case can't grade anything. The server also enforces
    // "at least one case", so we surface that here rather than send an obviously-invalid body.
    const items: DatasetItem[] = rows
      .filter((row) => row.input.trim() !== "")
      .map((row) => ({
        input: row.input,
        reference: row.reference.trim() === "" ? null : row.reference,
        metadata: row.metadata,
      }));
    onSubmit({ name: name.trim(), description: description.trim(), items });
  }

  const usableCases = rows.filter((row) => row.input.trim() !== "").length;

  return (
    <form onSubmit={handleSubmit} className="max-w-3xl">
      {mode === "create" && (
        <label className="block text-sm font-medium text-foreground">
          Name
          <Input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="summarization-golden"
            className="mt-1"
          />
        </label>
      )}

      <label className="mt-4 block text-sm font-medium text-foreground">
        Description
        <Input
          type="text"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this golden set checks"
          className="mt-1"
        />
      </label>

      <div className="mt-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-foreground">Cases</h2>
          <span className="text-xs text-muted-foreground">
            {usableCases} case{usableCases === 1 ? "" : "s"}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Each case is an input and, optionally, the reference answer it should match. At least one
          is required.
        </p>

        <div className="mt-3 space-y-3">
          {rows.map((row, index) => (
            <Card key={row.id} className="gap-3 p-4">
              <div className="flex items-start justify-between gap-3">
                <span className="text-xs font-medium text-muted-foreground">Case {index + 1}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => removeRow(index)}
                  disabled={rows.length === 1}
                  aria-label={`Remove case ${index + 1}`}
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </div>
              <label className="block text-xs font-medium text-foreground">
                Input
                <Textarea
                  rows={2}
                  value={row.input}
                  onChange={(e) => updateRow(index, { input: e.target.value })}
                  placeholder="Summarize: …"
                  className="mt-1"
                />
              </label>
              <label className="block text-xs font-medium text-foreground">
                Reference <span className="text-muted-foreground">(optional)</span>
                <Textarea
                  rows={2}
                  value={row.reference}
                  onChange={(e) => updateRow(index, { reference: e.target.value })}
                  placeholder="The expected answer"
                  className="mt-1"
                />
              </label>
            </Card>
          ))}
        </div>

        <Button type="button" variant="outline" size="sm" onClick={addRow} className="mt-3">
          <Plus className="size-4" aria-hidden />
          Add case
        </Button>
      </div>

      {errorMessage && <p className="mt-4 text-sm text-destructive">{errorMessage}</p>}

      <Button type="submit" disabled={submitting || usableCases === 0} className="mt-6">
        {submitting
          ? "Saving…"
          : mode === "create"
            ? "Create golden set"
            : "Save changes"}
      </Button>
    </form>
  );
}
