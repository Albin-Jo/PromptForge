// Line-based diff between two prompt versions (Sprint 15, Task 1).
//
// Hand-rolled LCS rather than a diff library: the sprint explicitly warns against a
// diff-library rabbit hole, and a line diff is ~40 lines and fully unit-testable.
//
// The algorithm: find the Longest Common Subsequence of the two lists of lines, then
// walk both lists together — lines in the LCS are "context", lines only in the old
// version are "removed", lines only in the new version are "added". This is the same
// shape `git diff` shows in unified mode.

export type DiffLineType = "context" | "added" | "removed";

export interface DiffLine {
  type: DiffLineType;
  text: string;
  /** 1-based line number in the old version, or null for added lines. */
  oldNumber: number | null;
  /** 1-based line number in the new version, or null for removed lines. */
  newNumber: number | null;
}

/** Split into lines, treating empty input as zero lines (not one blank line). */
function splitLines(text: string): string[] {
  if (text === "") return [];
  return text.split("\n");
}

/**
 * Compute a unified line diff from `oldText` to `newText`.
 *
 * Returns one {@link DiffLine} per output row, in display order.
 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = splitLines(oldText);
  const b = splitLines(newText);
  const m = a.length;
  const n = b.length;

  // lcs[i][j] = length of the LCS of a[i:] and b[j:]. Filled bottom-up so we can
  // backtrack forward through the lists in display order.
  const lcs: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      lcs[i][j] =
        a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  let oldNo = 1;
  let newNo = 1;

  while (i < m && j < n) {
    if (a[i] === b[j]) {
      out.push({ type: "context", text: a[i], oldNumber: oldNo++, newNumber: newNo++ });
      i++;
      j++;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      // Dropping a[i] keeps the LCS at least as long -> it was removed.
      out.push({ type: "removed", text: a[i], oldNumber: oldNo++, newNumber: null });
      i++;
    } else {
      out.push({ type: "added", text: b[j], oldNumber: null, newNumber: newNo++ });
      j++;
    }
  }
  while (i < m) out.push({ type: "removed", text: a[i++], oldNumber: oldNo++, newNumber: null });
  while (j < n) out.push({ type: "added", text: b[j++], oldNumber: null, newNumber: newNo++ });

  return out;
}

/** True when the two texts are identical (no add/remove rows). */
export function isUnchanged(lines: DiffLine[]): boolean {
  return lines.every((line) => line.type === "context");
}
