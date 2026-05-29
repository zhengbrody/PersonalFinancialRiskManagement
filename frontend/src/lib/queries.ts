/**
 * Typed React Query hooks for backend endpoints.
 *
 * Keep the wiring (query keys, fetcher functions, auth-token plumbing)
 * here so pages stay declarative: `const { data, isLoading } =
 * useMyPortfolios()`. The query-key tuples are intentionally small
 * and stable — `['portfolios','me']` not `['portfolios','me', token]`
 * — because cache invalidation on sign-out is handled separately
 * (see `useAuth().signOut` → `queryClient.clear()` later).
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { apiFetch } from "./api";
import { useAuth } from "./auth-context";
import type {
  ScoreFromActiveRequest,
  ScoreResponse,
} from "./schemas";

// ── shapes (manual mirror — Phase 4 will pull from api-types once
// the portfolios route declares response_model) ───────────────────

export type PortfolioRow = {
  id: string;
  user_id: string | null;
  name: string;
  holdings: Record<string, { shares: number; avg_cost?: number } & Record<string, unknown>>;
  margin_loan: number | null;
  contributed_capital: number | null;
  cash_balance: number | null;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
};

export type PortfoliosMe = {
  user_id: string;
  email: string | null;
  portfolios: PortfolioRow[];
};

// ── hooks ─────────────────────────────────────────────────────────

export function useMyPortfolios() {
  const { accessToken, user } = useAuth();
  return useQuery<PortfoliosMe>({
    queryKey: ["portfolios", "me", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<PortfoliosMe>("/api/v1/portfolios/me", {
        authToken: accessToken!,
      }),
  });
}

/**
 * Score the user's active portfolio using real market data.
 *
 * Mutation rather than query because it's an explicit user action
 * (a button click) and we want each click to fire — not be cached
 * by a query key. Each click pulls fresh data through the backend's
 * 24h-cached market_data layer.
 */
export function useScoreActivePortfolio() {
  const { accessToken } = useAuth();
  return useMutation<ScoreResponse, Error, ScoreFromActiveRequest | void>({
    mutationFn: (body) =>
      apiFetch<ScoreResponse>("/api/v1/risk/score_from_active", {
        method: "POST",
        body: body ?? {},
        authToken: accessToken ?? undefined,
      }),
  });
}
