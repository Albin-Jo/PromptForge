import { cn } from "@/lib/utils";

// The PromptForge brand mark: a cobalt tile with a stacked-layers glyph that nods to the
// product's core idea — versioned prompts stacked into an immutable history. Deliberately
// theme-independent (a fixed cobalt gradient, white glyph) so the logo reads the same in
// light and dark, the way a real brand mark should.
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid size-7 shrink-0 place-items-center rounded-lg text-white shadow-sm ring-1 ring-inset ring-white/15",
        className,
      )}
      style={{
        backgroundImage:
          "linear-gradient(145deg, oklch(0.63 0.16 250), oklch(0.47 0.16 262))",
      }}
    >
      <svg viewBox="0 0 24 24" className="size-[62%]" fill="none">
        <path d="M12 3 3 7.5 12 12l9-4.5L12 3Z" fill="currentColor" fillOpacity="0.95" />
        <path
          d="M3 12l9 4.5 9-4.5"
          stroke="currentColor"
          strokeOpacity="0.65"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M3 16.5 12 21l9-4.5"
          stroke="currentColor"
          strokeOpacity="0.4"
          strokeWidth="1.7"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  );
}
