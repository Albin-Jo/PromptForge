import type { PromptRollup } from "./types";

// Sorting for the fleet "all prompts" table. Pure + framework-free so the null handling and the
// deterministic tiebreak are unit-testable without rendering the table.

export type SortKey = "name" | "request_count" | "error_rate" | "p95_ms" | "cost_usd" | "quality";
export type SortDir = "asc" | "desc";

// The comparable value for a column. Money stays the exact decimal STRING in the model — Number()
// here is for *ordering only*, never displayed. Nullish sinks to the bottom of a desc sort.
function sortValue(p: PromptRollup, key: SortKey): number | string {
  switch (key) {
    case "name":
      return p.name;
    case "cost_usd":
      return p.cost_usd === null ? Number.NEGATIVE_INFINITY : Number(p.cost_usd);
    default: {
      const v = p[key];
      return v === null ? Number.NEGATIVE_INFINITY : v;
    }
  }
}

/**
 * Sort a copy of the rollups by one column + direction, always breaking ties by name (ascending) so
 * the order is deterministic — two prompts with the same or absent metric never jitter between
 * fetches. Comparison uses `<` rather than subtraction so two null (`-Infinity`) values compare
 * equal instead of producing `NaN`.
 */
export function sortPrompts(
  prompts: PromptRollup[],
  sort: { key: SortKey; dir: SortDir },
): PromptRollup[] {
  const rows = [...prompts];
  rows.sort((a, b) => {
    const av = sortValue(a, sort.key);
    const bv = sortValue(b, sort.key);
    let cmp: number;
    if (typeof av === "string" || typeof bv === "string") {
      cmp = String(av).localeCompare(String(bv));
    } else if (av === bv) {
      cmp = 0;
    } else {
      cmp = av < bv ? -1 : 1;
    }
    const directional = sort.dir === "asc" ? cmp : -cmp;
    return directional || a.name.localeCompare(b.name);
  });
  return rows;
}
