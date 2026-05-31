/**
 * Typed React Query hooks for backend endpoints.
 *
 * Keep the wiring (query keys, fetcher functions, auth-token plumbing)
 * here so pages stay declarative: `const { data, isLoading } =
 * useMyPortfolios()`. The query-key tuples are intentionally small
 * and stable — `['portfolios','me']` not `['portfolios','me', token]`
 * — because cache invalidation on sign-out is handled by
 * `useAuth().signOut` → `queryClient.clear()`.
 *
 * Response payloads are mirrored as zod schemas (not bare types) so
 * each hook passes `schema` into `apiFetch` and backend shape-drift
 * surfaces as a clean `invalid_response` error rather than an
 * `undefined` crash inside a component. TS types are derived via
 * `z.infer` so type and runtime guard can't drift.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { apiFetch } from "./api";
import { useAuth } from "./auth-context";
import {
  scoreResponseSchema,
  type ScoreFromActiveRequest,
  type ScoreResponse,
} from "./schemas";

// ── shapes (manual mirror — Phase 4 will pull from api-types once
// the portfolios route declares response_model) ───────────────────

export const portfolioRowSchema = z.looseObject({
  id: z.string(),
  user_id: z.string().nullable(),
  name: z.string(),
  holdings: z.record(
    z.string(),
    z.looseObject({ shares: z.number(), avg_cost: z.number().optional() }),
  ),
  margin_loan: z.number().nullable(),
  contributed_capital: z.number().nullable(),
  cash_balance: z.number().nullable(),
  is_default: z.boolean(),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});
export type PortfolioRow = z.infer<typeof portfolioRowSchema>;

export const portfoliosMeSchema = z.looseObject({
  user_id: z.string(),
  email: z.string().nullable(),
  portfolios: z.array(portfolioRowSchema),
});
export type PortfoliosMe = z.infer<typeof portfoliosMeSchema>;

// ── macro ────────────────────────────────────────────────────────

export const macroSeriesPointSchema = z.looseObject({
  date: z.string(),
  value: z.number(),
});
export type MacroSeriesPoint = z.infer<typeof macroSeriesPointSchema>;

export const macroSeriesSchema = z.looseObject({
  series_id: z.string(),
  label: z.string(),
  latest_value: z.number().nullable(),
  latest_date: z.string().nullable(),
  points: z.array(macroSeriesPointSchema),
});
export type MacroSeries = z.infer<typeof macroSeriesSchema>;

export const macroSeriesBatchSchema = z.looseObject({
  series: z.array(macroSeriesSchema),
});
export type MacroSeriesBatch = z.infer<typeof macroSeriesBatchSchema>;

export const yieldCurvePointSchema = z.looseObject({
  tenor: z.string(),
  yield_pct: z.number(),
});
export type YieldCurvePoint = z.infer<typeof yieldCurvePointSchema>;

export const yieldCurveSchema = z.looseObject({
  as_of: z.string(),
  points: z.array(yieldCurvePointSchema),
});
export type YieldCurve = z.infer<typeof yieldCurveSchema>;

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
        schema: portfoliosMeSchema,
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
        { schema: macroSeriesBatchSchema },
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
    queryFn: () =>
      apiFetch<YieldCurve>("/api/v1/macro/yield_curve", {
        schema: yieldCurveSchema,
      }),
    staleTime: 10 * 60 * 1000,
  });
}

// ── market regime ─────────────────────────────────────────────────

export const marketRegimeSchema = z.looseObject({
  vix: z.looseObject({
    current: z.number().nullable(),
    change: z.number().nullable(),
    level: z.string().nullable(),
  }),
  fear_greed: z.looseObject({
    score: z.number().nullable(),
    rating: z.string().nullable(),
  }),
  yield_curve: z.looseObject({
    status: z.string().nullable(),
    spread_3m_10y: z.number().nullable(),
    inverted: z.boolean().nullable(),
  }),
});
export type MarketRegime = z.infer<typeof marketRegimeSchema>;

/**
 * Market-regime snapshot (VIX / Fear & Greed / yield-curve status).
 * Public, server-cached ~5 min. Each leg is independently nullable, so
 * the panel renders partially when one upstream is down.
 */
export function useMarketRegime() {
  return useQuery<MarketRegime>({
    queryKey: ["macro", "regime"],
    queryFn: () =>
      apiFetch<MarketRegime>("/api/v1/macro/regime", {
        schema: marketRegimeSchema,
      }),
    staleTime: 5 * 60 * 1000,
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
        schema: portfolioRowSchema,
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
        schema: portfolioRowSchema,
      }),
    onSuccess: () => invalidatePortfoliosKey(qc),
  });
}

const deleteResultSchema = z.looseObject({
  deleted: z.boolean(),
  id: z.string(),
});

export function useDeletePortfolio() {
  const { accessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<z.infer<typeof deleteResultSchema>, Error, string>({
    mutationFn: (portfolioId) =>
      apiFetch(`/api/v1/portfolios/${portfolioId}`, {
        method: "DELETE",
        authToken: accessToken ?? undefined,
        schema: deleteResultSchema,
      }),
    onSuccess: () => invalidatePortfoliosKey(qc),
  });
}

// ── billing ──────────────────────────────────────────────────────

export const subscriptionRowSchema = z.looseObject({
  stripe_customer_id: z.string().nullable(),
  stripe_subscription_id: z.string().nullable(),
  plan: z.string().nullable(),
  status: z.string().nullable(),
  current_period_start: z.string().nullable(),
  current_period_end: z.string().nullable(),
  cancel_at_period_end: z.boolean().nullable(),
});
export type SubscriptionRow = z.infer<typeof subscriptionRowSchema>;

export const planCardSchema = z.looseObject({
  plan: z.string(),
  label: z.string(),
  price_usd_per_month: z.number(),
  monthly_analysis: z.number(),
  monthly_chat: z.number(),
});
export type PlanCard = z.infer<typeof planCardSchema>;

export const billingMeSchema = z.looseObject({
  user_id: z.string(),
  email: z.string().nullable(),
  plan: z.string(),
  subscription: subscriptionRowSchema.nullable(),
  plans: z.array(planCardSchema),
});
export type BillingMe = z.infer<typeof billingMeSchema>;

export const checkoutSessionResponseSchema = z.looseObject({
  checkout_url: z.string(),
  session_id: z.string(),
});
export type CheckoutSessionResponse = z.infer<
  typeof checkoutSessionResponseSchema
>;

export const portalSessionResponseSchema = z.looseObject({
  portal_url: z.string(),
});
export type PortalSessionResponse = z.infer<typeof portalSessionResponseSchema>;

/** Plan + subscription snapshot for the signed-in user. */
export function useBillingMe() {
  const { accessToken, user } = useAuth();
  return useQuery<BillingMe>({
    queryKey: ["billing", "me", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<BillingMe>("/api/v1/billing/me", {
        authToken: accessToken!,
        schema: billingMeSchema,
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
        schema: checkoutSessionResponseSchema,
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
        schema: portalSessionResponseSchema,
      }),
  });
}

// ── risk report ──────────────────────────────────────────────────

export const factorBetaRowSchema = z.looseObject({
  factor: z.string(),
  beta: z.number().nullable(),
  r_squared: z.number().nullable(),
  t_stat: z.number().nullable(),
  p_value: z.number().nullable(),
});
export type FactorBetaRow = z.infer<typeof factorBetaRowSchema>;

export const componentVarRowSchema = z.looseObject({
  ticker: z.string(),
  pct: z.number(),
});
export type ComponentVarRow = z.infer<typeof componentVarRowSchema>;

export const stressAssetLossSchema = z.looseObject({
  ticker: z.string(),
  loss_pct: z.number(),
});
export type StressAssetLoss = z.infer<typeof stressAssetLossSchema>;

export const liquidityRowSchema = z.looseObject({
  ticker: z.string(),
  days_to_liquidate: z.number().nullable(),
  adv_30d: z.number().nullable(),
  market_value: z.number().nullable(),
});
export type LiquidityRow = z.infer<typeof liquidityRowSchema>;

export const riskReportSchema = z.looseObject({
  annual_return: z.number().nullable(),
  annual_volatility: z.number().nullable(),
  sharpe_ratio: z.number().nullable(),
  max_drawdown: z.number().nullable(),
  var_95: z.number().nullable(),
  var_99: z.number().nullable(),
  cvar_95: z.number().nullable(),
  risk_free_rate: z.number().nullable(),
  betas: z.record(z.string(), z.number()),
  factor_betas: z.array(factorBetaRowSchema),
  component_var_pct: z.array(componentVarRowSchema),
  stress_loss: z.number().nullable(),
  stress_market_shock: z.number().nullable(),
  stress_asset_losses: z.array(stressAssetLossSchema),
  macro_betas: z.record(z.string(), z.number()),
  liquidity: z.array(liquidityRowSchema),
  drawdown_stats: z.record(z.string(), z.unknown()).nullable(),
});
export type RiskReport = z.infer<typeof riskReportSchema>;

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
        schema: riskReportSchema,
      }),
  });
}

// ── quant lab: backtest ──────────────────────────────────────────

/** A single point on the equity / drawdown time series. */
export const backtestPointSchema = z.looseObject({
  date: z.string(),
  value: z.number(),
});
export type BacktestPoint = z.infer<typeof backtestPointSchema>;

/**
 * Backtest summary stats. Every metric is independently nullable —
 * the backend returns null when a series is too short to compute
 * (e.g. alpha/beta need a benchmark overlap) so the UI must tolerate
 * any subset being present.
 */
export const backtestStatsSchema = z.looseObject({
  total_return: z.number().nullable(),
  annual_return: z.number().nullable(),
  annual_volatility: z.number().nullable(),
  sharpe_ratio: z.number().nullable(),
  sortino_ratio: z.number().nullable(),
  calmar_ratio: z.number().nullable(),
  max_drawdown: z.number().nullable(),
  win_rate: z.number().nullable(),
  alpha: z.number().nullable(),
  beta: z.number().nullable(),
});
export type BacktestStats = z.infer<typeof backtestStatsSchema>;

export const backtestResponseSchema = z.looseObject({
  strategy: z.string(),
  start_date: z.string(),
  end_date: z.string(),
  benchmark: z.string(),
  stats: backtestStatsSchema,
  equity_curve: z.array(backtestPointSchema),
  drawdown_series: z.array(backtestPointSchema),
  benchmark_total_return: z.number().nullable(),
});
export type BacktestResponse = z.infer<typeof backtestResponseSchema>;

export type BacktestRequest = {
  strategy: "static" | "equal_weight" | "momentum";
  years?: number;
  rebalance_freq?: "D" | "W" | "M" | "Q";
  benchmark?: string;
  lookback?: number;
  top_n?: number;
};

/**
 * Run a historical backtest of the user's active portfolio. The
 * backend pulls real prices and replays the chosen strategy — a
 * multi-second, network-bound call, so the page masks it with a
 * chart-shaped skeleton.
 *
 * Mutation rather than query: the user explicitly clicks "Run
 * backtest", and we want each click to fire fresh rather than be
 * served from a cache key.
 */
export function useRunBacktest() {
  const { accessToken } = useAuth();
  return useMutation<BacktestResponse, Error, BacktestRequest>({
    mutationFn: (body) =>
      apiFetch<BacktestResponse>("/api/v1/quant/backtest", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
        schema: backtestResponseSchema,
      }),
  });
}

// ── copilot chat ─────────────────────────────────────────────────

export const copilotResponseSchema = z.looseObject({
  agent_name: z.string(),
  response_markdown: z.string(),
  draft_trades: z.array(z.looseObject({})),
  tool_trace: z.array(z.string()),
  grounded_in: z.record(z.string(), z.unknown()),
});
export type CopilotResponse = z.infer<typeof copilotResponseSchema>;

/**
 * Send one message to the AI Portfolio Copilot. The backend resolves
 * the user's active portfolio, runs the typed agent, and returns
 * plain-language guidance plus the grounded numbers behind it.
 *
 * Mutation rather than query: each send is an explicit user action and
 * we want every message to fire fresh, not be served from a cache key.
 */
export function useCopilotChat() {
  const { accessToken } = useAuth();
  return useMutation<CopilotResponse, Error, { message: string }>({
    mutationFn: (body) =>
      apiFetch<CopilotResponse>("/api/v1/copilot/chat", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
        schema: copilotResponseSchema,
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
        schema: scoreResponseSchema,
      }),
  });
}
