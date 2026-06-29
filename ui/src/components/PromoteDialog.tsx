import { useState } from "react";
import {
  asPromotionBlocked,
  asPromotionPending,
  useSetLabel,
} from "../lib/prompts/api";
import { isEvalRunning, useVersionEval } from "../lib/evals/api";
import { isScanRunning, useVersionScan } from "../lib/scans/api";
import type { PromotionBlockedBody, PromotionDelta, PromotionPendingBody } from "../lib/prompts/types";
import { toast, toastError } from "../lib/toast";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { DisabledActionButton } from "./RunActionButton";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "./ui/table";
import { cn } from "../lib/utils";

// The labels a user can promote to. Only the gated label runs the quality gate; the rest move
// freely. Kept here (not config) — RBAC/label-policy depth is out of v0.1 scope.
const PROMOTABLE_LABELS = ["production", "staging"] as const;
type PromotableLabel = (typeof PROMOTABLE_LABELS)[number];

const selectClasses =
  "rounded-md border border-input bg-background text-foreground shadow-sm px-2 py-1 text-sm " +
  "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

function fmt(value: number | null): string {
  return value === null ? "—" : value.toFixed(2);
}

// The promote flow is a little state machine: confirm → (success | blocked | pending → retry).
type Phase = "confirm" | "blocked" | "pending";

/**
 * Promote one version to a label, handling the gate's three real outcomes (Sprint 16e):
 * 200 promoted, 409 blocked-with-per-metric-scores, 409 pending-and-polling. Admin-only — when
 * `canPromote` is false the trigger is disabled with a tooltip, so a non-admin never fires a 403.
 */
export function PromoteDialog({
  name,
  versionNumber,
  canPromote,
}: {
  name: string;
  versionNumber: number;
  canPromote: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState<PromotableLabel>("production");
  const [phase, setPhase] = useState<Phase>("confirm");
  const [blocked, setBlocked] = useState<PromotionBlockedBody | null>(null);
  const [pending, setPending] = useState<PromotionPendingBody | null>(null);

  const mutation = useSetLabel(name);

  // Return to the confirm step, clearing any prior gate outcome so a stale blocked/pending detail
  // can't linger behind the next attempt.
  function goToConfirm() {
    setPhase("confirm");
    setBlocked(null);
    setPending(null);
    mutation.reset();
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) goToConfirm();
  }

  function promote() {
    mutation.mutate(
      { label, versionNumber },
      {
        onSuccess: () => {
          toast.success(`Promoted v${versionNumber} → ${label}`);
          handleOpenChange(false);
        },
        onError: (err) => {
          const blk = asPromotionBlocked(err);
          if (blk) {
            setBlocked(blk);
            setPhase("blocked");
            return;
          }
          const pend = asPromotionPending(err);
          if (pend) {
            setPending(pend);
            setPhase("pending");
            return;
          }
          // A real failure (403/500/network) — surface it, stay on the confirm step.
          toastError(err, "Could not promote this version.");
        },
      },
    );
  }

  // Non-admins: render a disabled trigger with a reason, never a clickable promote.
  if (!canPromote) {
    return <DisabledActionButton label="Promote" reason="Requires the admin role" />;
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          Promote
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Promote v{versionNumber}</DialogTitle>
          <DialogDescription>
            Point a label at this version. Moving <code>production</code> runs the quality gate.
          </DialogDescription>
        </DialogHeader>

        {phase === "confirm" && (
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Promote v{versionNumber} →</span>
            <select
              aria-label="Target label"
              value={label}
              onChange={(e) => setLabel(e.target.value as PromotableLabel)}
              className={cn(selectClasses)}
            >
              {PROMOTABLE_LABELS.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </div>
        )}

        {phase === "blocked" && blocked && <BlockedDetail blocked={blocked} />}

        {phase === "pending" && pending && (
          <PendingGate
            name={name}
            versionNumber={versionNumber}
            pending={pending}
            // Retry in place — promote()'s own onSuccess/onError drives the next transition, so we
            // stay on the pending step (showing "Promoting…") instead of flashing back to confirm.
            onRetry={promote}
            retrying={mutation.isPending}
          />
        )}

        <DialogFooter>
          {phase === "confirm" && (
            <Button onClick={promote} disabled={mutation.isPending}>
              {mutation.isPending ? "Promoting…" : "Promote"}
            </Button>
          )}
          {phase === "blocked" && (
            <Button variant="outline" onClick={goToConfirm}>
              Back
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// The 409-blocked body: this is a *refusal*, not an error. Lead with why, then the per-metric
// candidate-vs-baseline detail so the failing scorer is obvious.
function BlockedDetail({ blocked }: { blocked: PromotionBlockedBody }) {
  const { promotion } = blocked;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="warning">Blocked by gate</Badge>
        <span className="text-sm text-muted-foreground">{blocked.detail}</span>
      </div>

      {promotion.reasons.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-5 text-sm text-foreground">
          {promotion.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}

      {promotion.deltas.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Scorer</TableHead>
              <TableHead className="text-right">Candidate</TableHead>
              <TableHead className="text-right">Baseline</TableHead>
              <TableHead className="text-right">Drop</TableHead>
              <TableHead className="text-right">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {promotion.deltas.map((d) => (
              <DeltaRow key={d.scorer} delta={d} />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function DeltaRow({ delta }: { delta: PromotionDelta }) {
  const failed = !delta.floor_ok || delta.regression;
  return (
    <TableRow className={cn(failed && "bg-destructive/10")}>
      <TableCell className="font-medium text-foreground">{delta.scorer}</TableCell>
      <TableCell className="text-right tabular-nums">{fmt(delta.candidate)}</TableCell>
      <TableCell className="text-right tabular-nums text-muted-foreground">
        {fmt(delta.baseline)}
      </TableCell>
      <TableCell className="text-right tabular-nums">{fmt(delta.drop)}</TableCell>
      <TableCell className="text-right">
        {failed ? (
          <Badge variant="destructive">{delta.regression ? "regressed" : "below floor"}</Badge>
        ) : (
          <Badge variant="success">ok</Badge>
        )}
      </TableCell>
    </TableRow>
  );
}

// The 409-pending body: the gate run is still in flight. Poll the right status (eval or scan) to
// completion, then let the user retry the promote. Only the relevant query is enabled, so we don't
// fetch a status we don't need. Exported for direct testing of the poll→retry transition.
export function PendingGate({
  name,
  versionNumber,
  pending,
  onRetry,
  retrying,
}: {
  name: string;
  versionNumber: number;
  pending: PromotionPendingBody;
  onRetry: () => void;
  retrying: boolean;
}) {
  const isEvalGate = Boolean(pending.eval_run_id);

  const evalQuery = useVersionEval(name, isEvalGate ? versionNumber : undefined, {
    poll: isEvalGate,
  });
  const scanQuery = useVersionScan(name, !isEvalGate ? versionNumber : undefined, {
    poll: !isEvalGate,
  });

  // Treat "no data yet" as still running so we don't flash a premature "ready".
  const running = isEvalGate
    ? evalQuery.data === undefined || isEvalRunning(evalQuery.data.status)
    : scanQuery.data === undefined || isScanRunning(scanQuery.data.status);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="info">Gate running</Badge>
        <span className="text-sm text-muted-foreground">{pending.detail}</span>
      </div>
      <p className="text-sm text-muted-foreground">
        {running
          ? `Waiting for the ${isEvalGate ? "evaluation" : "security scan"} to finish…`
          : "Gate finished — you can retry the promote now."}
      </p>
      <DialogFooter>
        <Button onClick={onRetry} disabled={running || retrying}>
          {retrying ? "Promoting…" : "Retry promote"}
        </Button>
      </DialogFooter>
    </div>
  );
}
