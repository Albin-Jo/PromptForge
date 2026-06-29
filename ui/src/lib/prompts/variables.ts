// Client-side mirror of the server's variable contract (api/.../templating.py:
// check_variable_contract). The editor uses it to warn about declared/detected mismatches
// *before* a save round-trips to a 422. It must stay faithful to the backend rule:
//
//   required = {{placeholders}} in the body  ∪  variables contributed by composed blocks
//   declared = the author's "Input variables" list
//   a save is rejected if any required var is undeclared, or any declared var is unused.
//
// The server computes the block contribution over the *transitive* subgraph (a block can
// compose other blocks); the caller here passes only the *direct* blocks' input_variables.
// Those sets are equal because every stored block version's input_variables already covers
// its own inherited vars — the same contract is enforced at block creation. If that block
// validation ever changes, this direct-union shortcut stops mirroring the server.
//
// This is advisory, not authoritative — the server stays the source of truth.

// A placeholder is {{ name }} with optional surrounding whitespace; a name is a plain
// identifier. Anything fancier (dots, calls, filters) is literal text, never a variable —
// the exact same shape as the backend regex, so the two can't disagree on what counts.
const PLACEHOLDER = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;

/** The distinct variable names referenced by {{ ... }} in *content*, in first-seen order. */
export function detectVariables(content: string): string[] {
  const seen = new Set<string>();
  for (const match of content.matchAll(PLACEHOLDER)) seen.add(match[1]);
  return [...seen];
}

export interface VariableContract {
  /** Variables referenced by {{...}} in the body. */
  detected: string[];
  /** detected ∪ block-contributed — the full set the server requires be declared. */
  required: string[];
  /** Required but not declared — a guaranteed server error (422), blocks or not. */
  undeclared: string[];
  /** Declared but not required — also a server error, unless an unresolved block consumes it. */
  unused: string[];
}

/**
 * Diff the author's declared variables against what the prompt (and its blocks) actually need.
 * `blockVariables` is the union of the pinned block versions' own `input_variables`; pass `[]`
 * for a prompt with no composition.
 */
export function checkVariableContract(
  content: string,
  declared: string[],
  blockVariables: string[],
): VariableContract {
  const detected = detectVariables(content);
  const required = new Set([...detected, ...blockVariables]);
  const declaredSet = new Set(declared);
  const undeclared = [...required].filter((v) => !declaredSet.has(v)).sort();
  const unused = [...declaredSet].filter((v) => !required.has(v)).sort();
  return { detected, required: [...required].sort(), undeclared, unused };
}
