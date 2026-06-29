// How a deployment label reads as a Badge: production is the headline (success), the rest are
// secondary pointers. Shared by the dashboard header's live-label badges and the By-version table
// marker so "what colour is production" is decided in exactly one place.

type BadgeVariant = "default" | "secondary" | "destructive" | "outline" | "success" | "warning";

export function labelVariant(label: string): BadgeVariant {
  return label === "production" ? "success" : "secondary";
}
