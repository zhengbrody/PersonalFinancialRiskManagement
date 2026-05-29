/**
 * Shared test helpers — keep the per-test boilerplate small.
 */

import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Wrap a render with a fresh React Query client. Each test gets its
 * own client so caches never leak between tests.
 *
 * Retries disabled — tests should see failures immediately, not after
 * a backoff. `gcTime: 0` keeps memory clean between renders.
 */
export function renderWithQuery(
  ui: React.ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(ui, {
    ...options,
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}
