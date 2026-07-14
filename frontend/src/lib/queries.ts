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
  concentrationSchema,
  dataConfidenceSchema,
  priceProvenanceSchema,
  scoreResponseSchema,
  sourceProvenanceSchema,
  type Concentration,
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
    z.looseObject({
      shares: z.number(),
      avg_cost: z.number().optional(),
      asset_type: z.string().optional(),
      // option-contract fields (present only when asset_type === "option")
      option_type: z.enum(["call", "put"]).optional(),
      option_side: z.enum(["long", "short"]).optional(),
      underlying: z.string().optional(),
      strike: z.number().optional(),
      expiry: z.string().optional(),
      contract_multiplier: z.number().optional(),
    }),
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
  source: z.string().optional(),
  cache_ttl_seconds: z.number().optional(),
  refresh_policy: z.string().optional(),
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
  source: z.string().optional(),
  cache_ttl_seconds: z.number().optional(),
  refresh_policy: z.string().optional(),
});
export type YieldCurve = z.infer<typeof yieldCurveSchema>;

// ── hooks ─────────────────────────────────────────────────────────

// ── portfolio CRUD payload types ──────────────────────────────────

export type PortfolioHoldingInput = {
  shares: number;
  avg_cost?: number;
  sector?: string;
  asset_type?: string;
  // Option-contract fields (present only when asset_type === "option").
  // The holding is keyed in `holdings` by a synthetic OCC-style contract
  // symbol; `shares` = number of contracts (positive magnitude),
  // `avg_cost` = premium per share. `option_side` distinguishes a bought
  // (long) leg from a sold/written (short) leg.
  option_type?: "call" | "put";
  option_side?: "long" | "short";
  underlying?: string;
  strike?: number;
  expiry?: string; // ISO date "YYYY-MM-DD"
  contract_multiplier?: number;
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

// ── ML regime classifier (trained risk-state model; CONTEXT only) ─────

export const mlRegimeSchema = z.looseObject({
  // 4-class risk STATE: risk_on | neutral | volatile | stress.
  regime: z.string().nullable(),
  confidence: z.number().nullable(),
  class_probabilities: z.record(z.string(), z.number()),
  top_drivers: z.array(
    z.looseObject({
      feature: z.string(),
      label: z.string(),
      value: z.number(),
      vs_normal: z.string(),
      importance: z.number().nullish(),
    }),
  ),
  model_version: z.string().nullish(),
  trained_at: z.string().nullish(),
  training_window: z.looseObject({}).nullish(),
  source: z.string(), // model | heuristic_fallback | unavailable
  last_updated: z.string().nullish(),
  data_coverage: z.looseObject({}),
  current_realized_vol: z.number().nullish(),
  note: z.string().nullish(),
});
export type MlRegime = z.infer<typeof mlRegimeSchema>;

/**
 * The TRAINED market risk-state model (backend/app/ml). Public, server-cached
 * ~10 min, fail-soft. Market CONTEXT only — never advice, never part of the
 * deterministic Health Score.
 */
export function useMlRegime() {
  return useQuery<MlRegime>({
    queryKey: ["ml", "regime"],
    queryFn: () =>
      apiFetch<MlRegime>("/api/v1/ml/regime", {
        schema: mlRegimeSchema,
      }),
    staleTime: 10 * 60 * 1000,
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

// ── account ──────────────────────────────────────────────────────

export const accountDeleteSchema = z.looseObject({
  deleted: z.boolean(),
  subscription_canceled: z.boolean(),
});

/** DELETE /api/v1/account — deletes the CALLER's account (id from the JWT).
 *  Requires the exact confirmation phrase; the server fails closed if a live
 *  Stripe subscription cannot be canceled first. */
export function useDeleteAccount() {
  const { accessToken } = useAuth();
  return useMutation<z.infer<typeof accountDeleteSchema>, Error, string>({
    mutationFn: (confirmation) =>
      apiFetch("/api/v1/account", {
        method: "DELETE",
        body: { confirmation },
        authToken: accessToken ?? undefined,
        schema: accountDeleteSchema,
      }),
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
  by_model: z.record(z.string(), usageAggSchema).optional(),
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

// ── owner: live in-process API metrics ──────────────────────────────
const metricRouteSchema = z.looseObject({
  method: z.string(),
  route: z.string(),
  count: z.number(),
  errors: z.number().optional(),
  status_2xx: z.number().optional(),
  status_4xx: z.number().optional(),
  status_5xx: z.number().optional(),
  avg_ms: z.number().optional(),
});
const metricProviderSchema = z.looseObject({
  name: z.string(),
  calls: z.number(),
  ok: z.number().optional(),
  cache_hit: z.number().optional(),
  empty: z.number().optional(),
  error: z.number().optional(),
  rate_limited: z.number().optional(),
  no_key: z.number().optional(),
});
export const adminMetricsSchema = z.looseObject({
  uptime_s: z.number(),
  total_requests: z.number(),
  total_errors: z.number(),
  routes: z.array(metricRouteSchema),
  providers: z.array(metricProviderSchema),
});
export type AdminMetrics = z.infer<typeof adminMetricsSchema>;
export type MetricRoute = z.infer<typeof metricRouteSchema>;
export type MetricProvider = z.infer<typeof metricProviderSchema>;

/** Owner-only LIVE in-process API activity. In-memory on the server (no DB
 * hit), so it's safe to poll every few seconds — the dashboard diffs
 * consecutive snapshots to show live rates. */
export function useAdminMetrics(enabled: boolean) {
  const { accessToken } = useAuth();
  return useQuery<AdminMetrics>({
    queryKey: ["billing", "admin", "metrics"],
    enabled: enabled && Boolean(accessToken),
    queryFn: () =>
      apiFetch<AdminMetrics>("/api/v1/billing/admin/metrics", {
        authToken: accessToken!,
        schema: adminMetricsSchema,
      }),
    refetchInterval: 4000,
    refetchIntervalInBackground: false,
    staleTime: 0,
    retry: false,
  });
}

// ── owner: LLM provider remaining balance / top-up ──────────────────
const balanceProviderSchema = z.looseObject({
  provider: z.string(),
  configured: z.boolean(),
  source: z.string(), // "live" (DeepSeek) | "estimate" (Claude)
  status: z.string(), // ok | warn | critical | unknown
  low: z.boolean().optional(),
  currency: z.string().optional(),
  remaining: z.number().nullish(),
  topped_up: z.number().nullish(),
  spent: z.number().nullish(),
  pct: z.number().nullish(),
  granted: z.number().nullish(),
  is_available: z.boolean().optional(),
  since: z.string().nullish(),
  error: z.string().optional(),
});
export const adminBalancesSchema = z.looseObject({
  deepseek: balanceProviderSchema,
  anthropic: balanceProviderSchema,
});
export type AdminBalances = z.infer<typeof adminBalancesSchema>;
export type BalanceProvider = z.infer<typeof balanceProviderSchema>;

/** Owner-only LLM provider balances (DeepSeek live + Claude estimate). Server-
 * cached 60s; poll slowly — balances don't move second-to-second. */
export function useAdminBalances(enabled: boolean) {
  const { accessToken } = useAuth();
  return useQuery<AdminBalances>({
    queryKey: ["billing", "admin", "balances"],
    enabled: enabled && Boolean(accessToken),
    queryFn: () =>
      apiFetch<AdminBalances>("/api/v1/billing/admin/balances", {
        authToken: accessToken!,
        schema: adminBalancesSchema,
      }),
    refetchInterval: 45_000,
    refetchIntervalInBackground: false,
    retry: false,
  });
}

// ── weekly digest preference (settings toggle) ──────────────────────

export const digestPrefSchema = z.looseObject({ enabled: z.boolean() });
export type DigestPref = z.infer<typeof digestPrefSchema>;

export function useDigestPref() {
  const { accessToken } = useAuth();
  return useQuery<DigestPref>({
    queryKey: ["digest", "pref"],
    queryFn: () =>
      apiFetch<DigestPref>("/api/v1/digest/pref", { authToken: accessToken ?? undefined, schema: digestPrefSchema }),
    enabled: Boolean(accessToken),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSetDigestPref() {
  const { accessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<DigestPref, Error, boolean>({
    mutationFn: (enabled) =>
      apiFetch<DigestPref>("/api/v1/digest/pref", {
        method: "POST",
        body: { enabled },
        authToken: accessToken ?? undefined,
        schema: digestPrefSchema,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["digest", "pref"] }),
  });
}

/** Owner sets the current Claude balance from the dashboard (after a top-up) —
 * no env edit / restart. Returns the refreshed balances + invalidates the card. */
export function useSetAnthropicTopup() {
  const { accessToken } = useAuth();
  const qc = useQueryClient();
  return useMutation<AdminBalances, Error, number>({
    mutationFn: (balance) =>
      apiFetch<AdminBalances>("/api/v1/billing/admin/anthropic-topup", {
        method: "POST",
        body: { balance },
        authToken: accessToken!,
        schema: adminBalancesSchema,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["billing", "admin", "balances"] }),
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

export const componentReturnRowSchema = z.looseObject({
  ticker: z.string(),
  contribution: z.number(),
});
export type ComponentReturnRow = z.infer<typeof componentReturnRowSchema>;

export const liquidityRowSchema = z.looseObject({
  ticker: z.string(),
  days_to_liquidate: z.number().nullable(),
  adv_30d: z.number().nullable(),
  market_value: z.number().nullable(),
});
export type LiquidityRow = z.infer<typeof liquidityRowSchema>;

// concentrationSchema + Concentration now live in ./schemas (shared with the
// score response); re-exported here for existing importers of the report API.
export { concentrationSchema, type Concentration };

// Desk analytics (Risk Desk round) — additive, nullable end-to-end.
const corrTopPairSchema = z.looseObject({ a: z.string(), b: z.string(), rho: z.number() });
const bestDiversifierSchema = z.looseObject({ ticker: z.string(), avg_rho: z.number() });
export const correlationSchema = z.looseObject({
  tickers: z.array(z.string()),
  matrix: z.array(z.array(z.number().nullable())),
  avg_pairwise: z.number().nullable().optional(),
  top_pair: corrTopPairSchema.nullish(),
  best_diversifier: bestDiversifierSchema.nullish(),
  diversification_ratio: z.number().nullable().optional(),
  truncated: z.boolean().optional().default(false),
  total_tickers: z.number().optional().default(0),
});
export type Correlation = z.infer<typeof correlationSchema>;

export const rollingVolPointSchema = z.looseObject({
  date: z.string(),
  portfolio: z.number(),
  benchmark: z.number().nullable().optional(),
});
export const rollingVolatilitySchema = z.looseObject({
  window_days: z.number().optional().default(21),
  series: z.array(rollingVolPointSchema).optional().default([]),
  current: z.number().nullable().optional(),
  median: z.number().nullable().optional(),
  state: z.enum(["calm", "normal", "elevated"]).optional().default("normal"),
  benchmark_ticker: z.string().nullable().optional(),
});
export type RollingVolatility = z.infer<typeof rollingVolatilitySchema>;

// ── Explainable cockpit: per-dimension model + %/$ losses (PR A) ──
export const riskDimensionSchema = z.looseObject({
  key: z.string(),
  name: z.string(),
  value: z.number().nullable().optional(),
  display: z.string().nullable().optional(),
  unit: z.string().nullable().optional(),
  status: z.enum(["calm", "normal", "elevated", "high", "n/a"]).optional().default("n/a"),
  percentile: z.number().nullable().optional(),
  percentile_n: z.number().nullable().optional(),
  contribution: z.number().nullable().optional(),
  confidence: z.string().nullable().optional(),
  explanation: z.string().optional().default(""),
  action: z.string().nullable().optional(),
  measurable: z.boolean().optional().default(true),
});
export type RiskDimension = z.infer<typeof riskDimensionSchema>;

export const lossFigureSchema = z.looseObject({
  label: z.string().optional().default(""),
  horizon: z.string().nullable().optional(),
  pct: z.number().nullable().optional(),
  usd: z.number().nullable().optional(),
});
export type LossFigure = z.infer<typeof lossFigureSchema>;

export const marginBufferSchema = z.looseObject({
  net_equity: z.number().nullable().optional(),
  margin_loan: z.number().nullable().optional(),
  gross_assets: z.number().nullable().optional(),
  maintenance_requirement: z.number().nullable().optional(),
  buffer_usd: z.number().nullable().optional(),
  buffer_pct: z.number().nullable().optional(),
  status: z
    .enum(["none", "comfortable", "tight", "call_risk", "n/a"])
    .optional()
    .default("n/a"),
});
export const lossBreakdownSchema = z.looseObject({
  basis_value: z.number().nullable().optional(),
  var_1d_95: lossFigureSchema.nullish(),
  cvar_1d_95: lossFigureSchema.nullish(),
  var_21d_95: lossFigureSchema.nullish(),
  stress: lossFigureSchema.nullish(),
  current_drawdown: lossFigureSchema.nullish(),
  margin_buffer: marginBufferSchema.nullish(),
});
export type LossBreakdown = z.infer<typeof lossBreakdownSchema>;

export const riskReportSchema = z.looseObject({
  annual_return: z.number().nullable(),
  annual_volatility: z.number().nullable(),
  sharpe_ratio: z.number().nullable(),
  max_drawdown: z.number().nullable(),
  var_95: z.number().nullable(),
  var_99: z.number().nullable(),
  cvar_95: z.number().nullable(),
  risk_free_rate: z.number().nullable(),
  total_value: z.number().nullable().optional(),
  net_equity: z.number().nullable().optional(),
  cash_balance: z.number().nullable().optional(),
  margin_loan: z.number().nullable().optional(),
  contributed_capital: z.number().nullable().optional(),
  daily_pnl: z.number().nullable().optional(),
  daily_return: z.number().nullable().optional(),
  total_pnl: z.number().nullable().optional(),
  total_return: z.number().nullable().optional(),
  betas: z.record(z.string(), z.number()),
  factor_betas: z.array(factorBetaRowSchema),
  component_var_pct: z.array(componentVarRowSchema),
  component_return: z.array(componentReturnRowSchema).optional().default([]),
  stress_loss: z.number().nullable(),
  stress_market_shock: z.number().nullable(),
  stress_asset_losses: z.array(stressAssetLossSchema),
  macro_betas: z.record(z.string(), z.number()),
  liquidity: z.array(liquidityRowSchema),
  drawdown_stats: z.record(z.string(), z.unknown()).nullable(),
  price_provenance: priceProvenanceSchema.nullish(),
  data_quality_notes: z.array(z.string()).optional().default([]),
  concentration: concentrationSchema.nullish(),
  correlation: correlationSchema.nullish(),
  rolling_volatility: rollingVolatilitySchema.nullish(),
  data_confidence: dataConfidenceSchema.nullish(),
  dimensions: z.array(riskDimensionSchema).optional().default([]),
  losses: lossBreakdownSchema.nullish(),
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

// ── options analytics (Greeks / IV / payoff) ──────────────────────────
// Deterministic, credit-free. The page derives the contracts from the active
// portfolio's option holdings and posts them; the backend prices them off free
// yfinance chains. Fail-soft per contract (each carries its own `warnings`).

const greeksSchema = z.looseObject({
  delta: z.number(),
  gamma: z.number(),
  theta: z.number(),
  vega: z.number(),
  rho: z.number(),
});

const payoffPointSchema = z.looseObject({ price: z.number(), pnl: z.number() });

export const optionAnalyticsSchema = z.looseObject({
  contract_symbol: z.string().nullish(),
  underlying: z.string(),
  option_type: z.string(),
  strike: z.number(),
  expiry: z.string(),
  quantity: z.number(),
  contract_multiplier: z.number(),
  days_to_expiry: z.number(),
  spot: z.number().nullish(),
  mark: z.number().nullish(),
  iv: z.number().nullish(),
  greeks: greeksSchema.nullish(),
  delta_notional: z.number().nullish(),
  market_value: z.number().nullish(),
  cost_basis: z.number().nullish(),
  unrealized_pnl: z.number().nullish(),
  intrinsic_value: z.number().nullish(),
  time_value: z.number().nullish(),
  max_loss: z.number().nullish(), // null = unbounded
  max_gain: z.number().nullish(), // null = unbounded
  assignment_risk: z.string().nullish(), // null | "watch" | "high"
  break_even: z.number().nullish(),
  moneyness: z.string().nullish(),
  payoff: z.array(payoffPointSchema),
  source: z.string(), // "market" | "theoretical_fallback"
  warnings: z.array(z.string()),
});
export type OptionAnalytics = z.infer<typeof optionAnalyticsSchema>;

// Portfolio-level option exposure + deterministic risk flags.
export const optionFlagSchema = z.looseObject({
  code: z.string(),
  severity: z.string(), // info | watch | high
  detail: z.string(),
});
export type OptionFlag = z.infer<typeof optionFlagSchema>;

export const optionExposureSchema = z.looseObject({
  net_delta: z.number(),
  gross_delta: z.number(),
  net_gamma: z.number(),
  net_theta: z.number(),
  net_vega: z.number(),
  option_market_value: z.number().nullish(),
  option_notional: z.number(),
  short_collateral_estimate: z.number(),
  contracts: z.number(),
  short_contracts: z.number(),
  expiry_ladder: z.array(
    z.looseObject({
      expiry: z.string(),
      days_to_expiry: z.number(),
      contracts: z.number(),
      net_delta: z.number(),
      net_notional: z.number(),
    }),
  ),
  underlying_exposure: z.array(
    z.looseObject({
      underlying: z.string(),
      contracts: z.number(),
      net_delta: z.number(),
      net_notional: z.number(),
      equity_shares: z.number().nullish(),
    }),
  ),
  flags: z.array(optionFlagSchema),
});
export type OptionExposure = z.infer<typeof optionExposureSchema>;

export const optionTotalsSchema = z.looseObject({
  net_delta: z.number(),
  net_gamma: z.number(),
  net_theta: z.number(),
  net_vega: z.number(),
  delta_notional: z.number(),
  market_value: z.number(),
  unrealized_pnl: z.number().nullish(),
  contracts: z.number(),
});
export type OptionTotals = z.infer<typeof optionTotalsSchema>;

// Stress grid (underlying × IV × time) — full Black-Scholes reprice, nested in
// the analyze response (one fetch covers analytics + exposure + scenarios).
export const scenarioCellSchema = z.looseObject({
  underlying_shock: z.number(),
  iv_shock: z.number(),
  horizon: z.union([z.number(), z.string()]),
  total_pnl: z.number(),
});
export type ScenarioCell = z.infer<typeof scenarioCellSchema>;

export const optionScenarioGridSchema = z.looseObject({
  grid: z.array(scenarioCellSchema),
  top_positions: z.array(
    z.looseObject({
      underlying: z.string().nullish(),
      option_type: z.string().nullish(),
      strike: z.number().nullish(),
      expiry: z.string().nullish(),
      quantity: z.number().nullish(),
      pnl: z.number(),
    }),
  ),
  stress_cell: z.record(z.string(), z.number()),
  underlying_shocks: z.array(z.number()),
  iv_shocks: z.array(z.number()),
  horizons: z.array(z.union([z.number(), z.string()])),
  repriced: z.number(),
  skipped: z.array(z.record(z.string(), z.unknown())),
  as_of: z.string().nullish(),
});
export type OptionScenarioGrid = z.infer<typeof optionScenarioGridSchema>;

export const optionStrategySchema = z.looseObject({
  underlying: z.string(),
  expiry: z.string(),
  name: z.string(),
  leg_count: z.number(),
  net_debit: z.number(), // >0 debit paid, <0 credit received
  net_pnl: z.number().nullish(),
  max_loss: z.number().nullish(), // null = unbounded
  max_gain: z.number().nullish(), // null = unbounded
  break_evens: z.array(z.number()),
  net_greeks: z.record(z.string(), z.number()),
  payoff: z.array(payoffPointSchema),
  legs: z.array(optionAnalyticsSchema),
});
export type OptionStrategy = z.infer<typeof optionStrategySchema>;

export const optionAnalyzeResponseSchema = z.looseObject({
  results: z.array(optionAnalyticsSchema),
  totals: optionTotalsSchema,
  exposure: optionExposureSchema,
  scenarios: optionScenarioGridSchema,
  strategies: z.array(optionStrategySchema).nullish(),
  as_of: z.string(),
  warnings: z.array(z.string()),
});
export type OptionAnalyzeResponse = z.infer<typeof optionAnalyzeResponseSchema>;

// Options AI-explain: deterministic skeleton → optional LLM rephrase.
export const optionExplainSchema = z.looseObject({
  severity: z.string(), // low | moderate | elevated | high
  headline: z.string(),
  summary_bullets: z.array(z.string()),
  suggested_actions: z.array(
    z.looseObject({ title: z.string(), reason: z.string(), next_step: z.string() }),
  ),
  caveats: z.array(z.string()),
  ai_generated: z.boolean(),
});
export type OptionExplain = z.infer<typeof optionExplainSchema>;

export type OptionContract = {
  underlying: string;
  option_type: "call" | "put";
  strike: number;
  expiry: string;
  quantity: number;
  avg_premium?: number;
  contract_multiplier?: number;
};

/**
 * Option contracts of the user's ACTIVE (default-flagged) portfolio — the book
 * the risk report scores. Shared by /risk and /portfolios/[id]/risk so the
 * active-portfolio resolution lives in one place. [] when no portfolio/options.
 */
export function activePortfolioOptionContracts(
  me: PortfoliosMe | undefined,
): OptionContract[] {
  const rows = me?.portfolios ?? [];
  const active = rows.find((p) => p.is_default) ?? rows[0];
  return optionContractsFromHoldings(active?.holdings);
}

/**
 * Pull option contracts out of a portfolio's holdings dict (the entries with
 * asset_type === "option"), shaped for POST /options/analyze. Equity holdings
 * are ignored. Returns [] when the book has no options.
 */
export function optionContractsFromHoldings(
  holdings: Record<string, Record<string, unknown>> | undefined,
): OptionContract[] {
  const out: OptionContract[] = [];
  for (const h of Object.values(holdings ?? {})) {
    if (String(h.asset_type ?? "").toLowerCase() !== "option") continue;
    const underlying = String(h.underlying ?? "").toUpperCase();
    const strike = Number(h.strike);
    const expiry = String(h.expiry ?? "");
    if (!underlying || !Number.isFinite(strike) || strike <= 0 || !expiry) continue;
    // A sold/written leg is short → negative quantity (the analytics + delta
    // overlay read the sign). `shares` is stored as a positive magnitude.
    const magnitude = Number(h.shares ?? 1) || 1;
    const quantity = h.option_side === "short" ? -magnitude : magnitude;
    out.push({
      underlying,
      option_type: h.option_type === "put" ? "put" : "call",
      strike,
      expiry,
      quantity,
      avg_premium: typeof h.avg_cost === "number" ? h.avg_cost : undefined,
      contract_multiplier: typeof h.contract_multiplier === "number" ? h.contract_multiplier : 100,
    });
  }
  return out;
}

/**
 * Analytics for a set of option contracts. A query (not a mutation) keyed on
 * the contract set so it auto-runs when the page mounts with options and is
 * served from cache on tab/route revisits. Disabled when there are no options
 * or no auth token.
 */
export function useOptionAnalytics(contracts: OptionContract[]) {
  const { accessToken } = useAuth();
  return useQuery<OptionAnalyzeResponse, Error>({
    queryKey: ["options-analyze", contracts],
    enabled: Boolean(accessToken) && contracts.length > 0,
    staleTime: 60_000,
    queryFn: () =>
      apiFetch<OptionAnalyzeResponse>("/api/v1/options/analyze", {
        method: "POST",
        body: { contracts },
        authToken: accessToken ?? undefined,
        schema: optionAnalyzeResponseSchema,
      }),
  });
}

/**
 * Plain-language explanation of the option book's risk. Deterministic skeleton
 * the LLM may only rephrase (severity/actions locked). Keyed on the exposure so
 * identical exposure is cached; FREE (no credit). Disabled until exposure loads.
 */
export function useOptionExplain(exposure: OptionExposure | undefined) {
  const { accessToken } = useAuth();
  return useQuery<OptionExplain, Error>({
    queryKey: ["options-explain", exposure],
    enabled: Boolean(accessToken) && Boolean(exposure) && (exposure?.contracts ?? 0) > 0,
    staleTime: 5 * 60_000,
    queryFn: () =>
      apiFetch<OptionExplain>("/api/v1/options/explain", {
        method: "POST",
        body: { exposure },
        authToken: accessToken ?? undefined,
        schema: optionExplainSchema,
      }),
  });
}

// Copilot chat now streams over SSE (see CopilotConversation, which reads
// /api/v1/copilot/chat/stream directly); the old non-streaming useCopilotChat
// hook + copilotResponseSchema were removed when the streaming path landed.

// ── Copilot 2.0 — structured single-shot answer ─────────────────────
// A one-shot /ask endpoint that returns a pre-formatted markdown answer
// PLUS structured evidence (each numeric fact tagged with its source) and
// the classified intent. Distinct from the streaming chat: this is a
// mutation (explicit "Ask" click, credit-gated) whose result renders as a
// structured card, not a running conversation.

const copilotEvidenceSchema = z.looseObject({
  label: z.string(),
  value: z.string(),
  source: z.string(), // engine|fmp|yfinance|macro|derived|glossary
  // PR2 traceability (additive): per-answer id ("E1"…) + producing tool.
  id: z.string().nullish(),
  tool: z.string().nullish(),
});
export type CopilotEvidence = z.infer<typeof copilotEvidenceSchema>;

// PR2: one of the six structured answer sections. `answer_markdown` is
// composed from these on the backend, so flat and structured cannot drift;
// rendering the flat answer (current UI) stays fully supported.
const copilotSectionSchema = z.looseObject({
  key: z.string(), // direct_answer|portfolio_relevance|evidence|data_confidence|what_would_change|simulation
  title: z.string(),
  markdown: z.string(),
  ai_generated: z.boolean().optional(),
});
export type CopilotSection = z.infer<typeof copilotSectionSchema>;

export const copilotAnswerSchema = z.looseObject({
  intent: z.string(),
  tickers: z.array(z.string()),
  answer_markdown: z.string(),
  evidence: z.array(copilotEvidenceSchema),
  data_only: z.boolean(),
  model: z.string().nullish(),
  conviction: z.string().nullish(),
  data_confidence: dataConfidenceSchema.nullish(),
  // PR2 additive fields — optional so pre-PR2 responses still validate.
  sections: z.array(copilotSectionSchema).optional(),
  language: z.string().optional(),
  disclaimer: z.string().nullish(),
});
export type CopilotAnswer = z.infer<typeof copilotAnswerSchema>;

/**
 * Ask the Copilot 2.0 structured-answer endpoint. A mutation (explicit user
 * action — it spends credits). 429 `quota_exceeded` on quota; `data_only`
 * answer (no LLM key) is still a valid 200. Mirrors the auth-token + schema
 * plumbing of the other copilot/equity mutations in this file.
 */
export function useCopilotAsk() {
  const { accessToken } = useAuth();
  return useMutation<
    CopilotAnswer,
    Error,
    { message: string; route?: string; ticker?: string }
  >({
    mutationFn: ({ message, route, ticker }) =>
      apiFetch<CopilotAnswer>("/api/v1/copilot/ask", {
        method: "POST",
        // route/ticker are page CONTEXT — they steer intent + tool choice on
        // the backend but never become citable evidence.
        body: { message, ...(route ? { route } : {}), ...(ticker ? { ticker } : {}) },
        authToken: accessToken ?? undefined,
        schema: copilotAnswerSchema,
      }),
  });
}

// ── Copilot PR3/PR4 — confirmed preferences + proactive insights ─────

export const copilotPreferencesSchema = z.looseObject({
  confirmed: z.boolean(),
  risk_tolerance: z.number().nullish(),
  investment_horizon: z.string().nullish(),
  liquidity_need: z.string().nullish(),
  concentration_limit: z.number().nullish(),
  margin_limit: z.number().nullish(),
  confirmed_at: z.string().nullish(),
  updated_at: z.string().nullish(),
});
export type CopilotPreferences = z.infer<typeof copilotPreferencesSchema>;

export type CopilotPreferencesInput = {
  risk_tolerance?: number | null;
  investment_horizon?: string | null;
  liquidity_need?: string | null;
  concentration_limit?: number | null;
  margin_limit?: number | null;
};

/** The user's confirmed Copilot preferences. 503 = the feature isn't
 * provisioned → surfaces as an error the card uses to hide itself. */
export function useCopilotPreferences() {
  const { accessToken } = useAuth();
  return useQuery<CopilotPreferences, Error>({
    queryKey: ["copilot-preferences"],
    enabled: Boolean(accessToken),
    retry: false,
    staleTime: 60_000,
    queryFn: () =>
      apiFetch<CopilotPreferences>("/api/v1/copilot/preferences", {
        authToken: accessToken ?? undefined,
        schema: copilotPreferencesSchema,
      }),
  });
}

/** The explicit CONFIRMATION act — the only write path for preferences. */
export function useSaveCopilotPreferences() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  return useMutation<CopilotPreferences, Error, CopilotPreferencesInput>({
    mutationFn: (body) =>
      apiFetch<CopilotPreferences>("/api/v1/copilot/preferences", {
        method: "PUT",
        body,
        authToken: accessToken ?? undefined,
        schema: copilotPreferencesSchema,
      }),
    onSuccess: (data) => queryClient.setQueryData(["copilot-preferences"], data),
  });
}

/** Complete erasure of the stored preferences. */
export function useClearCopilotPreferences() {
  const { accessToken } = useAuth();
  const queryClient = useQueryClient();
  return useMutation<{ cleared?: boolean }, Error, void>({
    mutationFn: () =>
      apiFetch<{ cleared?: boolean }>("/api/v1/copilot/preferences", {
        method: "DELETE",
        authToken: accessToken ?? undefined,
        schema: z.looseObject({ cleared: z.boolean().optional() }),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["copilot-preferences"] }),
  });
}

const copilotInsightSchema = z.looseObject({
  id: z.string(),
  kind: z.string(),
  severity: z.string(),
  what_changed: z.string(),
  why_it_matters: z.string(),
  evidence: z.array(copilotEvidenceSchema),
  confidence: z.string().nullish(),
  as_of: z.string().nullish(),
  missing_data: z.array(z.string()),
  suggested_next_analysis: z
    .looseObject({ label: z.string(), href: z.string() })
    .nullish(),
});
export type CopilotInsight = z.infer<typeof copilotInsightSchema>;

export const copilotInsightsSchema = z.looseObject({
  insights: z.array(copilotInsightSchema),
  as_of: z.string().nullish(),
  portfolio_available: z.boolean(),
  missing_data: z.array(z.string()).optional(),
});
export type CopilotInsights = z.infer<typeof copilotInsightsSchema>;

/** Deterministic proactive insights — material changes only, never advice. */
export function useCopilotInsights() {
  const { accessToken } = useAuth();
  return useQuery<CopilotInsights, Error>({
    queryKey: ["copilot-insights"],
    enabled: Boolean(accessToken),
    retry: false,
    staleTime: 5 * 60_000,
    queryFn: () =>
      apiFetch<CopilotInsights>("/api/v1/copilot/insights", {
        authToken: accessToken ?? undefined,
        schema: copilotInsightsSchema,
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

// (The pre-FactPack /equity dossier hooks were removed 2026-06-11 — the
// /research cockpit reads /research/fact_pack + /research/verdict only.)
const fnum = z.number().nullish();
const fstr = z.string().nullish();

// ── ticker research 2.0 (FactPack cockpit) ──────────────────────────
// Two-stage, same shape as the dossier flow above: useFactPack (fast,
// authed, no credit) paints the cockpit; useResearchVerdict (authed +
// credit-gated) phrases a verdict OVER the FactPack the cockpit already
// fetched — so /verdict never re-hits the network.

const factPackValuationSchema = z.looseObject({
  pe: fnum,
  forward_pe: fnum,
  ps: fnum,
  pb: fnum,
  ev_ebitda: fnum,
  fcf_yield: fnum,
  dividend_yield: fnum,
  band: fstr, // "cheap" | "in-line" | "rich" | null
  peer_median_pe: fnum,
});

const factPackQualitySchema = z.looseObject({
  gross_margin: fnum,
  operating_margin: fnum,
  net_margin: fnum,
  roe: fnum,
  roa: fnum,
  roic: fnum,
  current_ratio: fnum,
  debt_to_equity: fnum,
  interest_coverage: fnum,
});

const factPackGrowthSchema = z.looseObject({
  revenue_cagr: fnum,
  eps_cagr: fnum,
  fcf_cagr: fnum,
  revenue_growth_yoy: fnum,
  earnings_growth_yoy: fnum,
  periods: z.number().nullish(),
});

const factPackAnalystSchema = z.looseObject({
  rating: fstr,
  num_analysts: fnum,
  target_low: fnum,
  target_consensus: fnum,
  target_high: fnum,
  implied_upside_pct: fnum,
});

const factPackMomentumSchema = z.looseObject({
  rsi_14: fnum,
  sma_50: fnum,
  sma_200: fnum,
  price_vs_sma50_pct: fnum,
  price_vs_sma200_pct: fnum,
  fifty_two_week_high: fnum,
  fifty_two_week_low: fnum,
  pct_from_52w_high: fnum,
  pct_off_52w_low: fnum,
  realized_vol_20d: fnum,
  realized_vol_60d: fnum,
  trend: fstr, // "uptrend" | "downtrend" | "mixed"
});

const factPackOwnershipSchema = z.looseObject({
  institutional_pct: fnum,
});

const factPackInsiderSchema = z.looseObject({
  buys_90d: z.number().nullish(),
  sells_90d: z.number().nullish(),
  net_shares_90d: fnum,
  signal: fstr, // "net buying" | "net selling" | "balanced"
});

const factPackPeerSchema = z.looseObject({
  ticker: z.string(),
  name: fstr,
  market_cap: fnum,
  pe: fnum,
  ps: fnum,
  net_margin: fnum,
  roe: fnum,
});

const factPackNewsSchema = z.looseObject({
  title: z.string(),
  site: fstr,
  published: fstr,
  url: fstr,
});

const factPackDataQualitySourceSchema = z.looseObject({
  field: z.string(),
  source: z.string(), // "fmp" | "yfinance" | "derived" | "unavailable"
  as_of: fstr,
  coverage: fnum,
});

const factPackDataQualitySchema = z.looseObject({
  coverage: fnum,
  sources: z.array(factPackDataQualitySourceSchema),
  warnings: z.array(z.string()),
});

export const factPackSchema = z.looseObject({
  ticker: z.string(),
  name: fstr,
  sector: fstr,
  industry: fstr,
  currency: fstr,
  as_of: fstr,
  price: fnum,
  market_cap: fnum,
  beta: fnum,
  valuation: factPackValuationSchema,
  quality: factPackQualitySchema,
  growth: factPackGrowthSchema,
  analyst: factPackAnalystSchema,
  momentum: factPackMomentumSchema.nullish(),
  ownership: factPackOwnershipSchema.nullish(),
  insider: factPackInsiderSchema.nullish(),
  peers: z.array(factPackPeerSchema),
  news: z.array(factPackNewsSchema),
  drivers: z.array(z.string()),
  risk_flags: z.array(z.string()),
  data_quality: factPackDataQualitySchema,
});
export type FactPack = z.infer<typeof factPackSchema>;

const verdictDimensionSchema = z.looseObject({
  name: z.string(), // valuation | growth | quality | momentum | risk
  score: z.number(),
  note: fstr,
});
export const researchVerdictSchema = z.looseObject({
  rating: z.string(), // data screen: Strong | Favorable | Mixed | Weak | Very Weak (never buy/sell)
  conviction: z.string(), // low | medium | high
  summary: z.string(),
  dimensions: z.array(verdictDimensionSchema),
  catalysts: z.array(z.string()),
  risks: z.array(z.string()),
  what_would_change_my_mind: z.array(z.string()),
  data_only: z.boolean(),
  data_confidence: dataConfidenceSchema.nullish(),
});
export type ResearchVerdict = z.infer<typeof researchVerdictSchema>;

export const factPackResponseSchema = z.looseObject({
  fact_pack: factPackSchema,
});
export type FactPackResponse = z.infer<typeof factPackResponseSchema>;

export const researchVerdictResponseSchema = z.looseObject({
  verdict: researchVerdictSchema,
  fact_pack: factPackSchema,
});
export type ResearchVerdictResponse = z.infer<
  typeof researchVerdictResponseSchema
>;

// ── unified ticker news (FMP news + press releases + SEC, source-labeled) ──
export const unifiedNewsItemSchema = z.looseObject({
  title: z.string(),
  url: z.string().nullish(),
  type: z.string(), // news | press_release | earnings_transcript | filing | macro
  source: z.string(),
  source_label: z.string(),
  site: z.string().nullish(),
  published: z.string().nullish(),
  snippet: z.string().nullish(),
});
export type UnifiedNewsItem = z.infer<typeof unifiedNewsItemSchema>;

export const tickerNewsSchema = z.looseObject({
  items: z.array(unifiedNewsItemSchema),
  sources: z.array(sourceProvenanceSchema),
  warnings: z.array(z.string()),
});
export type TickerNews = z.infer<typeof tickerNewsSchema>;

/** Unified, source-labeled news for a ticker. Authed, no credit; cached. */
export function useTickerNews(ticker: string | null) {
  const { accessToken } = useAuth();
  return useQuery<TickerNews>({
    queryKey: ["research", "news", ticker],
    enabled: Boolean(accessToken && ticker),
    queryFn: () =>
      apiFetch<TickerNews>(`/api/v1/research/news/${encodeURIComponent(ticker!)}`, {
        authToken: accessToken!,
        schema: tickerNewsSchema,
      }),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

// ── Institutional Research FactPack (financials + deterministic trends) ──
// Every number here is computed by the backend; the LLM is never involved.
const finFigures = {
  revenue: z.number().nullish(),
  gross_profit: z.number().nullish(),
  operating_income: z.number().nullish(),
  net_income: z.number().nullish(),
  eps: z.number().nullish(),
  eps_diluted: z.number().nullish(),
  free_cash_flow: z.number().nullish(),
  capex: z.number().nullish(),
  cash: z.number().nullish(),
  debt: z.number().nullish(),
  shares_outstanding: z.number().nullish(),
  diluted_shares: z.number().nullish(),
  ebitda: z.number().nullish(),
  gross_margin: z.number().nullish(),
  operating_margin: z.number().nullish(),
  net_margin: z.number().nullish(),
  fcf_margin: z.number().nullish(),
};

export const researchFactPackSchema = z.looseObject({
  ticker: z.string(),
  as_of: z.string().nullish(),
  generated_at: z.string().nullish(),
  snapshot: z.looseObject({
    ticker: z.string(),
    name: z.string().nullish(),
    sector: z.string().nullish(),
    industry: z.string().nullish(),
    exchange: z.string().nullish(),
    currency: z.string().default("USD"),
    price: z.number().nullish(),
    market_cap: z.number().nullish(),
    beta: z.number().nullish(),
    shares_outstanding: z.number().nullish(),
  }),
  quarters: z.array(z.looseObject({ period: z.string(), fiscal_date: z.string().nullish(), ...finFigures })),
  annuals: z.array(z.looseObject({ fiscal_year: z.string(), fiscal_date: z.string().nullish(), ...finFigures })),
  trend: z.looseObject({
    ttm_revenue: z.number().nullish(),
    ttm_ebitda: z.number().nullish(),
    ttm_fcf: z.number().nullish(),
    ttm_eps: z.number().nullish(),
    ttm_net_income: z.number().nullish(),
    revenue_yoy: z.number().nullish(),
    revenue_qoq: z.number().nullish(),
    eps_yoy: z.number().nullish(),
    net_income_yoy: z.number().nullish(),
    prior_revenue_yoy: z.number().nullish(),
    gross_margin_delta_yoy: z.number().nullish(),
    operating_margin_delta_yoy: z.number().nullish(),
    net_margin_delta_yoy: z.number().nullish(),
    revenue_trend: z.string().nullish(),
    flags: z.array(z.string()),
    quarters_used: z.number(),
    annuals_used: z.number(),
  }),
  provenance: z.array(
    z.looseObject({
      dataset: z.string(),
      source: z.string(),
      as_of: z.string().nullish(),
      fetched_at: z.string().nullish(),
      coverage: z.number(),
      note: z.string().nullish(),
    }),
  ),
  missing_data: z.array(z.looseObject({ dataset: z.string(), reason: z.string() })),
  data_confidence: z.number(),
  confidence_label: z.string(),
  disclaimer: z.string(),
});
export type ResearchFactPack = z.infer<typeof researchFactPackSchema>;

const researchFactPackResponseSchema = z.looseObject({ fact_pack: researchFactPackSchema });
type ResearchFactPackResponse = z.infer<typeof researchFactPackResponseSchema>;

/** Institutional FactPack (financial statements + deterministic trends).
 * Authed, no credit; cached. Self-fetches by ticker. */
export function useResearchFinancials(ticker: string | null) {
  const { accessToken } = useAuth();
  return useQuery<ResearchFactPackResponse>({
    queryKey: ["research", "financials", ticker],
    enabled: Boolean(accessToken && ticker),
    queryFn: () =>
      apiFetch<ResearchFactPackResponse>(
        `/api/v1/research/${encodeURIComponent(ticker!)}/fact-pack`,
        { authToken: accessToken!, schema: researchFactPackResponseSchema },
      ),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

// ── DCF valuation (deterministic; user overrides recalc) ────────────
const dcfAssumptionSchema = z.looseObject({
  name: z.string(),
  value: z.number().nullish(),
  source_type: z.string(),
  source: z.string().nullish(),
  note: z.string().nullish(),
});
const dcfProjectionSchema = z.looseObject({
  year: z.number(),
  revenue: z.number(),
  revenue_growth: z.number(),
  operating_margin: z.number(),
  ebit: z.number(),
  nopat: z.number(),
  fcf: z.number(),
  pv_fcf: z.number(),
});
const dcfScenarioSchema = z.looseObject({
  name: z.string(),
  implied_value_per_share: z.number().nullish(),
  upside_pct: z.number().nullish(),
});
const dcfSensitivitySchema = z.looseObject({
  title: z.string(),
  row_label: z.string(),
  col_label: z.string(),
  rows: z.array(z.number()),
  cols: z.array(z.number()),
  values: z.array(z.array(z.number().nullable())),
});
const dcfHistoricalRowSchema = z.looseObject({
  fiscal_year: z.string().nullish(),
  fiscal_date: z.string().nullish(),
  revenue: z.number().nullish(),
  revenue_growth: z.number().nullish(),
  ebit: z.number().nullish(),
  ebit_margin: z.number().nullish(),
  taxes: z.number().nullish(),
  tax_pct_ebit: z.number().nullish(),
  da: z.number().nullish(),
  da_pct_sales: z.number().nullish(),
  capex: z.number().nullish(),
  capex_pct_sales: z.number().nullish(),
  change_nwc: z.number().nullish(),
  nwc_pct_sales: z.number().nullish(),
});

export const dcfOutputSchema = z.looseObject({
  ticker: z.string(),
  currency: z.string().default("USD"),
  as_of: z.string().nullish(),
  inputs: z.looseObject({
    projection_years: z.number(),
    base_revenue: dcfAssumptionSchema,
    revenue_growth: z.array(dcfAssumptionSchema),
    operating_margin: z.array(dcfAssumptionSchema),
    tax_rate: dcfAssumptionSchema,
    da_pct_revenue: dcfAssumptionSchema,
    capex_pct_revenue: dcfAssumptionSchema,
    nwc_pct_revenue: dcfAssumptionSchema,
    wacc: dcfAssumptionSchema,
    wacc_breakdown: z.array(dcfAssumptionSchema).default([]),
    terminal_growth: dcfAssumptionSchema,
    net_debt: dcfAssumptionSchema,
    diluted_shares: dcfAssumptionSchema,
    missing_data: z.array(z.looseObject({ dataset: z.string(), reason: z.string() })),
  }),
  valuation_date: z.string().nullish(),
  historical: z.array(dcfHistoricalRowSchema).default([]),
  projections: z.array(dcfProjectionSchema),
  terminal_value: z.number().nullish(),
  pv_terminal_value: z.number().nullish(),
  enterprise_value: z.number().nullish(),
  // Itemized equity bridge (workbook DCF rows 59–63).
  cash: z.number().nullish(),
  short_term_investments: z.number().nullish(),
  total_debt: z.number().nullish(),
  minority_interest: z.number().nullish(),
  diluted_shares: z.number().nullish(),
  equity_value: z.number().nullish(),
  implied_value_per_share: z.number().nullish(),
  current_price: z.number().nullish(),
  upside_pct: z.number().nullish(),
  scenarios: z.array(dcfScenarioSchema),
  sensitivity: z.array(dcfSensitivitySchema),
  valid: z.boolean(),
  warnings: z.array(z.string()),
  disclaimer: z.string(),
});
export type DcfOutput = z.infer<typeof dcfOutputSchema>;
const dcfResponseSchema = z.looseObject({ dcf: dcfOutputSchema });
type DcfResponse = z.infer<typeof dcfResponseSchema>;

export type DcfOverrides = {
  projection_years?: number;
  base_revenue?: number;
  wacc?: number;
  terminal_growth?: number;
  tax_rate?: number;
  revenue_growth?: number[];
  operating_margin?: number;
  terminal_operating_margin?: number;
  da_pct_revenue?: number;
  capex_pct_revenue?: number;
  nwc_pct_revenue?: number;
  net_debt?: number;
  diluted_shares?: number;
  // WACC build-up overrides (workbook WACC sheet).
  cost_of_debt?: number;
  risk_free_rate?: number;
  beta?: number;
  market_risk_premium?: number;
  equity_value?: number;
  total_debt?: number;
  short_term_investments?: number;
  minority_interest?: number;
};

/** Deterministic DCF; pass overrides to recompute. Authed, no credit. */
export function useDcf() {
  const { accessToken } = useAuth();
  return useMutation<DcfResponse, Error, { ticker: string; overrides?: DcfOverrides }>({
    mutationFn: ({ ticker, overrides }) =>
      apiFetch<DcfResponse>(`/api/v1/research/${encodeURIComponent(ticker)}/dcf`, {
        method: "POST",
        body: { overrides: overrides ?? null },
        authToken: accessToken ?? undefined,
        schema: dcfResponseSchema,
      }),
  });
}

// ── Peer comparison (deterministic; median + percentiles) ───────────
const peerRowSchema = z.looseObject({
  ticker: z.string(),
  name: z.string().nullish(),
  is_subject: z.boolean(),
  market_cap: z.number().nullish(),
  revenue_growth: z.number().nullish(),
  gross_margin: z.number().nullish(),
  operating_margin: z.number().nullish(),
  net_margin: z.number().nullish(),
  fcf_margin: z.number().nullish(),
  roe: z.number().nullish(),
  roic: z.number().nullish(),
  pe: z.number().nullish(),
  forward_pe: z.number().nullish(),
  ev_sales: z.number().nullish(),
  ev_ebitda: z.number().nullish(),
  ps: z.number().nullish(),
  debt_to_equity: z.number().nullish(),
  net_cash: z.number().nullish(),
  return_1y: z.number().nullish(),
});
export type PeerRow = z.infer<typeof peerRowSchema>;
const peerPercentileSchema = z.looseObject({
  metric: z.string(),
  subject_value: z.number().nullish(),
  peer_median: z.number().nullish(),
  percentile: z.number().nullish(),
  n: z.number(),
});
export type PeerPercentile = z.infer<typeof peerPercentileSchema>;
export const peersOutputSchema = z.looseObject({
  ticker: z.string(),
  as_of: z.string().nullish(),
  peer_source: z.string(),
  rows: z.array(peerRowSchema),
  percentiles: z.array(peerPercentileSchema),
  missing_data: z.array(z.looseObject({ dataset: z.string(), reason: z.string() })),
  disclaimer: z.string(),
});
export type PeersOutput = z.infer<typeof peersOutputSchema>;
const peersResponseSchema = z.looseObject({ peers: peersOutputSchema });
type PeersResponse = z.infer<typeof peersResponseSchema>;

/** Deterministic peer comparison + percentiles. Authed, no credit; cached. */
export function usePeers(ticker: string | null, userPeers?: string) {
  const { accessToken } = useAuth();
  return useQuery<PeersResponse>({
    queryKey: ["research", "peers", ticker, userPeers ?? null],
    enabled: Boolean(accessToken && ticker),
    queryFn: () => {
      const qs = userPeers ? `?peers=${encodeURIComponent(userPeers)}` : "";
      return apiFetch<PeersResponse>(
        `/api/v1/research/${encodeURIComponent(ticker!)}/peers${qs}`,
        { authToken: accessToken!, schema: peersResponseSchema },
      );
    },
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

// ── Earnings comparison (deterministic) ─────────────────────────────
const earningsPeriodSchema = z.looseObject({
  period: z.string(),
  fiscal_date: z.string().nullish(),
  revenue: z.number().nullish(),
  revenue_yoy: z.number().nullish(),
  revenue_qoq: z.number().nullish(),
  eps: z.number().nullish(),
  eps_yoy: z.number().nullish(),
  eps_qoq: z.number().nullish(),
  revenue_estimate: z.number().nullish(),
  eps_estimate: z.number().nullish(),
  revenue_surprise_pct: z.number().nullish(),
  eps_surprise_pct: z.number().nullish(),
  revenue_beat: z.boolean().nullish(),
  eps_beat: z.boolean().nullish(),
});
export type EarningsPeriod = z.infer<typeof earningsPeriodSchema>;
export const earningsOutputSchema = z.looseObject({
  ticker: z.string(),
  as_of: z.string().nullish(),
  periods: z.array(earningsPeriodSchema),
  transcript: z.looseObject({
    available: z.boolean(),
    quarter: z.number().nullish(),
    fiscal_year: z.number().nullish(),
    date: z.string().nullish(),
    source: z.string().nullish(),
    excerpt_length: z.number(),
  }),
  summary: z.looseObject({
    headline: z.string().nullish(),
    points: z.array(z.string()),
    ai_generated: z.boolean(),
  }),
  missing_data: z.array(z.looseObject({ dataset: z.string(), reason: z.string() })),
  disclaimer: z.string(),
});
export type EarningsOutput = z.infer<typeof earningsOutputSchema>;
const earningsResponseSchema = z.looseObject({ earnings: earningsOutputSchema });
type EarningsResponse = z.infer<typeof earningsResponseSchema>;

/** Deterministic earnings comparison. Authed, no credit; cached. */
export function useEarnings(ticker: string | null) {
  const { accessToken } = useAuth();
  return useQuery<EarningsResponse>({
    queryKey: ["research", "earnings", ticker],
    enabled: Boolean(accessToken && ticker),
    queryFn: () =>
      apiFetch<EarningsResponse>(`/api/v1/research/${encodeURIComponent(ticker!)}/earnings`, {
        authToken: accessToken!,
        schema: earningsResponseSchema,
      }),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

// ── AI thesis (LLM over deterministic evidence; credit-gated) ───────
export const thesisOutputSchema = z.looseObject({
  ticker: z.string(),
  bull_case: z.array(z.string()),
  bear_case: z.array(z.string()),
  key_debate: z.string().nullish(),
  what_would_change_view: z.array(z.string()),
  monitor_next_quarter: z.array(z.string()),
  questions_for_management: z.array(z.string()),
  red_flags: z.array(z.string()),
  ai_generated: z.boolean(),
  flagged_numbers: z.array(z.string()),
  warnings: z.array(z.string()),
  disclaimer: z.string(),
});
export type ThesisOutput = z.infer<typeof thesisOutputSchema>;
const thesisResponseSchema = z.looseObject({ thesis: thesisOutputSchema });
type ThesisResponse = z.infer<typeof thesisResponseSchema>;

/** AI-grounded bull/bear thesis. Authed, credit-gated (mutation, on demand). */
export function useThesis() {
  const { accessToken } = useAuth();
  return useMutation<ThesisResponse, Error, { ticker: string }>({
    mutationFn: ({ ticker }) =>
      apiFetch<ThesisResponse>(`/api/v1/research/${encodeURIComponent(ticker)}/thesis`, {
        method: "POST",
        authToken: accessToken ?? undefined,
        schema: thesisResponseSchema,
      }),
  });
}

// ── Analyst HTML report (deterministic, assembled server-side) ──────
const analystReportSchema = z.looseObject({
  ticker: z.string(),
  title: z.string(),
  generated_at: z.string().nullish(),
  as_of: z.string().nullish(),
  html: z.string(),
  sections: z.array(z.looseObject({ key: z.string(), title: z.string(), included: z.boolean() })),
  disclaimer: z.string(),
});
export type AnalystReport = z.infer<typeof analystReportSchema>;
const analystReportResponseSchema = z.looseObject({ report: analystReportSchema });
type AnalystReportResponse = z.infer<typeof analystReportResponseSchema>;

/** Server-assembled analyst HTML report. Authed, no credit; cached. */
export function useAnalystReport(ticker: string | null) {
  const { accessToken } = useAuth();
  return useQuery<AnalystReportResponse>({
    queryKey: ["research", "report", ticker],
    enabled: Boolean(accessToken && ticker),
    queryFn: () =>
      apiFetch<AnalystReportResponse>(`/api/v1/research/${encodeURIComponent(ticker!)}/report`, {
        authToken: accessToken!,
        schema: analystReportResponseSchema,
      }),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

/** Fetch the deterministic FactPack for a ticker (fast, no credit). */
export function useFactPack() {
  const { accessToken } = useAuth();
  return useMutation<FactPackResponse, Error, { ticker: string }>({
    mutationFn: ({ ticker }) =>
      apiFetch<FactPackResponse>(
        `/api/v1/research/fact_pack/${encodeURIComponent(ticker)}`,
        {
          authToken: accessToken ?? undefined,
          schema: factPackResponseSchema,
        },
      ),
  });
}

/** Phrase an AI verdict over an already-fetched FactPack (credit-gated). */
export function useResearchVerdict() {
  const { accessToken } = useAuth();
  return useMutation<ResearchVerdictResponse, Error, { fact_pack: FactPack }>({
    mutationFn: (body) =>
      apiFetch<ResearchVerdictResponse>("/api/v1/research/verdict", {
        method: "POST",
        body,
        authToken: accessToken ?? undefined,
        schema: researchVerdictResponseSchema,
      }),
  });
}

// ── consolidated research bundle (ONE fetch for the whole page) ─────────
// Reuses every block schema above. A ticker search fans out to the providers
// once (server-side, shared cache) instead of one fetch per tab.
export const researchBundleSchema = z.looseObject({
  ticker: z.string(),
  generated_at: z.string().nullish(),
  as_of: z.string().nullish(),
  data_confidence: z.number().nullish(),
  confidence_label: z.string().nullish(),
  fact_pack: factPackSchema.nullish(),
  financials: researchFactPackSchema.nullish(),
  dcf: dcfOutputSchema.nullish(),
  peers: peersOutputSchema.nullish(),
  earnings: earningsOutputSchema.nullish(),
  thesis: thesisOutputSchema.nullish(),
  news: tickerNewsSchema.nullish(),
});
export type ResearchBundle = z.infer<typeof researchBundleSchema>;
const researchBundleResponseSchema = z.looseObject({ bundle: researchBundleSchema });
type ResearchBundleResponse = z.infer<typeof researchBundleResponseSchema>;

/** Everything the consolidated research page needs in one fetch. Authed, no
 * credit; cached. Self-fetches by ticker (the page sets the active ticker on
 * search). The AI verdict + LLM thesis stay separate on-demand calls. */
export function useResearchBundle(ticker: string | null) {
  const { accessToken } = useAuth();
  return useQuery<ResearchBundleResponse>({
    queryKey: ["research", "bundle", ticker],
    enabled: Boolean(accessToken && ticker),
    queryFn: () =>
      apiFetch<ResearchBundleResponse>(`/api/v1/research/${encodeURIComponent(ticker!)}/bundle`, {
        authToken: accessToken!,
        schema: researchBundleResponseSchema,
      }),
    staleTime: 10 * 60 * 1000,
    retry: false,
  });
}

// ── scenario simulator + efficient frontier ─────────────────────────
const frontierPointSchema = z.looseObject({ vol: z.number(), ret: z.number() });
export const efficientFrontierSchema = z.looseObject({
  frontier: z.array(frontierPointSchema),
  current: frontierPointSchema,
  risk_free_rate: z.number(),
  as_of: z.string().nullable().optional(),
  observations: z.number().nullable().optional(),
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
  as_of: z.string().nullable().optional(),
  observations: z.number().nullable().optional(),
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
  daily_pnl: z.number().nullish(),
  daily_return: z.number().nullish(),
  total_pnl: z.number().nullish(),
  total_return: z.number().nullish(),
  contributed_capital: z.number().nullish(),
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
  confidence_label: z.string().nullish(),
  directional_allowed: z.boolean().nullish(),
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

// ── deterministic "what changed?" vs the user's own prior snapshot ──
export const driverChangeSchema = z.looseObject({
  key: z.string(),
  label: z.string(),
  points: z.number(),
  detail: z.string().nullish(),
});

export const scoreChangeReportSchema = z.looseObject({
  window: z.string(),
  available: z.boolean(),
  as_of_previous: z.string().nullish(),
  current_score: z.number(),
  previous_score: z.number().nullish(),
  score_delta: z.number().nullish(),
  base_score_delta: z.number().nullish(),
  component_deltas: z.array(
    z.looseObject({
      key: z.string(),
      name: z.string(),
      previous: z.number().nullish(),
      current: z.number().nullish(),
      delta: z.number().nullish(),
      points_contribution: z.number().nullish(),
    }),
  ),
  input_changes: z.array(
    z.looseObject({
      key: z.string(),
      label: z.string(),
      previous: z.number().nullish(),
      current: z.number().nullish(),
      delta: z.number().nullish(),
      unit: z.string(),
      direction: z.string(),
    }),
  ),
  top_drivers: z.array(
    z.looseObject({
      key: z.string(),
      label: z.string(),
      points: z.number(),
      detail: z.string().nullish(),
    }),
  ),
  data_quality_changes: z.array(
    z.looseObject({
      key: z.string(),
      label: z.string(),
      previous: z.string().nullish(),
      current: z.string().nullish(),
      note: z.string().nullish(),
    }),
  ),
  holdings_changes: z.looseObject({
    added: z.array(z.string()),
    removed: z.array(z.string()),
    reweighted: z.array(z.looseObject({})),
  }),
  // Single biggest +/- dimension contributor (PR B).
  top_positive_contributor: driverChangeSchema.nullish(),
  top_negative_contributor: driverChangeSchema.nullish(),
  // Market / holding / data-quality attribution (PR B).
  attribution: z
    .looseObject({
      data_quality_driven: z.number().nullish(),
      market_driven: z.number().nullish(),
      holding_driven: z.number().nullish(),
      combined_market_holdings: z.number().nullish(),
      separable: z.boolean().optional().default(true),
      note: z.string().optional().default(""),
    })
    .nullish(),
  summary: z.string(),
  // Methodology provenance. When `comparable` is false the prior snapshot used a
  // DIFFERENT scoring version — the delta must NOT be shown as a market/holdings
  // move (backend nulls score_delta + the decomposition); the UI shows a notice.
  current_score_version: z.string().nullish(),
  previous_score_version: z.string().nullish(),
  comparable: z.boolean().nullish(),
});
export type ScoreChangeReport = z.infer<typeof scoreChangeReportSchema>;

/**
 * Deterministic "what changed?" — posts the CURRENT score the page already holds
 * (zero recompute) for a window (previous|7d|30d); the backend diffs it against
 * the user's own prior snapshot. The LLM is never involved.
 */
export function useScoreChanges(body: Record<string, unknown> | null) {
  const { accessToken, user } = useAuth();
  return useQuery<ScoreChangeReport>({
    queryKey: ["risk", "score_changes", user?.id ?? null, body ? JSON.stringify(body) : null],
    enabled: Boolean(accessToken && body),
    queryFn: () =>
      apiFetch<ScoreChangeReport>("/api/v1/risk/score_changes", {
        method: "POST",
        body: body!,
        authToken: accessToken!,
        schema: scoreChangeReportSchema,
      }),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

// ── upgraded Action Cards: deterministic levers + re-scored impact (PR C) ──
export const simulateHoldingSchema = z.looseObject({
  ticker: z.string(),
  market_value: z.number(),
  asset_type: z.string().optional().default("public_security"),
});
export const actionCardSchema = z.looseObject({
  key: z.string(),
  title: z.string(),
  rationale: z.string(),
  proposed_change: z.string(),
  expected_score_delta: z.number().nullish(),
  expected_score_after: z.number().nullish(),
  expected_var_delta: z.number().nullish(),
  expected_cvar_delta: z.number().nullish(),
  trade_offs: z.array(z.string()).optional().default([]),
  assumptions: z.array(z.string()).optional().default([]),
  simulate_holdings: z.array(simulateHoldingSchema).optional().default([]),
  disclaimer: z.string().optional().default(""),
});
export type ActionCard = z.infer<typeof actionCardSchema>;

export const actionSimulateSchema = z.looseObject({
  baseline_score: z.number(),
  baseline_var_95_daily: z.number().nullish(),
  baseline_cvar_95_daily: z.number().nullish(),
  actions: z.array(actionCardSchema).optional().default([]),
});
export type ActionSimulate = z.infer<typeof actionSimulateSchema>;

/**
 * Deterministic risk-lever Action Cards with expected impact re-scored on the
 * user's active book. Auth-gated query keyed on user.id (deterministic; no
 * credit). The cards never execute a trade — the simulate payload just prefills
 * the what-if sandbox.
 */
export function useSimulateActions() {
  const { accessToken, user } = useAuth();
  return useQuery<ActionSimulate>({
    queryKey: ["risk", "simulate_actions", user?.id ?? null],
    enabled: Boolean(accessToken),
    queryFn: () =>
      apiFetch<ActionSimulate>("/api/v1/risk/simulate_actions", {
        method: "POST",
        body: {},
        authToken: accessToken!,
        schema: actionSimulateSchema,
      }),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

// ── exportable HTML reports (server-rendered, deterministic) ────────
export const reportResponseSchema = z.looseObject({
  html: z.string(),
  input_hash: z.string(),
  as_of: z.string(),
  kind: z.string(),
});
export type ReportResponse = z.infer<typeof reportResponseSchema>;

// ── proactive risk alerts (deterministic, credit-free) ──────────────
export const riskAlertSchema = z.looseObject({
  type: z.string(),
  severity: z.string(), // low | moderate | elevated | high
  headline: z.string(),
  detail: z.string(),
  metric: z.string(),
  ask_copilot: z.string(),
});
export type RiskAlert = z.infer<typeof riskAlertSchema>;

const riskAlertsResponseSchema = z.looseObject({ alerts: z.array(riskAlertSchema) });

/** The numbers the page already has — score-level always, report-level on /risk. */
export type RiskAlertsInput = Record<string, unknown>;

export function useRiskAlerts(input: RiskAlertsInput | null) {
  const { accessToken, user } = useAuth();
  return useQuery<RiskAlert[]>({
    queryKey: ["risk", "alerts", user?.id ?? null, input ? JSON.stringify(input) : null],
    enabled: Boolean(accessToken && input),
    queryFn: async () => {
      const res = await apiFetch<{ alerts: RiskAlert[] }>("/api/v1/risk/alerts", {
        method: "POST",
        body: input!,
        authToken: accessToken!,
        schema: riskAlertsResponseSchema,
      });
      return res.alerts;
    },
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
  daily_pnl: z.number().nullish(),
  daily_return: z.number().nullish(),
  total_pnl: z.number().nullish(),
  total_return: z.number().nullish(),
  contributed_capital: z.number().nullish(),
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
const coverageTestSchema = z.looseObject({
  n: z.number(),
  breaches: z.number(),
  expected: z.number().nullish(),
  alpha: z.number().nullish(),
  lr_uc: z.number().nullish(),
  p_uc: z.number().nullish(),
  lr_ind: z.number().nullish(),
  p_ind: z.number().nullish(),
  lr_cc: z.number().nullish(),
  p_cc: z.number().nullish(),
  passed: z.boolean().nullish(),
});
export type CoverageTest = z.infer<typeof coverageTestSchema>;

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
  coverage_95: coverageTestSchema.nullish(),
  coverage_99: coverageTestSchema.nullish(),
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
export const newsSchema = z.looseObject({
  items: z.array(newsItemSchema),
  sources: z.array(sourceProvenanceSchema).nullish(),
});
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
  as_of: z.string().nullable().optional(),
  observations: z.number().nullable().optional(),
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
