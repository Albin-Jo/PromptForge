import { useMemo } from "react";
import { diffLines, isUnchanged, type DiffLine } from "../lib/diff";

interface DiffViewProps {
  oldText: string;
  newText: string;
  /** Labels for the two sides, shown in the header (e.g. "v2" / "v3"). */
  oldLabel?: string;
  newLabel?: string;
}

// Subtle token tints so the diff reads in both themes (added=success, removed=destructive).
const ROW_STYLES: Record<DiffLine["type"], string> = {
  context: "text-foreground",
  added: "bg-success/10 text-foreground",
  removed: "bg-destructive/10 text-foreground",
};

const SIGILS: Record<DiffLine["type"], string> = {
  context: " ",
  added: "+",
  removed: "-",
};

// Color the +/- gutter so the add/remove cue carries even where the 10%-opacity row tint
// is hard to read (notably dark mode). The glyph still differs, so this isn't color-only.
const SIGIL_STYLES: Record<DiffLine["type"], string> = {
  context: "text-muted-foreground",
  added: "text-success",
  removed: "text-destructive",
};

// Unified line diff (one column, +/- gutters) — deliberately simple per the sprint's
// "resist a diff-library rabbit hole" note. Side-by-side is a later polish if wanted.
export function DiffView({ oldText, newText, oldLabel, newLabel }: DiffViewProps) {
  const lines = useMemo(() => diffLines(oldText, newText), [oldText, newText]);

  if (isUnchanged(lines)) {
    return (
      <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
        No differences{oldLabel && newLabel ? ` between ${oldLabel} and ${newLabel}` : ""}.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-md border border-border">
      {oldLabel && newLabel && (
        <div className="flex gap-4 border-b border-border bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
          <span className="text-destructive">− {oldLabel}</span>
          <span className="text-success">+ {newLabel}</span>
        </div>
      )}
      <table className="w-full border-collapse font-mono text-xs">
        <tbody>
          {lines.map((line, idx) => (
            <tr key={idx} className={ROW_STYLES[line.type]} data-diff-type={line.type}>
              <td className="w-10 select-none border-r border-border px-2 py-0.5 text-right text-muted-foreground">
                {line.oldNumber ?? ""}
              </td>
              <td className="w-10 select-none border-r border-border px-2 py-0.5 text-right text-muted-foreground">
                {line.newNumber ?? ""}
              </td>
              <td
                className={`w-5 select-none px-1 py-0.5 text-center font-semibold ${SIGIL_STYLES[line.type]}`}
              >
                {SIGILS[line.type]}
              </td>
              <td className="whitespace-pre-wrap break-words px-2 py-0.5">{line.text || " "}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
