// Mirrors the API's block schemas (api/.../schemas.py).

import type { BlockRef } from "../prompts/types";

export type BlockRole = "role" | "context" | "guardrails" | "output_format" | "other";

// Mirrors BlockVersionRead.
export interface BlockVersion {
  id: string;
  version_number: number;
  parent_version_id: string | null;
  content: string;
  input_variables: string[];
  created_at: string;
  // Pinned child-block refs this version composes from, in order (empty = leaf block). Populated
  // by the read endpoints so the editor can carry composition forward when adding a new version.
  blocks: BlockRef[];
}

// Mirrors BlockRead — a block with its version history.
export interface Block {
  id: string;
  name: string;
  role: BlockRole;
  description: string | null;
  created_at: string;
  updated_at: string;
  versions: BlockVersion[];
}

// Shared create/new-version body (mirrors BlockVersionContent). A block may compose other blocks,
// so it carries the same ordered, version-pinned BlockRefs a prompt version does.
export interface BlockVersionContent {
  content: string;
  input_variables: string[];
  blocks: BlockRef[];
}

// Request body for POST /blocks (mirrors BlockCreate) — block identity + its first version.
export interface BlockCreate extends BlockVersionContent {
  name: string;
  role: BlockRole;
  description?: string | null;
}

// Request body for POST /blocks/:name/versions (mirrors BlockVersionCreate).
export type BlockVersionCreate = BlockVersionContent;

// Mirrors ImpactedRefDTO.
export interface ImpactedRef {
  name: string;
  version_number: number;
}

// Mirrors BlockImpactResponse — the reverse dependency graph for one block.
export interface BlockImpact {
  block: string;
  prompts: ImpactedRef[];
  blocks: ImpactedRef[];
}
