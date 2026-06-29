import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

/**
 * Wraps a disabled control so it still explains *why* it's disabled on hover/focus. The span wrapper
 * is required because a disabled control (button, select trigger) emits none of the pointer/focus
 * events the tooltip listens for. Shared by every role-gated affordance — buttons via
 * DisabledActionButton, the golden-set select — so the "you can't do this" message is identical.
 */
export function DisabledTooltip({ reason, children }: { reason: string; children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span tabIndex={0}>{children}</span>
      </TooltipTrigger>
      <TooltipContent>{reason}</TooltipContent>
    </Tooltip>
  );
}
