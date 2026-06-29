import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useDatasets } from "../lib/datasets/api";
import { useSetGoldenSet } from "../lib/prompts/api";
import { useCan } from "../lib/auth/AuthContext";
import { toast, toastError } from "../lib/toast";
import { Card } from "./ui/card";
import { DisabledTooltip } from "./DisabledTooltip";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

// Radix Select can't use an empty-string item value, so "no gate" gets a sentinel.
const NONE = "__none__";
// A second sentinel for "a set is attached, but it isn't in the list we loaded" — so we never
// silently render an attached gate as "None". Can't happen today (you can't delete an in-use set),
// but it's a one-line guard against future list filtering/pagination misrepresenting the gate.
const UNRESOLVED = "__unresolved__";

// Show the "why disabled" tooltip only when the *role* is the reason. When the user can edit, the
// children render bare — a transient busy/pending disable shouldn't claim "requires the editor role".
function RoleGate({ canEdit, children }: { canEdit: boolean; children: ReactNode }): ReactNode {
  if (canEdit) return children;
  return <DisabledTooltip reason="Requires the editor role">{children}</DisabledTooltip>;
}

interface GoldenSetSelectProps {
  promptName: string;
  /** The currently-attached golden set id, or null when none is attached. */
  attachedId: string | null;
}

/**
 * The promotion-gate control on a prompt's editor: pick the golden set this prompt must clear to be
 * promoted (or "none"). Reflects the currently-attached set and writes through immediately — it's a
 * standalone action, not part of saving a version. Editor-gated; the backend enforces the role too.
 */
export function GoldenSetSelect({ promptName, attachedId }: GoldenSetSelectProps) {
  const datasetsQuery = useDatasets();
  const setGoldenSet = useSetGoldenSet(promptName);
  const canEdit = useCan("editor");

  const datasets = datasetsQuery.data ?? [];
  const attached = datasets.find((d) => d.id === attachedId) ?? null;
  // An attached id we couldn't resolve to a loaded set (and aren't still loading) — surface it
  // rather than show NONE, which would falsely read as "no gate".
  const unresolved = attachedId !== null && attached === null && !datasetsQuery.isPending;
  // Map id → name for the Select value: the attached set's name, the unresolved sentinel, or NONE.
  const value = attached?.name ?? (unresolved ? UNRESOLVED : NONE);

  function handleChange(next: string) {
    const dataset = next === NONE ? null : next;
    setGoldenSet.mutate(dataset, {
      onSuccess: () => {
        toast.success(dataset ? `Gate set to “${dataset}”` : "Removed the promotion gate");
      },
      onError: (err) => toastError(err, "Could not update the golden set."),
    });
  }

  return (
    <Card className="mt-6 max-w-2xl gap-3 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium text-foreground">Promotion gate</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            The golden set this prompt must clear before it can be promoted.
          </p>
        </div>
        <RoleGate canEdit={canEdit}>
          <Select
            value={value}
            onValueChange={handleChange}
            disabled={!canEdit || setGoldenSet.isPending || datasetsQuery.isPending}
          >
            <SelectTrigger className="w-56" aria-label="Golden set">
              <SelectValue placeholder="Select a golden set" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>None — no gate</SelectItem>
              {unresolved && (
                <SelectItem value={UNRESOLVED} disabled>
                  Attached set (unavailable)
                </SelectItem>
              )}
              {datasets.map((d) => (
                <SelectItem key={d.id} value={d.name}>
                  {d.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </RoleGate>
      </div>

      {datasetsQuery.data?.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No golden sets yet — <Link to="/datasets/new" className="underline">create one</Link> to
          gate this prompt.
        </p>
      )}
    </Card>
  );
}
