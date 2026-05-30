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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

// ── macro ────────────────────────────────────────────────────────

export type MacroSeriesPoint = { date: string; value: number };

export type MacroSeries = {
  series_id: string;
  label: string;
  latest_value: number | null;
  latest_date: string | null;
  points: MacroSeriesPoint[];
};

export type MacroSeriesBatch = { series: MacroSeries[] };

export type YieldCurvePoint = { tenor: string; yield_pct: number };

export type YieldCurve = { as_of: string; points: YieldCurvePoint[] };

// ── hooks ─────────────────────────────────────────────────────────

// ── portfolio CRUD payload types ──────────────────────────────────

export type PortfolioHoldingInput = {
  shares: number;
  avg_cost?: number;
  sector?: string;
  asset_type?: string;
};

export type PortfolioCreateInput = {
  name: string;
  holdings: Record<string, PortfolioHoldingInput>;
  margin_loan?: number;
  contributed_capital?: number;
  cash_balance?: number;
  is_default?: boolean;
};

export type PortfolioPatchInput = Partial<PortfolioCreateInput>;

// ── hooks ────────────────────────────────────────────────────────

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
 * Latest values for a small set of public macro series. Public
 * endpoint, no auth — cached server-side for an hour, so the home-
 * page widget can hammer this without burning rate budget.
 */
export function useMacroSnapshot(seriesIds: string[]) {
  const key = seriesIds.join(",");
  return useQuery<MacroSeriesBatch>({
    queryKey: ["macro", "series", key],
    queryFn: () =>
      apiFetch<MacroSeriesBatch>(
        `/api/v1/macro/series?series=${encodeURIComponent(key)}&days=180`,
      ),
    // Macro updates daily — 10 minutes of client-side staleness is fine.
    staleTime: 10 * 60 * 1000,
  });
}

/**
 * Latest US Treasury yield curve. Public, server-cached 1h.
 */
export function useYieldCurve() {
  return useQuery<YieldCurve>({
    queryKey: ["macro", "yield_curve"],
    queryFn: () => apiFetch<YieldCurve>("/api/v1/macro/yield_curve"),
    staleTime: 10 * 60 * 1000,
  });
}

/** Invalidate the portfolios list so the next render refetches. */
function invalidatePortfoliosKey(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["portfolios"] });
}

export function useCreatePortfolio() {
  const { accessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<PortfolioRow, Error, PortfolioCreateInput>({
    mutationFn: (body) =>
      apiFetch<PortfolioRow>("/api/v1/portfolios", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
      }),
    onSuccess: () => invalidatePortfoliosKey(qc),
  });
}

export function useUpdatePortfolio(portfolioId: string) {
  const { accessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<PortfolioRow, Error, PortfolioPatchInput>({
    mutationFn: (body) =>
      apiFetch<PortfolioRow>(`/api/v1/portfolios/${portfolioId}`, {
        method: "PATCH",
        body,
        authToken: accessToken ?? undefined,
      }),
    onSuccess: () => invalidatePortfoliosKey(qc),
  });
}

export function useDeletePortfolio() {
  const { accessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<{ deleted: boolean; id: string }, Error, string>({
    mutationFn: (portfolioId) =>
      apiFetch<{ deleted: boolean; id: string }>(
        `/api/v1/portfolios/${portfolioId}`,
        {
          method: "DELETE",
          authToken: accessToken ?? undefined,
        },
      ),
    onSuccess: () => invalidatePortfoliosKey(qc),
  });
}

// ── billing ──────────────────────────────────────────────────────

export type SubscriptionRow = {
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  plan: string | null;
  status: string | null;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean | null;
};

export type PlanCard = {
  plan: string;
  label: string;
  price_usd_per_month: number;
  monthly_analysis: number;
  monthly_chat: number;
};

export type BillingMe = {
  user_id: string;
  email: string | null;
  plan: string;
  subscription: SubscriptionRow | null;
  plans: PlanCard[];
};

export type CheckoutSessionResponse = {
  checkout_url: string;
  session_id: string;
};

export type PortalSessionResponse = { portal_url: string };

/** Plan + subscription snapshot for the signed-in user. */
export function useBillingMe() {
  const { accessToken, user } = useAuth();
  return useQuery<BillingMe>({
    queryKey: ["billing", "me", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<BillingMe>("/api/v1/billing/me", {
        authToken: accessToken!,
      }),
    staleTime: 30 * 1000,
  });
}

/**
 * Start a Stripe Checkout flow. The mutation resolves to the hosted
 * Stripe URL; the caller does `window.location.href = url` to send
 * the user to Stripe's page. Stripe handles card capture + 3DS and
 * fires the webhook back into our Supabase Edge Function.
 */
export function useStartCheckout() {
  const { accessToken } = useAuth();
  return useMutation<
    CheckoutSessionResponse,
    Error,
    { plan: "basic" | "pro"; success_path?: string; cancel_path?: string }
  >({
    mutationFn: (body) =>
      apiFetch<CheckoutSessionResponse>("/api/v1/billing/checkout_session", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
      }),
  });
}

/** Open the Stripe Customer Portal (manage card, switch plan, cancel). */
export function useStartPortal() {
  const { accessToken } = useAuth();
  return useMutation<
    PortalSessionResponse,
    Error,
    { return_path?: string } | void
  >({
    mutationFn: (body) =>
      apiFetch<PortalSessionResponse>("/api/v1/billing/portal_session", {
        method: "POST",
        body: body ?? {},
        authToken: accessToken ?? undefined,
      }),
  });
}

// ── risk report ──────────────────────────────────────────────────

export type FactorBetaRow = {
  factor: string;
  beta: number | null;
  r_squared: number | null;
  t_stat: number | null;
  p_value: number | null;
};

export type ComponentVarRow = { ticker: string; pct: number };

export type StressAssetLoss = { ticker: string; loss_pct: number };

export type LiquidityRow = {
  ticker: string;
  days_to_liquidate: number | null;
  adv_30d: number | null;
  market_value: number | null;
};

export type RiskReport = {
  annual_return: number | null;
  annual_volatility: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  var_95: number | null;
  var_99: number | null;
  cvar_95: number | null;
  risk_free_rate: number | null;
  betas: Record<string, number>;
  factor_betas: FactorBetaRow[];
  component_var_pct: ComponentVarRow[];
  stress_loss: number | null;
  stress_market_shock: number | null;
  stress_asset_losses: StressAssetLoss[];
  macro_betas: Record<string, number>;
  liquidity: LiquidityRow[];
  drawdown_stats: Record<string, unknown> | null;
};

export type ReportFromActiveBody = {
  risk_preference?: number;
  risk_free_rate?: number;
  history_days?: number;
  market_shock?: number;
};

/**
 * Fetch the full risk report for the user's active portfolio. The
 * backend pulls real prices, runs Monte Carlo VaR, factor regressions,
 * and stress tests. Heavier than the score endpoint — expect a few
 * seconds on cold cache.
 *
 * Mutation rather than query so the user explicitly triggers it
 * (avoid auto-fetching on page mount when the heavy compute hasn't
 * been requested).
 */
export function useRiskReport() {
  const { accessToken } = useAuth();
  return useMutation<RiskReport, Error, ReportFromActiveBody | void>({
    mutationFn: (body) =>
      apiFetch<RiskReport>("/api/v1/risk/report_from_active", {
        method: "POST",
        body: body ?? {},
        authToken: accessToken ?? undefined,
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
