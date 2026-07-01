import { Link, useLocation } from "react-router-dom";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/shell/BrandMark";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { NAV_ITEMS } from "@/lib/nav";
import type { NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";

type SidebarProps = {
  // Desktop collapse state. The mobile Sheet always renders expanded.
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  // When rendered inside the mobile Sheet, clicking a link should close the sheet.
  onNavigate?: () => void;
  // The nav entries to show — already role-filtered by AppLayout. Defaults to the full set so the
  // component is usable on its own (e.g. in isolation tests).
  navItems?: NavItem[];
};

// A lean, owned sidebar: brand + primary nav + a collapse toggle. No submenus or rails we
// don't use. Collapsing shrinks it to an icon rail; labels hide and tooltips take over.
export function Sidebar({
  collapsed = false,
  onToggleCollapsed,
  onNavigate,
  navItems = NAV_ITEMS,
}: SidebarProps) {
  const { pathname } = useLocation();

  return (
    <div className="bg-sidebar text-sidebar-foreground flex h-full flex-col border-r">
      {/* Brand */}
      <div
        className={cn(
          "flex h-14 items-center border-b px-4",
          collapsed && "justify-center px-0",
        )}
      >
        <Link
          to="/"
          onClick={onNavigate}
          aria-label="PromptForge home"
          className="flex items-center gap-2.5"
        >
          <BrandMark />
          {!collapsed && (
            <span className="text-[15px] font-semibold tracking-tight">PromptForge</span>
          )}
        </Link>
      </div>

      {/* Primary nav */}
      <nav className="flex flex-1 flex-col gap-1 p-2">
        {navItems.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          const link = (
            <Link
              key={item.to}
              to={item.to}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                active
                  ? "bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary"
                  : "text-sidebar-foreground/70",
                // A cobalt spine on the active item — the accent's clearest, most restrained use.
                active && !collapsed && "shadow-[inset_2px_0_0_0_var(--primary)]",
                collapsed && "justify-center px-0",
              )}
            >
              <Icon className="size-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );

          // When collapsed, a tooltip surfaces the label the icon is hiding.
          return collapsed ? (
            <Tooltip key={item.to}>
              <TooltipTrigger asChild>{link}</TooltipTrigger>
              <TooltipContent side="right">{item.label}</TooltipContent>
            </Tooltip>
          ) : (
            link
          );
        })}
      </nav>

      {/* Collapse toggle — desktop only (the mobile Sheet has its own close button). */}
      {onToggleCollapsed && (
        <div className="border-t p-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="w-full"
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
          </Button>
        </div>
      )}
    </div>
  );
}
