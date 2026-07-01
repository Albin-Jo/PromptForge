import type { AuditEvent } from "./types";

// Friendly labels for the known audit actions (ADR 0028). Anything not listed — a future action the
// backend grows, or a legacy verb — falls through to its raw string, so the feed never hides an
// event it doesn't recognise.
const ACTION_LABELS: Record<string, string> = {
  promoted: "Promoted",
  blocked: "Blocked",
  version_created: "Version created",
  label_set: "Label set",
  golden_set_attached: "Golden set attached",
  golden_set_detached: "Golden set detached",
  user_created: "User created",
};

/** A human-readable label for an audit action, falling back to the raw verb for unknown ones. */
export function formatAction(action: AuditEvent["action"]): string {
  return ACTION_LABELS[action] ?? action;
}
