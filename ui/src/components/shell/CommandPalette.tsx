import { useNavigate } from "react-router-dom";
import { Blocks, Database, Plus, ScrollText } from "lucide-react";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { NAV_ITEMS } from "@/lib/nav";
import type { NavItem } from "@/lib/nav";
import { usePrompts } from "@/lib/prompts/api";
import { useBlocks } from "@/lib/blocks/api";
import { useDatasets } from "@/lib/datasets/api";
import { useCan } from "@/lib/auth/AuthContext";

type CommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Role-filtered nav entries from AppLayout; defaults to the full set when used standalone.
  navItems?: NavItem[];
};

// ⌘/Ctrl-K palette. Navigation actions come from the shared nav config; the create verbs and
// the jump-to groups (prompts, blocks, golden sets) reuse the same cached list hooks the list
// pages use, so the palette can never drift from them. cmdk fuzzy-filters everything client-side
// — the `value` strings are prefixed with the entity word so typing "block"/"golden" narrows fast.
export function CommandPalette({ open, onOpenChange, navItems = NAV_ITEMS }: CommandPaletteProps) {
  const navigate = useNavigate();
  const { data: prompts } = usePrompts();
  const { data: blocks } = useBlocks();
  const { data: datasets } = useDatasets();
  // Create verbs are editor+ (same gate as the create pages they open), so viewers don't see an
  // action they can't complete — mirrors the role filter already applied to admin-only nav items.
  const canCreate = useCan("editor");

  // Close the palette, then run the action — so the dialog isn't still mounted mid-navigate.
  function run(action: () => void) {
    onOpenChange(false);
    action();
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput placeholder="Type a command or search…" />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <CommandItem
                key={item.to}
                value={item.label}
                onSelect={() => run(() => navigate(item.to))}
              >
                <Icon />
                {item.label}
              </CommandItem>
            );
          })}
        </CommandGroup>

        {canCreate && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Create">
              <CommandItem value="New prompt" onSelect={() => run(() => navigate("/prompts/new"))}>
                <Plus />
                New prompt
              </CommandItem>
              <CommandItem value="New block" onSelect={() => run(() => navigate("/blocks/new"))}>
                <Plus />
                New block
              </CommandItem>
              <CommandItem
                value="New golden set"
                onSelect={() => run(() => navigate("/datasets/new"))}
              >
                <Plus />
                New golden set
              </CommandItem>
            </CommandGroup>
          </>
        )}

        {prompts && prompts.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Jump to prompt">
              {prompts.map((p) => (
                <CommandItem
                  key={p.name}
                  value={`prompt ${p.name}`}
                  onSelect={() =>
                    run(() => navigate(`/prompts/${encodeURIComponent(p.name)}/edit`))
                  }
                >
                  <ScrollText />
                  {p.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {blocks && blocks.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Jump to block">
              {blocks.map((b) => (
                <CommandItem
                  key={b.name}
                  value={`block ${b.name}`}
                  onSelect={() => run(() => navigate(`/blocks/${encodeURIComponent(b.name)}`))}
                >
                  <Blocks />
                  {b.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}

        {datasets && datasets.length > 0 && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Jump to golden set">
              {datasets.map((d) => (
                <CommandItem
                  key={d.name}
                  value={`golden set ${d.name}`}
                  // No dataset detail route exists — the edit page is the only landing surface.
                  onSelect={() =>
                    run(() => navigate(`/datasets/${encodeURIComponent(d.name)}/edit`))
                  }
                >
                  <Database />
                  {d.name}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
