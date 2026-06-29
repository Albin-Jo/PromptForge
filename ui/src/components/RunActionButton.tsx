import { Button } from "./ui/button";
import { DisabledTooltip } from "./DisabledTooltip";

/**
 * A disabled action button that still explains *why* it's disabled on hover/focus. Shared by every
 * role-gated control (run eval/scan, promote) so the "you can't do this" affordance is identical.
 * Delegates the span+tooltip plumbing to DisabledTooltip so non-button controls share it too.
 */
export function DisabledActionButton({ label, reason }: { label: string; reason: string }) {
  return (
    <DisabledTooltip reason={reason}>
      <Button size="sm" variant="outline" disabled>
        {label}
      </Button>
    </DisabledTooltip>
  );
}

// The shared "trigger an async run" button used by the on-demand eval + scan actions (Sprint 16e).
// Encapsulates the two cross-cutting concerns both share: role-gating (disabled + tooltip when the
// user can't run it, so they never fire a doomed request) and a busy state while a run is in flight.
export function RunActionButton({
  onRun,
  running,
  canRun,
  idleLabel,
  runningLabel,
  deniedReason,
}: {
  onRun: () => void;
  /** A run is currently in flight (mutation pending or a polled status still running). */
  running: boolean;
  /** The current user's role permits this action. */
  canRun: boolean;
  idleLabel: string;
  runningLabel: string;
  /** Tooltip shown on the disabled button when `canRun` is false. */
  deniedReason: string;
}) {
  if (!canRun) {
    return <DisabledActionButton label={idleLabel} reason={deniedReason} />;
  }

  return (
    <Button size="sm" variant="outline" onClick={onRun} disabled={running}>
      {running ? runningLabel : idleLabel}
    </Button>
  );
}
