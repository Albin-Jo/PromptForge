// Mirrors the API's dataset DTOs (api/.../schemas.py).
//
// A golden set is the curated input→reference cases a prompt is graded against; attaching one is
// what makes a prompt promotable. The list view carries only a count; the detail read carries the
// cases (what the editor prefills from).

// One golden-set case: an input and (optionally) the reference answer to grade against.
// `metadata` is carried through edits unchanged — the editor doesn't expose it yet (Sprint 16f),
// but PUT replaces the whole case list (ADR 0024), so we round-trip it to avoid silently dropping
// per-case tags/hints someone set via the API.
export interface DatasetItem {
  input: string;
  reference: string | null;
  metadata: Record<string, unknown> | null;
}

// Mirrors DatasetRead — a golden set in the list view (item count, no case bodies).
export interface DatasetSummary {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  item_count: number;
}

// Mirrors DatasetDetail — one golden set *with* its cases (the editor prefill).
export interface DatasetDetail extends DatasetSummary {
  items: DatasetItem[];
}

// POST body — name is settable only on create.
export interface DatasetCreate {
  name: string;
  description: string | null;
  items: DatasetItem[];
}

// PUT body — name is immutable (path), cases are replaced wholesale (ADR 0024).
export interface DatasetUpdate {
  description: string | null;
  items: DatasetItem[];
}
