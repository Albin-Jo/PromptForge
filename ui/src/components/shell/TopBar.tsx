import { Fragment } from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronRight, LogOut, Menu, Monitor, Moon, Search, Sun, User } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ThemeToggle } from "@/components/ThemeToggle";
import { buildBreadcrumbs } from "@/components/shell/breadcrumbs";
import { useAuth } from "@/lib/auth/AuthContext";
import { useTheme } from "@/lib/theme/ThemeProvider";
import type { Theme } from "@/lib/theme/ThemeProvider";

type TopBarProps = {
  // Opens the mobile sidebar Sheet (shown only below md).
  onOpenMobileSidebar: () => void;
  // Opens the ⌘K command palette.
  onOpenCommand: () => void;
  onLogout: () => void;
};

export function TopBar({ onOpenMobileSidebar, onOpenCommand, onLogout }: TopBarProps) {
  const { pathname } = useLocation();
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  const crumbs = buildBreadcrumbs(pathname);

  return (
    <header className="bg-background/85 supports-[backdrop-filter]:bg-background/70 sticky top-0 z-30 flex h-14 items-center gap-3 border-b px-4 backdrop-blur-md">
      {/* Mobile: open the sidebar sheet */}
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        aria-label="Open navigation"
        onClick={onOpenMobileSidebar}
      >
        <Menu />
      </Button>

      {/* Breadcrumbs */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-sm">
        {crumbs.map((crumb, i) => {
          const isLast = i === crumbs.length - 1;
          return (
            <Fragment key={`${crumb.label}-${i}`}>
              {i > 0 && (
                <ChevronRight className="text-muted-foreground size-3.5 shrink-0" />
              )}
              {crumb.to && !isLast ? (
                <Link
                  to={crumb.to}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className={isLast ? "text-foreground font-medium" : "text-muted-foreground"}
                  aria-current={isLast ? "page" : undefined}
                >
                  {crumb.label}
                </span>
              )}
            </Fragment>
          );
        })}
      </nav>

      <div className="ml-auto flex items-center gap-1">
        {/* Command-palette trigger: full pill on desktop, icon-only on mobile. */}
        <Button
          variant="outline"
          size="sm"
          onClick={onOpenCommand}
          className="text-muted-foreground hidden h-8 gap-2 sm:flex"
        >
          <Search className="size-3.5" />
          <span>Search…</span>
          <kbd className="bg-muted pointer-events-none ml-2 inline-flex h-5 items-center gap-1 rounded border px-1.5 text-[10px] font-medium">
            ⌘K
          </kbd>
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="sm:hidden"
          aria-label="Search"
          onClick={onOpenCommand}
        >
          <Search />
        </Button>

        <ThemeToggle />

        {/* User menu: email + 3-way theme choice + logout */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="User menu">
              <User />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
            {user && (
              <DropdownMenuLabel className="font-normal">
                <div className="truncate">{user.email}</div>
                {user.role && (
                  <div className="text-muted-foreground text-xs capitalize">{user.role}</div>
                )}
              </DropdownMenuLabel>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-muted-foreground text-xs">
              Theme
            </DropdownMenuLabel>
            <DropdownMenuRadioGroup
              value={theme}
              onValueChange={(v) => setTheme(v as Theme)}
            >
              <DropdownMenuRadioItem value="light">
                <Sun className="mr-2 size-4" /> Light
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="dark">
                <Moon className="mr-2 size-4" /> Dark
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="system">
                <Monitor className="mr-2 size-4" /> System
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={onLogout}>
              <LogOut className="mr-2 size-4" /> Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
