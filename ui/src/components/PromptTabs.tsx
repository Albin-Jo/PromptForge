import { NavLink } from "react-router-dom";

import { cn } from "@/lib/utils";

// The per-prompt sub-navigation shown above Editor / Versions / Dashboard.
// These tabs are *routes*, so we keep NavLink (real anchors: middle-click, open-in-new-tab,
// aria-current for free) but borrow the Tabs primitive's look — a muted track with a raised
// active pill — so it matches the design system without a state-driven Radix Tabs.
export function PromptTabs({ name }: { name: string }) {
  const base = encodeURIComponent(name);
  const tabs = [
    { to: `/prompts/${base}/edit`, label: "Editor" },
    { to: `/prompts/${base}/versions`, label: "Versions" },
    { to: `/prompts/${base}/dashboard`, label: "Dashboard" },
  ];

  return (
    <nav className="bg-muted text-muted-foreground mb-6 inline-flex h-9 w-fit items-center justify-center rounded-lg p-1">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end
          className={({ isActive }) =>
            cn(
              "inline-flex items-center justify-center rounded-md px-3 py-1 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
              isActive
                ? "bg-background text-foreground shadow-sm"
                : "hover:text-foreground",
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
