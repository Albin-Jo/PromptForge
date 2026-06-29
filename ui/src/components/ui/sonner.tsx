import { Toaster as Sonner } from "sonner";
import type { ComponentProps } from "react";

import { useTheme } from "@/lib/theme/ThemeProvider";

// shadcn's sonner wrapper, adapted to PromptForge's ThemeProvider (the canonical
// version reads next-themes). We pass the *resolved* theme so toasts match the
// active light/dark surface, and lean on our design tokens for the toast chrome.
function Toaster({ ...props }: ComponentProps<typeof Sonner>) {
  const { resolvedTheme } = useTheme();

  return (
    <Sonner
      theme={resolvedTheme}
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-background group-[.toaster]:text-foreground group-[.toaster]:border-border group-[.toaster]:shadow-lg",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
