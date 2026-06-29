import { Badge } from "./ui/badge";
import { SEVERITY_VARIANT } from "../lib/scans/presentation";
import type { Severity } from "../lib/scans/types";

// The shared scan-severity badge (high=danger … none=clean). Used by both the full scan page and the
// dashboard scan panel so the severity→colour mapping lives in exactly one place.
export function SeverityBadge({ severity }: { severity: Severity | "none" }) {
  return (
    <Badge variant={SEVERITY_VARIANT[severity]} className="uppercase tracking-wide">
      {severity}
    </Badge>
  );
}
