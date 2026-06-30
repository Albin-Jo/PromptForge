// A small copy-to-clipboard button with success/failure feedback. Reusable wherever the UI shows
// copyable text (introduced for the trace drill-down's rendered prompt + output, Sprint 24 T4).

import { useState } from "react";
import { toast, toastError } from "../lib/toast";
import { Button } from "./ui/button";

export function CopyButton({
  text,
  label = "Copy",
}: {
  text: string;
  /** Accessible label / button text — distinguishes multiple copy buttons (e.g. "Copy prompt"). */
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success("Copied to clipboard");
      // Revert the label after a beat so the button reads "Copy" again.
      window.setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      toastError(err, "Couldn't copy to the clipboard.");
    }
  }

  return (
    <Button variant="outline" size="sm" onClick={copy} aria-label={label}>
      {copied ? "Copied" : label}
    </Button>
  );
}
