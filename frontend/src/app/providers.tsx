"use client";

/**
 * Client-side provider stack mounted by the root layout.
 *
 * Order matters:
 *   * QueryClientProvider must wrap anything that calls `useQuery`.
 *   * AuthProvider wraps the queries because protected queries pull
 *     `accessToken` from auth state to seed `apiFetch({ authToken })`.
 *
 * `QueryClient` is created via `useState` so React keeps the same
 * instance across renders. Putting `new QueryClient()` at module
 * scope works for SPAs but breaks under Next.js streaming where
 * different requests can share a server worker.
 */

import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth-context";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Auth-sensitive data refetches when the tab regains focus
            // so a freshly-signed-in window doesn't stay stale.
            refetchOnWindowFocus: true,
            // Treat data as fresh for 30s — saves hitting the API on
            // every nav between cached pages.
            staleTime: 30_000,
            // One retry is usually enough; the envelope wrapper already
            // distinguishes network vs server errors via ApiError.
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
