import { useEffect, useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Sidebar } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { useAuth } from "@/lib/auth/AuthContext";
import { roleSatisfies } from "@/lib/auth/permissions";
import { NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";

// One content width for every route, so switching tabs never re-centers or resizes the
// column. Data-dense pages (tables) fill it; reading-oriented content (editor forms, detail
// panes) self-caps with its own max-w and sits at the left. The sidebar lives outside this
// column — only the main content is constrained.
const CONTENT_WIDTH = "max-w-[1400px]";
const COLLAPSE_KEY = "pf-sidebar-collapsed";

// The app shell: a persistent left sidebar (collapsible on desktop, a Sheet on mobile),
// a sticky top bar, and a width-aware <main> where the active route renders.
export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();

  // Role-filter the nav once here, then hand the same list to both the sidebar and the command
  // palette so they can't drift. Admin-only entries (Users) are hidden — not disabled — from anyone
  // who isn't an admin (Sprint 16g). Uses roleSatisfies (not useCan) so the role check stays a pure
  // function of the user we already hold.
  const navItems = useMemo(
    () => NAV_ITEMS.filter((item) => !item.adminOnly || roleSatisfies(user?.role, "admin")),
    [user?.role],
  );

  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === "true",
  );
  const [mobileOpen, setMobileOpen] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);

  // Persist the collapse choice (1A) so it survives reloads, like the theme.
  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, String(collapsed));
  }, [collapsed]);

  // Global ⌘K / Ctrl-K toggles the command palette.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setCommandOpen((o) => !o);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  // Close the mobile sheet whenever the route changes (a nav click navigated).
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="bg-background text-foreground flex min-h-screen">
      {/* Keyboard a11y: first tab stop jumps past the nav straight to the page body. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-sm focus:text-primary-foreground"
      >
        Skip to main content
      </a>

      {/* Desktop sidebar — reserves width in flow; the inner div sticks full-height. */}
      <aside
        className={cn(
          "hidden shrink-0 transition-[width] duration-200 md:block",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className="sticky top-0 h-screen">
          <Sidebar
            collapsed={collapsed}
            onToggleCollapsed={() => setCollapsed((c) => !c)}
            navItems={navItems}
          />
        </div>
      </aside>

      {/* Mobile sidebar as a slide-in Sheet */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-60 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Sidebar onNavigate={() => setMobileOpen(false)} navItems={navItems} />
        </SheetContent>
      </Sheet>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          onOpenMobileSidebar={() => setMobileOpen(true)}
          onOpenCommand={() => setCommandOpen(true)}
          onLogout={handleLogout}
        />
        <main id="main" className={cn("mx-auto w-full px-6 py-8", CONTENT_WIDTH)}>
          <Outlet />
        </main>
      </div>

      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} navItems={navItems} />
    </div>
  );
}
