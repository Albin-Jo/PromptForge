import { QueryClient } from "@tanstack/react-query";

// One shared client for the whole app. Defaults are deliberately conservative for a
// data-management tool: don't spam the API on every window focus, and treat data as
// fresh for a short window so navigating back to a list doesn't always refetch.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
