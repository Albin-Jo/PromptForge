// Mirrors the API's ScanStatusResponse (api/.../schemas.py).
//
// The schema types `findings` loosely as list[dict[str, Any]], but every scanner serialises to the
// one shape below (api/.../scanning/finding.py::Finding.to_dict). We tighten it here so the
// scan-results view is fully typed.

// A version's derived scan lifecycle. "completed" means findings + risk_level are ready.
export type ScanStatus = "unscanned" | "pending" | "running" | "completed" | "failed";

// Rolled-up worst severity of a scan (and per-finding severity). Ordered low < medium < high.
export type Severity = "low" | "medium" | "high";

// The family of safety problem a finding belongs to — one per scanner.
export type Category = "injection" | "pii" | "secret" | "jailbreak";

// Mirrors Finding.to_dict — one thing a scanner flagged.
// `evidence` is already redacted by the scanner (we never store live secrets).
// `span` is [start, end] char offsets, or null when a detector reasons over the whole text.
export interface Finding {
  category: Category;
  severity: Severity;
  detector: string;
  message: string;
  evidence: string;
  span: [number, number] | null;
  metadata: Record<string, unknown>;
}

// Mirrors ScanStatusResponse — a version's scan state: risk level + findings.
// risk_level is the worst severity once completed, or "none" for a clean scan.
export interface VersionScanStatus {
  prompt: string;
  version_number: number;
  prompt_version_id: string;
  status: ScanStatus;
  latest_scan_id: string | null;
  risk_level: Severity | "none" | null;
  findings: Finding[] | null;
}

// Mirrors ScanAccepted — the 202 body when a scan is triggered on demand (Sprint 16e).
export interface ScanAccepted {
  security_scan_id: string;
  status: string;
}

// Mirrors ScanRunSummary — one row in a version's scan run-history list (newest first).
// `findings` carries the full list (so the drill-in needs no second call) and is null while the
// scan is pending/running or on failure; the list's finding count is derived from it.
export interface ScanRunSummary {
  id: string;
  status: ScanStatus;
  scanners: string[];
  risk_level: Severity | "none" | null;
  findings: Finding[] | null;
  created_at: string;
  completed_at: string | null;
}
