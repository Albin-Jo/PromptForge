import {
  Blocks,
  ClipboardList,
  Database,
  LayoutDashboard,
  ScrollText,
  ServerCog,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// The primary navigation, shared by the sidebar and the command palette (task #5) so they
// can never drift. `match` decides the active state from the current pathname.
export type NavItem = {
  label: string;
  to: string;
  icon: LucideIcon;
  match: (pathname: string) => boolean;
  // Admin-only sections are hidden from non-admins entirely (no editor-usable surface). Both the
  // sidebar and the command palette filter these out via `useCan("admin")` (Sprint 16g).
  adminOnly?: boolean;
};

export const NAV_ITEMS: NavItem[] = [
  {
    label: "Overview",
    to: "/",
    icon: LayoutDashboard,
    // The fleet overview is the index route.
    match: (p) => p === "/",
  },
  {
    label: "Prompts",
    to: "/prompts",
    icon: ScrollText,
    // The prompt list and every per-prompt page live under this section.
    match: (p) => p.startsWith("/prompts"),
  },
  {
    label: "Golden sets",
    to: "/datasets",
    icon: Database,
    // The dataset list and its create/edit pages live under this section.
    match: (p) => p.startsWith("/datasets"),
  },
  {
    label: "Blocks",
    to: "/blocks",
    icon: Blocks,
    // The block library and its detail/create/version pages live under this section.
    match: (p) => p.startsWith("/blocks"),
  },
  {
    label: "Users",
    to: "/users",
    icon: Users,
    // Admin-only user management (Sprint 16g) — hidden from non-admins.
    match: (p) => p.startsWith("/users"),
    adminOnly: true,
  },
  {
    label: "Activity",
    to: "/activity",
    icon: ClipboardList,
    // Admin-only audit log — hidden from non-admins.
    match: (p) => p.startsWith("/activity"),
    adminOnly: true,
  },
  {
    label: "Operations",
    to: "/operations",
    icon: ServerCog,
    // Admin-only async-backbone health — queue depth + worker liveness (Sprint 29).
    match: (p) => p.startsWith("/operations"),
    adminOnly: true,
  },
];
