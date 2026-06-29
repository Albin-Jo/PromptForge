import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// The shadcn class-merge helper. clsx resolves conditional/array class inputs into a
// string; twMerge then dedupes conflicting Tailwind utilities so the *last* one wins
// (e.g. cn("px-2", "px-4") -> "px-4"). Every primitive uses this to let callers override
// styles via a `className` prop without specificity fights.
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// Comma-separated input -> trimmed, de-duped, non-empty list. The shared contract for the
// `input_variables` field on the prompt and block editors (must match the {{placeholders}} in
// the content). One copy so the two forms can't drift.
export function parseVariables(raw: string): string[] {
  const seen = new Set<string>();
  for (const part of raw.split(",")) {
    const trimmed = part.trim();
    if (trimmed) seen.add(trimmed);
  }
  return [...seen];
}
