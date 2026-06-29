// Role-gate logic for the UI's write actions (Sprint 16e).
//
// Roles are hierarchical: an admin can do everything an editor can. We encode that with a rank
// instead of equality checks so `roleSatisfies(role, "editor")` is true for both editor and admin.
// Kept free of React so it's unit-testable on its own; the `useCan` hook (AuthContext) wraps it.
//
// Scope note: this is deliberately just admin-vs-editor — not an action→permission map. RBAC depth
// is out of scope for v0.1 (see sprint/00-overview.md). 16f/16g consume this same helper.

// The roles the API issues today (api/.../db/user_models.py). Ordered low → high privilege.
const ROLE_RANK = { editor: 1, admin: 2 } as const;

export type Role = keyof typeof ROLE_RANK;

/**
 * Does `userRole` meet the `required` role bar? Hierarchical: admin satisfies editor.
 * Unknown/undefined roles (logged-out, restoring, or a role we don't recognise) rank 0 and are
 * denied — fail closed.
 */
export function roleSatisfies(userRole: string | undefined, required: Role): boolean {
  const have = ROLE_RANK[userRole as Role] ?? 0;
  return have >= ROLE_RANK[required];
}
