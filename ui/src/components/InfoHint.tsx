import { Info } from "lucide-react";

import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

// A small "ⓘ" affordance that reveals an explanatory tooltip on hover/focus. Used next to terse
// metric headers to surface scales/semantics without bloating the label. The trigger is a real
// focusable button and carries `text` as its aria-label, so the hint is reachable by keyboard and
// screen readers — not hover-only. (Deeper a11y polish is Sprint 26.)
export function InfoHint({ text, className }: { text: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={text}
          className={cn(
            "text-muted-foreground hover:text-foreground inline-flex align-middle",
            className,
          )}
        >
          <Info className="size-3" aria-hidden />
        </button>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </Tooltip>
  );
}
