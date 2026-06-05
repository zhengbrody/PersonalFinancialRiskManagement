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

// ── market regime detail (bull/bear/transition "season") ──────────

export const regimeDetailSchema = z.looseObject({
  current_regime: z.string().nullable(),
  confidence: z.number().nullable(),
  regime_since_date: z.string().nullable(),
  vix_regime: z.string().nullable(),
  trend_regime: z.string().nullable(),
  vol_regime: z.string().nullable(),
  history: z.array(z.looseObject({ date: z.string(), regime: z.string() })),
});
export type RegimeDetail = z.infer<typeof regimeDetailSchema>;

/**
 * Market-wide regime (bull / bear / transition) + ~1y history. Public,
 * server-cached. Powers the "Market season" panel on /markets.
 */
export function useRegimeDetail() {
  return useQuery<RegimeDetail>({
    queryKey: ["macro", "regime_detail"],
    queryFn: () =>
      apiFetch<RegimeDetail>("/api/v1/macro/regime_detail", {
        schema: regimeDetailSchema,
      }),
    staleTime: 5 * 60 * 1000,
  });
}

/** Invalidate the portfolios list so the next render refetches. */
function invalidatePortfoliosKey(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["portfolios"] });
  // Holdings changed → every risk-derived cache (score, snapshots, benchmarks
  // context) is now stale; drop them so the next view recomputes fresh.
  qc.invalidateQueries({ queryKey: ["risk"] });
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
  monthly_credits: z.number().optional(),
});
export type PlanCard = z.infer<typeof planCardSchema>;

export const creditStatusSchema = z.looseObject({
  plan: z.string(),
  label: z.string().optional(),
  unlimited: z.boolean(),
  credits_total: z.number().nullable(),
  credits_used: z.number(),
  credits_remaining: z.number().nullable(),
  budget_usd: z.number().nullable(),
  used_usd: z.number(),
});
export type CreditStatus = z.infer<typeof creditStatusSchema>;

export const billingMeSchema = z.looseObject({
  user_id: z.string(),
  email: z.string().nullable(),
  plan: z.string(),
  subscription: subscriptionRowSchema.nullable(),
  plans: z.array(planCardSchema),
  credits: creditStatusSchema.nullable().optional(),
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

// ── owner usage/cost dashboard ───────────────────────────────────
const usageAggSchema = z.looseObject({
  events: z.number().optional(),
  tokens_in: z.number().optional(),
  tokens_out: z.number().optional(),
  cost_usd: z.number().optional(),
  credits: z.number().optional(),
});
const usageUserSchema = z.looseObject({
  user_id: z.string(),
  events: z.number().optional(),
  tokens_in: z.number().optional(),
  tokens_out: z.number().optional(),
  cost_usd: z.number().optional(),
  credits: z.number().optional(),
});
export const adminUsageSchema = z.looseObject({
  since: z.string().nullable(),
  totals: usageAggSchema,
  by_kind: z.record(z.string(), usageAggSchema),
  users: z.array(usageUserSchema),
});
export type AdminUsage = z.infer<typeof adminUsageSchema>;

/** Owner-only month-to-date token/cost/credit aggregates. */
export function useAdminUsage(enabled: boolean) {
  const { accessToken } = useAuth();
  return useQuery<AdminUsage>({
    queryKey: ["billing", "admin", "usage"],
    enabled: enabled && Boolean(accessToken),
    queryFn: () =>
      apiFetch<AdminUsage>("/api/v1/billing/admin/usage", {
        authToken: accessToken!,
        schema: adminUsageSchema,
      }),
    staleTime: 30 * 1000,
    retry: false,
  });
}

// ── owner: integration system status ────────────────────────────────
const integrationStatusSchema = z.looseObject({
  name: z.string(),
  state: z.string(),
  detail: z.string(),
  configured: z.boolean(),
});
export const adminStatusSchema = z.looseObject({
  live: z.boolean(),
  integrations: z.array(integrationStatusSchema),
});
export type AdminStatus = z.infer<typeof adminStatusSchema>;
export type IntegrationStatus = z.infer<typeof integrationStatusSchema>;

/** Owner-only integration diagnostics. `live` toggles the slower
 * key-validation calls (separate query key → toggling refetches). */
export function useAdminStatus(enabled: boolean, live: boolean) {
  const { accessToken } = useAuth();
  return useQuery<AdminStatus>({
    queryKey: ["billing", "admin", "status", live],
    enabled: enabled && Boolean(accessToken),
    queryFn: () =>
      apiFetch<AdminStatus>(
        `/api/v1/billing/admin/status${live ? "?live=true" : ""}`,
        { authToken: accessToken!, schema: adminStatusSchema },
      ),
    staleTime: 60 * 1000,
    retry: false,
  });
}

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

// Copilot chat now streams over SSE (see CopilotConversation, which reads
// /api/v1/copilot/chat/stream directly); the old non-streaming useCopilotChat
// hook + copilotResponseSchema were removed when the streaming path landed.

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

/**
 * Cached auto-score of the active portfolio. A QUERY (not a mutation) so the
 * result is shared + cached across the dashboard and /score: navigating
 * between them — or returning within `staleTime` — shows the score instantly
 * instead of re-running the (multi-second) compute and flashing a skeleton
 * every time. Invalidated when holdings change (see invalidatePortfoliosKey).
 */
export function useActiveScore() {
  const { accessToken, user } = useAuth();
  return useQuery<ScoreResponse>({
    queryKey: ["risk", "score_active", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<ScoreResponse>("/api/v1/risk/score_from_active", {
        method: "POST",
        body: {},
        authToken: accessToken!,
        schema: scoreResponseSchema,
      }),
    staleTime: 10 * 60 * 1000, // prices are 24h-cached server-side; 10 min is safe
    gcTime: 30 * 60 * 1000,
    retry: false,
  });
}

// ── ticker research (single-name equity) ────────────────────────────
// Two-stage: useTickerDossier (fast, authed, no quota) paints the data
// dashboard; useTickerVerdict (authed + quota) fills the AI verdict. The
// verdict REUSES the dossier the dashboard already fetched, so /analyze
// doesn't re-hit the network.

const fnum = z.number().nullish();
const fstr = z.string().nullish();

export const equityDossierSchema = z.looseObject({
  ticker: z.string(),
  as_of: z.string().optional(),
  profile: z.looseObject({
    name: fstr,
    sector: fstr,
    industry: fstr,
    description: fstr,
    employees: fnum,
    website: fstr,
  }),
  market: z.looseObject({
    current_price: fnum,
    market_cap: fnum,
    beta: fnum,
    implied_volatility: fnum,
    shares_outstanding: fnum,
  }),
  fundamentals: z.looseObject({
    pe_ttm: fnum,
    pe_forward: fnum,
    ps_ttm: fnum,
    pb: fnum,
    ev_ebitda: fnum,
    roe: fnum,
    roa: fnum,
    gross_margin: fnum,
    operating_margin: fnum,
    net_margin: fnum,
    eps_ttm: fnum,
    dividend_yield: fnum,
    revenue_growth_yoy: fnum,
    earnings_growth_yoy: fnum,
    debt_to_equity: fnum,
    current_ratio: fnum,
    free_cash_flow: fnum,
    fcf_yield: fnum,
  }),
  valuation: z.looseObject({
    dcf_intrinsic_value: fnum,
    dcf_upside_pct: fnum,
    wacc: fnum,
    terminal_growth: fnum,
  }),
  technicals: z.looseObject({
    rsi_14: fnum,
    sma_50: fnum,
    sma_200: fnum,
    fifty_two_week_high: fnum,
    fifty_two_week_low: fnum,
    max_drawdown_1y: fnum,
  }),
  ratings: z
    .looseObject({
      analyst_rating: fstr,
      analyst_count: fnum,
      price_targets: z
        .looseObject({ low: fnum, mean: fnum, high: fnum, current: fnum })
        .optional(),
    })
    .optional(),
  ownership: z.looseObject({ institutional_pct: fnum }).optional(),
  earnings_quarterly: z
    .array(
      z.looseObject({
        period: z.string(),
        revenue: fnum,
        net_income: fnum,
        eps: fnum,
      }),
    )
    .optional(),
});
export type EquityDossier = z.infer<typeof equityDossierSchema>;

const dimensionSchema = z.looseObject({
  score_0_100: z.number(),
  key_points: z.array(z.string()),
  evidence: z.array(z.string()),
});
export const deepAnalysisSchema = z.looseObject({
  ticker: z.string(),
  as_of: z.string().optional(),
  verdict: z.looseObject({
    rating: z.string(),
    confidence: z.string(),
    target_weight_pct_band: z.string().optional(),
    thesis_one_liner: z.string().optional(),
  }),
  dimensions: z.record(z.string(), dimensionSchema),
  catalysts_90d: z.array(z.string()),
  risks: z.array(z.string()),
  data_gaps: z.array(z.string()),
  would_change_mind: z.array(z.string()),
});
export type DeepAnalysis = z.infer<typeof deepAnalysisSchema>;

export const dossierResponseSchema = z.looseObject({
  dossier: equityDossierSchema,
});
export type DossierResponse = z.infer<typeof dossierResponseSchema>;

export const analyzeResponseSchema = z.looseObject({
  analysis: deepAnalysisSchema,
  dossier: equityDossierSchema,
});
export type AnalyzeResponse = z.infer<typeof analyzeResponseSchema>;

/** Fetch the deterministic dossier for a ticker (fast, no quota). */
export function useTickerDossier() {
  const { accessToken } = useAuth();
  return useMutation<DossierResponse, Error, { ticker: string }>({
    mutationFn: (body) =>
      apiFetch<DossierResponse>("/api/v1/equity/dossier", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
        schema: dossierResponseSchema,
      }),
  });
}

/** Run the AI analyst verdict over an already-fetched dossier (quota). */
export function useTickerVerdict() {
  const { accessToken } = useAuth();
  return useMutation<AnalyzeResponse, Error, { dossier: EquityDossier }>({
    mutationFn: (body) =>
      apiFetch<AnalyzeResponse>("/api/v1/equity/analyze", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
        schema: analyzeResponseSchema,
      }),
  });
}

// ── scenario simulator + efficient frontier ─────────────────────────
const frontierPointSchema = z.looseObject({ vol: z.number(), ret: z.number() });
export const efficientFrontierSchema = z.looseObject({
  frontier: z.array(frontierPointSchema),
  current: frontierPointSchema,
  risk_free_rate: z.number(),
});
export type EfficientFrontier = z.infer<typeof efficientFrontierSchema>;

const scenarioPointSchema = z.looseObject({
  shock_pct: z.number(),
  pnl_pct: z.number(),
  portfolio_value: z.number(),
  // Per-holding signed return under this shock, most-impacted first (optional —
  // older backends omit it). Drives the Scenario Explorer's "top impacted".
  asset_losses: z.array(stressAssetLossSchema).default([]),
});
export const scenariosSchema = z.looseObject({
  total_value: z.number(),
  scenarios: z.array(scenarioPointSchema),
});
export type Scenarios = z.infer<typeof scenariosSchema>;

/** Efficient frontier + the active portfolio's risk/return point. */
export function useEfficientFrontier() {
  const { accessToken } = useAuth();
  return useMutation<EfficientFrontier, Error, void>({
    mutationFn: () =>
      apiFetch<EfficientFrontier>("/api/v1/risk/efficient_frontier", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: efficientFrontierSchema,
      }),
  });
}

/** −30%…+30% market-move P&L sweep for the active portfolio. */
export function useScenarios() {
  const { accessToken } = useAuth();
  return useMutation<Scenarios, Error, void>({
    mutationFn: () =>
      apiFetch<Scenarios>("/api/v1/risk/scenarios", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: scenariosSchema,
      }),
  });
}

// ── "what changed since last visit" (prior-day snapshot) ────────────
const snapshotMetricsSchema = z.looseObject({
  as_of: z.string().nullish(),
  overall_score: z.number().nullish(),
  annual_volatility: z.number().nullish(),
  var_95_daily: z.number().nullish(),
  sharpe_ratio: z.number().nullish(),
  max_drawdown: z.number().nullish(),
  net_equity: z.number().nullish(),
});
export const lastSnapshotSchema = z.looseObject({
  snapshot: snapshotMetricsSchema.nullable(),
});
export type LastSnapshot = z.infer<typeof lastSnapshotSchema>;

/** The prior-day portfolio snapshot (or {snapshot:null}) for the dashboard
 * "what changed since your last visit" delta. */
export function useLastSnapshot() {
  const { accessToken, user } = useAuth();
  return useQuery<LastSnapshot>({
    queryKey: ["risk", "last_snapshot", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<LastSnapshot>("/api/v1/risk/last_snapshot", {
        authToken: accessToken!,
        schema: lastSnapshotSchema,
      }),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

// ── AI risk diagnosis (structured, deterministic-first) ─────────────
// The page passes back the numbers it ALREADY fetched (score / report); the
// backend turns them into a plain-English diagnosis. severity + primary_driver
// are computed deterministically server-side and never invented by the LLM;
// the whole thing degrades to a deterministic template if the LLM is
// unavailable. Free (not credit-gated). Cached per-input so tab switches and
// re-views don't re-call.

export type ExplainDimensionInput = {
  name: string;
  score?: number | null;
  status?: string;
};

export type RiskExplainInput = {
  source: "score" | "risk";
  overall_score?: number | null;
  dimensions?: Record<string, ExplainDimensionInput>;
  metrics?: {
    annual_return?: number | null;
    annual_volatility?: number | null;
    sharpe_ratio?: number | null;
    max_drawdown?: number | null;
    var_95_daily?: number | null;
    cvar_95_daily?: number | null;
    beta_to_benchmark?: number | null;
    total_value?: number | null;
    cash_weight?: number | null;
  };
  top_component_var?: { ticker: string; pct: number }[];
  factor_betas?: Record<string, number>;
  stress_loss?: number | null;
  stress_market_shock?: number | null;
  liquidity_outliers?: { ticker: string; days_to_liquidate?: number | null }[];
  snapshot_delta?: {
    as_of?: string | null;
    prev_overall_score?: number | null;
    prev_annual_volatility?: number | null;
    prev_sharpe_ratio?: number | null;
  } | null;
};

export const suggestedActionSchema = z.looseObject({
  reason: z.string(),
  evidence: z.string(),
  next_step: z.string(),
  disclaimer: z.string().default("Educational, not financial advice."),
});
export type SuggestedAction = z.infer<typeof suggestedActionSchema>;

export const riskExplainSchema = z.looseObject({
  severity: z.enum(["low", "moderate", "elevated", "high"]),
  headline: z.string(),
  summary_bullets: z.array(z.string()),
  primary_driver: z.string(),
  watch_items: z.array(z.string()),
  suggested_actions: z.array(suggestedActionSchema),
  caveats: z.array(z.string()),
  ai_generated: z.boolean(),
});
export type RiskExplain = z.infer<typeof riskExplainSchema>;
export type Severity = RiskExplain["severity"];

/**
 * AI risk diagnosis over already-computed numbers. A query (not a mutation) so
 * it's cached + deduped per-input: switching tabs or revisiting the page reuses
 * the result instead of re-calling. `enabled` only once `input` is built, so
 * the deterministic metrics paint first and this fills in second.
 */
export function useRiskExplain(input: RiskExplainInput | null) {
  const { accessToken, user } = useAuth();
  return useQuery<RiskExplain>({
    queryKey: ["risk", "explain", user?.id ?? null, input ? JSON.stringify(input) : null],
    enabled: Boolean(accessToken && input),
    queryFn: () =>
      apiFetch<RiskExplain>("/api/v1/risk/explain", {
        method: "POST",
        body: input!,
        authToken: accessToken!,
        schema: riskExplainSchema,
      }),
    staleTime: 30 * 60 * 1000,
    retry: false,
  });
}

// ── institutions: SEC 13F smart money ───────────────────────────────
export const smartMoneySignalSchema = z.looseObject({
  ticker: z.string(),
  num_institutions: z.number(),
  crowding_score: z.number(),
  top_holders: z.array(z.string()),
  signal: z.string(),
});
export type SmartMoneySignal = z.infer<typeof smartMoneySignalSchema>;
export const smartMoneySchema = z.looseObject({
  signals: z.array(smartMoneySignalSchema),
});

const institutionRowSchema = z.looseObject({ name: z.string(), cik: z.string() });
export const topInstitutionsSchema = z.looseObject({
  institutions: z.array(institutionRowSchema),
});
export type InstitutionRow = z.infer<typeof institutionRowSchema>;

const instHoldingSchema = z.looseObject({
  ticker: z.string(),
  name: z.string(),
  shares: z.number().nullable(),
  value: z.number().nullable(),
  pct_of_portfolio: z.number().nullable(),
});
const instChangeRowSchema = z.looseObject({
  ticker: z.string(),
  name: z.string(),
  shares: z.number().nullish(),
  value: z.number().nullish(),
  prev_shares: z.number().nullish(),
  change_pct: z.number().nullish(),
});
const institutionChangesSchema = z.looseObject({
  latest_filing_date: z.string().nullish(),
  previous_filing_date: z.string().nullish(),
  new_positions: z.array(instChangeRowSchema),
  increased: z.array(instChangeRowSchema),
  decreased: z.array(instChangeRowSchema),
  exited: z.array(instChangeRowSchema),
  summary: z.record(z.string(), z.unknown()),
});
export const institutionDetailSchema = z.looseObject({
  cik: z.string(),
  name: z.string().nullable(),
  holdings: z.array(instHoldingSchema),
  changes: institutionChangesSchema,
});
export type InstitutionDetail = z.infer<typeof institutionDetailSchema>;
export type InstitutionChanges = z.infer<typeof institutionChangesSchema>;
export type InstChangeRow = z.infer<typeof instChangeRowSchema>;
export type InstHolding = z.infer<typeof instHoldingSchema>;

/** Institutional-conviction signals for the user's active holdings. Slow on a
 * cold SEC cache → long staleTime; fail-soft to {signals:[]} server-side. */
export function useSmartMoney() {
  const { accessToken, user } = useAuth();
  return useQuery({
    queryKey: ["institutions", "smart_money", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch("/api/v1/institutions/smart_money", {
        authToken: accessToken!,
        schema: smartMoneySchema,
      }),
    staleTime: 30 * 60 * 1000,
    retry: false,
  });
}

/** The ~30 most-watched 13F filers (for the deep-dive picker). */
export function useTopInstitutions() {
  const { accessToken } = useAuth();
  return useQuery({
    queryKey: ["institutions", "top"],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch("/api/v1/institutions/top", {
        authToken: accessToken!,
        schema: topInstitutionsSchema,
      }),
    staleTime: 60 * 60 * 1000,
    retry: false,
  });
}

/** A fund's top holdings + QoQ changes. Enabled only when a CIK is picked. */
export function useInstitution(cik: string | null) {
  const { accessToken } = useAuth();
  return useQuery<InstitutionDetail>({
    queryKey: ["institutions", "detail", cik],
    enabled: Boolean(accessToken && cik),
    queryFn: () =>
      apiFetch<InstitutionDetail>(`/api/v1/institutions/${cik}`, {
        authToken: accessToken!,
        schema: institutionDetailSchema,
      }),
    staleTime: 30 * 60 * 1000,
    retry: false,
  });
}

// ── market movers + sectors (public) ────────────────────────────────
const sectorRowSchema = z.looseObject({
  sector: z.string(),
  ticker: z.string(),
  change_pct: z.number().nullish(),
  ytd_return: z.number().nullish(),
});
const moverRowSchema = z.looseObject({
  ticker: z.string(),
  name: z.string(),
  change_pct: z.number().nullish(),
  close: z.number().nullish(),
  avg_volume_ratio: z.number().nullish(),
});
export const moversSchema = z.looseObject({
  scan_date: z.string().nullish(),
  sectors: z.array(sectorRowSchema),
  top_gainers: z.array(moverRowSchema),
  top_losers: z.array(moverRowSchema),
  unusual_volume: z.array(moverRowSchema),
});
export type Movers = z.infer<typeof moversSchema>;
export type MoverRow = z.infer<typeof moverRowSchema>;
export type SectorRow = z.infer<typeof sectorRowSchema>;

// ── benchmark reference context (public) ────────────────────────────
const benchmarkRowSchema = z.looseObject({
  name: z.string(),
  annual_return: z.number().nullish(),
  annual_volatility: z.number().nullish(),
  sharpe_ratio: z.number().nullish(),
  max_drawdown: z.number().nullish(),
});
export const benchmarksSchema = z.looseObject({
  as_of: z.string().nullish(),
  benchmarks: z.array(benchmarkRowSchema),
});
export type Benchmarks = z.infer<typeof benchmarksSchema>;
export type BenchmarkRow = z.infer<typeof benchmarkRowSchema>;

// ── snapshot history (score/vol/VaR over time) ──────────────────────
const snapshotPointSchema = z.looseObject({
  as_of: z.string().nullish(),
  overall_score: z.number().nullish(),
  annual_volatility: z.number().nullish(),
  var_95_daily: z.number().nullish(),
  sharpe_ratio: z.number().nullish(),
  max_drawdown: z.number().nullish(),
  net_equity: z.number().nullish(),
});
export const snapshotHistorySchema = z.looseObject({
  snapshots: z.array(snapshotPointSchema),
});
export type SnapshotHistory = z.infer<typeof snapshotHistorySchema>;
export type SnapshotPoint = z.infer<typeof snapshotPointSchema>;

/** Recent portfolio snapshots (oldest→newest) for trend sparklines. */
export function useSnapshotHistory() {
  const { accessToken, user } = useAuth();
  return useQuery<SnapshotHistory>({
    queryKey: ["risk", "snapshot_history", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<SnapshotHistory>("/api/v1/risk/snapshot_history", {
        authToken: accessToken!,
        schema: snapshotHistorySchema,
      }),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

// ── VaR backtest + distribution (authed) ────────────────────────────
const histogramBinSchema = z.looseObject({ x: z.number().nullish(), count: z.number() });
export const varBacktestSchema = z.looseObject({
  n_days: z.number(),
  mean_daily: z.number().nullish(),
  vol_daily: z.number().nullish(),
  var_95: z.number().nullish(),
  var_99: z.number().nullish(),
  hist_var_95: z.number().nullish(),
  hist_var_99: z.number().nullish(),
  breaches_95: z.number(),
  expected_95: z.number().nullish(),
  breaches_99: z.number(),
  expected_99: z.number().nullish(),
  worst_day: z.number().nullish(),
  histogram: z.array(histogramBinSchema),
});
export type VarBacktest = z.infer<typeof varBacktestSchema>;

/** Backtest the portfolio's 1-day VaR vs realised breaches + the empirical
 * return distribution. Mutation — fired once with the risk report. */
export function useVarBacktest() {
  const { accessToken } = useAuth();
  return useMutation<VarBacktest, Error, void>({
    mutationFn: () =>
      apiFetch<VarBacktest>("/api/v1/risk/var_backtest", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: varBacktestSchema,
      }),
  });
}

// ── historical scenario replay (authed) ─────────────────────────────
const historicalScenarioRowSchema = z.looseObject({
  label: z.string(),
  start: z.string(),
  end: z.string(),
  portfolio_return: z.number().nullish(),
  market_return: z.number().nullish(),
  max_drawdown: z.number().nullish(),
  coverage: z.number().nullish(),
  recovery_days: z.number().nullish(),
});
export const historicalScenariosSchema = z.looseObject({
  scenarios: z.array(historicalScenarioRowSchema),
});
export type HistoricalScenarios = z.infer<typeof historicalScenariosSchema>;
export type HistoricalScenarioRow = z.infer<typeof historicalScenarioRowSchema>;

/** Replay real crises (COVID / 2022 / 2018Q4 / GFC) on the active portfolio.
 * Mutation — heavier (long history fetch), fired once per user like the sweep. */
export function useHistoricalScenarios() {
  const { accessToken } = useAuth();
  return useMutation<HistoricalScenarios, Error, void>({
    mutationFn: () =>
      apiFetch<HistoricalScenarios>("/api/v1/risk/historical_scenarios", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: historicalScenariosSchema,
      }),
  });
}

// ── latest prices (public) — for the holdings-form sanity check ─────
const priceRowSchema = z.looseObject({
  ticker: z.string(),
  price: z.number(),
  as_of: z.string(),
});
export const marketPricesSchema = z.looseObject({
  prices: z.array(priceRowSchema),
  requested: z.array(z.string()),
});
export type MarketPrices = z.infer<typeof marketPricesSchema>;

/** Latest close per ticker (public). Keyed only on the ticker SET so editing
 * other fields doesn't refetch. Used to show implied market value / P&L as the
 * user types a portfolio, catching wrong cost-basis entries at the source. */
export function useMarketPrices(tickers: string[]) {
  const key = Array.from(
    new Set(tickers.map((t) => t.trim().toUpperCase()).filter(Boolean)),
  ).sort();
  return useQuery<MarketPrices>({
    queryKey: ["market", "prices", key.join(",")],
    enabled: key.length > 0,
    queryFn: () =>
      apiFetch<MarketPrices>(
        `/api/v1/market/prices?tickers=${encodeURIComponent(key.join(","))}`,
        { schema: marketPricesSchema },
      ),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

/** Public reference stats (S&P 500 + 60/40) for "vs what?" context. */
export function useBenchmarks() {
  return useQuery<Benchmarks>({
    queryKey: ["risk", "benchmarks"],
    queryFn: () => apiFetch<Benchmarks>("/api/v1/risk/benchmarks", { schema: benchmarksSchema }),
    staleTime: 6 * 60 * 60 * 1000,
  });
}

/** Public sector performance + top gainers/losers. Fail-soft server-side. */
export function useMarketMovers() {
  return useQuery<Movers>({
    queryKey: ["macro", "movers"],
    queryFn: () => apiFetch<Movers>("/api/v1/macro/movers", { schema: moversSchema }),
    staleTime: 10 * 60 * 1000,
  });
}

// ── macro news (public) + portfolio sentiment (authed, credits) ─────
const newsItemSchema = z.looseObject({
  source: z.string().nullish(),
  title: z.string(),
  link: z.string().nullish(),
  published: z.string().nullish(),
  summary: z.string().nullish(),
});
export const newsSchema = z.looseObject({ items: z.array(newsItemSchema) });
export type NewsItem = z.infer<typeof newsItemSchema>;

/** Public macro news headlines. Fail-soft to {items:[]} server-side. */
export function useMarketNews() {
  return useQuery({
    queryKey: ["macro", "news"],
    queryFn: () => apiFetch("/api/v1/macro/news", { schema: newsSchema }),
    staleTime: 15 * 60 * 1000,
  });
}

const sentimentRowSchema = z.looseObject({
  ticker: z.string(),
  score: z.number(),
  label: z.string(),
  narrative: z.string(),
  headline_count: z.number(),
});
export const sentimentSchema = z.looseObject({
  sentiments: z.array(sentimentRowSchema),
  ai_generated: z.boolean(),
});
export type Sentiment = z.infer<typeof sentimentSchema>;
export type SentimentRow = z.infer<typeof sentimentRowSchema>;

/** Per-holding AI sentiment over the active portfolio. A mutation (explicit
 * user action — it spends credits). 429 on quota; data-only without a key. */
export function usePortfolioSentiment() {
  const { accessToken } = useAuth();
  return useMutation<Sentiment, Error, void>({
    mutationFn: () =>
      apiFetch<Sentiment>("/api/v1/market/sentiment", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: sentimentSchema,
      }),
  });
}

// ── quant: performance attribution ──────────────────────────────────
const sectorEffectSchema = z.looseObject({
  sector: z.string(),
  weight_diff: z.number().nullish(),
  allocation_effect: z.number().nullish(),
  selection_effect: z.number().nullish(),
  total_effect: z.number().nullish(),
});
const brinsonSchema = z.looseObject({
  total_active_return: z.number().nullish(),
  allocation_effect: z.number().nullish(),
  selection_effect: z.number().nullish(),
  interaction_effect: z.number().nullish(),
  sector_detail: z.array(sectorEffectSchema),
});
const factorSchema = z.looseObject({
  alpha: z.number().nullish(),
  r_squared: z.number().nullish(),
  residual_return: z.number().nullish(),
  factor_betas: z.record(z.string(), z.number().nullable()),
  factor_contributions: z.record(z.string(), z.number().nullable()),
});
export const attributionSchema = z.looseObject({
  tracking_error: z.number().nullish(),
  information_ratio: z.number().nullish(),
  hit_ratio: z.number().nullish(),
  active_return_annual: z.number().nullish(),
  brinson: brinsonSchema.nullable(),
  factor: factorSchema.nullable(),
});
export type Attribution = z.infer<typeof attributionSchema>;

/** Brinson + factor attribution for the active portfolio. Mutation (heavy,
 * explicit run). Deterministic — no credits. */
export function useAttribution() {
  const { accessToken } = useAuth();
  return useMutation<Attribution, Error, void>({
    mutationFn: () =>
      apiFetch<Attribution>("/api/v1/quant/attribution", {
        method: "POST",
        body: {},
        authToken: accessToken ?? undefined,
        schema: attributionSchema,
      }),
  });
}
