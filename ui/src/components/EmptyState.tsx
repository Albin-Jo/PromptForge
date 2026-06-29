import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

// The designed "nothing here yet" surface every data page drops into QueryState's
// `empty` slot: a muted lucide icon, a title, an optional line of context, and a single
// primary action. Keeps empty states identical across the app (Sprint 16d DoD).
interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  /** Optional primary action — label + handler, or a fully custom node. */
  action?: { label: string; onClick: () => void } | ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  const isActionConfig =
    action != null &&
    typeof action === "object" &&
    "label" in action &&
    "onClick" in action;

  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      <Icon className="size-10 text-muted-foreground" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {isActionConfig ? (
        <Button
          onClick={(action as { onClick: () => void }).onClick}
          className="mt-1"
        >
          {(action as { label: string }).label}
        </Button>
      ) : (
        (action as ReactNode) ?? null
      )}
    </div>
  );
}
