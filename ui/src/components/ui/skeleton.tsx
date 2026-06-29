import * as React from "react";

import { cn } from "@/lib/utils";

// A shimmering placeholder for loading states (used by 16d's loading skeletons).
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn("bg-accent animate-pulse rounded-md", className)}
      {...props}
    />
  );
}

export { Skeleton };
