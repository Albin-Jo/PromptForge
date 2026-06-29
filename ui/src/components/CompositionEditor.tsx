import { useMemo, useState } from "react";
import { useBlocks, useBlockImpact } from "../lib/blocks/api";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";
import type { Block } from "../lib/blocks/types";
import type { BlockRef } from "../lib/prompts/types";

// Native <select> restyled onto design tokens. We keep it native (not the Radix Select
// primitive) for these dense, interaction-tested inline controls — see Sprint 16d notes.
const selectClasses =
  "rounded-md border border-input bg-background text-foreground shadow-sm " +
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring " +
  "disabled:cursor-not-allowed disabled:opacity-50";

interface CompositionEditorProps {
  /** The ordered, version-pinned blocks composed into this version. */
  value: BlockRef[];
  onChange: (next: BlockRef[]) => void;
}

// The block/composition editor (Sprint 15, Task 2). Builds the ordered, version-pinned
// list of BlockRefs that gets saved onto a new prompt version. Decisions (approved):
//   - lives inside the prompt editor (state lifted to the form)
//   - adding a block pins to its latest version by default, editable via a dropdown
//   - impact is fetched on demand per block, not eagerly for the whole list
export function CompositionEditor({ value, onChange }: CompositionEditorProps) {
  const { data: blocks, isPending, isError, error } = useBlocks();

  const byName = useMemo(() => {
    const map = new Map<string, Block>();
    for (const b of blocks ?? []) map.set(b.name, b);
    return map;
  }, [blocks]);

  // Blocks not yet in the composition — the "add" picker's options.
  const available = useMemo(
    () => (blocks ?? []).filter((b) => !value.some((ref) => ref.block === b.name)),
    [blocks, value],
  );

  function latestVersion(block: Block): number {
    return block.versions.reduce((max, v) => Math.max(max, v.version_number), 0);
  }

  function addBlock(name: string) {
    const block = byName.get(name);
    if (!block) return;
    onChange([...value, { block: name, version: latestVersion(block) }]);
  }

  function removeBlock(index: number) {
    onChange(value.filter((_, i) => i !== index));
  }

  function move(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= value.length) return;
    const next = [...value];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  function repin(index: number, version: number) {
    onChange(value.map((ref, i) => (i === index ? { ...ref, version } : ref)));
  }

  return (
    <div className="mt-4 rounded-md border border-border bg-muted/40 p-3">
      <p className="text-sm font-medium text-foreground">Composition</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Blocks are prepended to the content in order, each pinned to an exact version.
      </p>

      {isError && (
        <p className="mt-2 text-sm text-destructive">Could not load blocks: {error.message}</p>
      )}

      {value.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">No blocks composed in. Add one below.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {value.map((ref, index) => {
            const block = byName.get(ref.block);
            return (
              <li key={ref.block} className="rounded-md border border-border bg-card p-2">
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-xs text-muted-foreground">{index + 1}.</span>
                  <span className="font-medium text-foreground">{ref.block}</span>
                  {block && <Badge variant="secondary">{block.role}</Badge>}

                  <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
                    version
                    {block ? (
                      <select
                        aria-label={`Pinned version for ${ref.block}`}
                        value={ref.version}
                        onChange={(e) => repin(index, Number(e.target.value))}
                        className={cn(selectClasses, "px-1.5 py-0.5 text-xs")}
                      >
                        {[...block.versions]
                          .sort((a, b) => b.version_number - a.version_number)
                          .map((v) => (
                            <option key={v.id} value={v.version_number}>
                              v{v.version_number}
                            </option>
                          ))}
                      </select>
                    ) : (
                      // Block isn't in the catalog (deleted/renamed) — keep the pin, show it.
                      <span className="text-foreground">v{ref.version}</span>
                    )}
                  </label>

                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-7"
                      aria-label={`Move ${ref.block} up`}
                      disabled={index === 0}
                      onClick={() => move(index, -1)}
                    >
                      ↑
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      className="size-7"
                      aria-label={`Move ${ref.block} down`}
                      disabled={index === value.length - 1}
                      onClick={() => move(index, 1)}
                    >
                      ↓
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 text-destructive hover:bg-destructive/10 hover:text-destructive"
                      aria-label={`Remove ${ref.block}`}
                      onClick={() => removeBlock(index)}
                    >
                      Remove
                    </Button>
                  </div>
                </div>
                <ImpactToggle block={ref.block} />
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-3 flex items-center gap-2">
        <AddBlockPicker available={available} disabled={isPending} onAdd={addBlock} />
      </div>
    </div>
  );
}

interface AddBlockPickerProps {
  available: Block[];
  disabled: boolean;
  onAdd: (name: string) => void;
}

// A select + button to add a not-yet-composed block. Resets after each add.
function AddBlockPicker({ available, disabled, onAdd }: AddBlockPickerProps) {
  const [selected, setSelected] = useState("");

  function handleAdd() {
    if (!selected) return;
    onAdd(selected);
    setSelected("");
  }

  return (
    <>
      <select
        aria-label="Add a block"
        value={selected}
        disabled={disabled || available.length === 0}
        onChange={(e) => setSelected(e.target.value)}
        className={cn(selectClasses, "px-2 py-1 text-sm")}
      >
        <option value="">
          {available.length === 0 ? "No more blocks to add" : "Select a block…"}
        </option>
        {available.map((b) => (
          <option key={b.id} value={b.name}>
            {b.name} ({b.role})
          </option>
        ))}
      </select>
      <Button type="button" variant="outline" size="sm" onClick={handleAdd} disabled={!selected}>
        Add block
      </Button>
    </>
  );
}

// On-demand impact: only calls GET /blocks/{name}/impact once expanded.
function ImpactToggle({ block }: { block: string }) {
  const [open, setOpen] = useState(false);
  const { data, isFetching, isError } = useBlockImpact(block, open);

  return (
    <div className="mt-2 border-t border-border pt-2 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-muted-foreground hover:text-foreground"
      >
        {open ? "▾" : "▸"} Impact
      </button>
      {open && (
        <div className="mt-1 text-muted-foreground">
          {isFetching && <span className="text-muted-foreground">Loading impact…</span>}
          {isError && <span className="text-destructive">Could not load impact.</span>}
          {data && (
            <span>
              Used by {data.prompts.length} prompt version
              {data.prompts.length === 1 ? "" : "s"} and {data.blocks.length} block version
              {data.blocks.length === 1 ? "" : "s"}.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
