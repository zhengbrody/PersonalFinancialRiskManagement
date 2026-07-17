/**
 * Frontend ↔ backend schema bridge.
 *
 * **Request types** are sourced from the OpenAPI-generated
 * `api-types.ts` so the contract can never drift. Re-run
 * `npm run gen:api` (reads the committed `openapi.json` offline) to refresh.
 *
 * **Response types** are now ALSO typed in OpenAPI — backend routes declare
 * `response_model=Envelope[X]`, so `components["schemas"][...]` describes the
 * real payloads. The zod schemas below stay as the RUNTIME guard at the
 * network boundary (`apiFetch({ schema })`), with the TS type via `z.infer`.
 * `contract.ts` pins the hand-written zod shapes to the generated contract at
 * compile time, and the CI regen-diff gate fails on undocumented backend drift.
 * Schemas migrate onto the generated `Api*` types incrementally.
 */

import { z } from "zod";
import type { components } from "./api-types";

// ── request types (single source of truth: generated) ─────────────
export type Holding = components["schemas"]["HoldingIn"];
export type ScoreRequest = components["schemas"]["ScoreRequest"];
export type ScoreFromActiveRequest = components["schemas"]["ScoreFromActiveRequest"];

// ── response schemas (hand-mirrored — see file header) ────────────
//
// These are zod schemas, not bare types, so `apiFetch({ schema })` can
// validate the payload at the network boundary. The TS types are
// derived via `z.infer` so the type and the runtime guard can never
// drift apart. `looseObject` keeps unknown keys (forward-compatible
// with additive backend changes) while still requiring the declared
// fields to be present and correctly typed.

export const dimensionScoreSchema = z.looseObject({
  name: z.string(),
  score: z.number(),
  status: z.string(),
  detail: z.string(),
});
export type DimensionScore = z.infer<typeof dimensionScoreSchema>;

// Unified per-field source provenance (registry-backed). What DataSourceBadges
// + the "Data Sources Used" panel render across the app.
export const sourceProvenanceSchema = z.looseObject({
  field: z.string(),
  provider: z.string(),
  label: z.string().nullish(),
  role: z.string().nullish(), // primary | fallback | computed
  endpoint: z.string().nullish(),
  as_of: z.string().nullish(),
  freshness: z.string().nullish(),
  confidence: z.number().nullish(),
  cache_hit: z.boolean().nullish(),
  latency_ms: z.number().nullish(),
  fallback_used: z.boolean().nullish(),
  warning: z.string().nullish(),
});
export type SourceProvenance = z.infer<typeof sourceProvenanceSchema>;

// Price-source data quality. Optional/nullable so older backend
// responses (before this field shipped) still parse. Describes which
// source priced each holding and any gaps.
export const priceProvenanceSchema = z.looseObject({
  primary: z.string().nullish(),
  fallback: z.string().nullish(),
  by_ticker: z.record(z.string(), z.string()).nullish(),
  yfinance_fallback_used: z.array(z.string()).nullish(),
  massive_fallback_used: z.array(z.string()).nullish(),
  missing: z.array(z.string()).nullish(),
  trading_days: z.number().nullish(),
});
export type PriceProvenance = z.infer<typeof priceProvenanceSchema>;

export const portfolioMetricsSchema = z.looseObject({
  annual_return: z.number().nullable(),
  annual_volatility: z.number().nullable(),
  sharpe_ratio: z.number().nullable(),
  max_drawdown: z.number().nullable(),
  var_95_daily: z.number().nullable(),
  cvar_95_daily: z.number().nullable(),
  beta_to_benchmark: z.number().nullable(),
  total_value: z.number().nullable(),
  net_equity: z.number().nullable().optional(),
  cash_balance: z.number().nullable().optional(),
  margin_loan: z.number().nullable().optional(),
  contributed_capital: z.number().nullable().optional(),
  daily_pnl: z.number().nullable().optional(),
  daily_return: z.number().nullable().optional(),
  total_pnl: z.number().nullable().optional(),
  total_return: z.number().nullable().optional(),
  cash_weight: z.number().nullable(),
  data_coverage: z.number().nullable(),
  observations: z.number().nullable(),
  data_quality_notes: z.array(z.string()),
  // Margin/cash transparency. sharpe_ratio is the leverage-invariant ASSET-MIX
  // Sharpe; these expose the leverage cost separately (margin books only).
  leverage: z.number().nullish(),
  gross_annual_return: z.number().nullish(),
  margin_cost_annual: z.number().nullish(),
  // Deterministic input-health: data_quality ∈ [0,1] (worst-link of coverage /
  // observations / dropped holdings); confidence is its label. When not "high"
  // the score is stabilized toward neutral instead of collapsing.
  data_quality: z.number().nullish(),
  confidence: z.string().nullish(),
  dropped_tickers: z.array(z.string()).nullish(),
  // Drawdown from peak right now (0 = fresh high). Non-scoring context.
  current_drawdown: z.number().nullish(),
});
export type PortfolioMetrics = z.infer<typeof portfolioMetricsSchema>;

// How option holdings deterministically affect the Health Score. Present only
// when the active book has option contracts.
export const optionScoreImpactSchema = z.looseObject({
  contracts: z.number(),
  net_delta: z.number(),
  net_gamma: z.number(),
  net_theta: z.number(),
  net_vega: z.number(),
  option_notional: z.number(),
  short_collateral_estimate: z.number(),
  base_score: z.number(),
  penalty: z.number(),
  flags: z.array(
    z.looseObject({ code: z.string(), severity: z.string(), detail: z.string() }),
  ),
  penalty_breakdown: z.array(
    z.looseObject({ code: z.string(), severity: z.string(), points: z.number() }),
  ),
});
export type OptionScoreImpact = z.infer<typeof optionScoreImpactSchema>;

/** Concentration diagnostics over the invested equity book. Shared by the
 * score response and the risk report (re-exported from queries for the latter). */
export const concentrationSchema = z.looseObject({
  num_holdings: z.number(),
  top_holding_ticker: z.string().nullable().optional(),
  top_holding_weight: z.number().nullable().optional(),
  top5_weight: z.number().nullable().optional(),
  hhi: z.number().nullable().optional(),
  effective_holdings: z.number().nullable().optional(),
  sectors: z
    .array(z.looseObject({ sector: z.string(), weight: z.number() }))
    .optional()
    .default([]),
  top_sector: z.string().nullable().optional(),
  top_sector_weight: z.number().nullable().optional(),
});
export type Concentration = z.infer<typeof concentrationSchema>;

export const scoreDriverSchema = z.looseObject({
  key: z.string(),
  name: z.string(),
  score: z.number(),
  weight: z.number(),
  points_below_max: z.number(),
  detail: z.string().nullish(),
});
export type ScoreDriver = z.infer<typeof scoreDriverSchema>;

export const reasonCodeSchema = z.looseObject({
  code: z.string(),
  severity: z.string(),
  detail: z.string().nullish(),
});
export type ReasonCode = z.infer<typeof reasonCodeSchema>;

// ── unified data-confidence contract (backend schemas/confidence.py) ──
export const fieldProvenanceSchema = z.looseObject({
  field: z.string(),
  source: z.string(),
  source_type: z.enum(["primary", "secondary", "derived"]).nullish(),
  label: z.string().nullish(),
  as_of: z.string().nullish(),
  fetched_at: z.string().nullish(),
  stale: z.boolean().nullish(),
  coverage: z.number().nullish(),
  fallback_used: z.boolean().nullish(),
  critical: z.boolean().nullish(),
  missing_reason: z.string().nullish(),
  note: z.string().nullish(),
});
export type FieldProvenance = z.infer<typeof fieldProvenanceSchema>;

// Per-field cross-source agreement: BOTH sides' raw values are preserved so a
// disagreement can be shown without overwriting either source's number.
export const sourceObservationSchema = z.looseObject({
  source: z.string(),
  source_type: z.enum(["primary", "secondary", "derived"]).nullish(),
  value: z.number(),
  unit: z.string().nullish(),
  as_of: z.string().nullish(),
  fetched_at: z.string().nullish(),
});
export type SourceObservation = z.infer<typeof sourceObservationSchema>;

export const fieldAgreementSchema = z.looseObject({
  field: z.string(),
  status: z.enum([
    "exact",
    "within_tolerance",
    "disagreement",
    "incomparable",
    "only_one_source",
  ]),
  rel_tolerance: z.number().nullish(),
  observed_rel_diff: z.number().nullish(),
  observations: z.array(sourceObservationSchema).nullish(),
  note: z.string().nullish(),
});
export type FieldAgreement = z.infer<typeof fieldAgreementSchema>;

export const dataConfidenceSchema = z.looseObject({
  label: z.enum(["high", "medium", "low"]),
  confidence: z.number(),
  overall_coverage: z.number(),
  critical_coverage: z.number(),
  as_of: z.string().nullish(),
  fetched_at: z.string().nullish(),
  stale: z.boolean().nullish(),
  fallback_used: z.boolean().nullish(),
  cross_source_agreement: z.number().nullish(),
  conviction_cap: z.enum(["none", "low", "medium", "high"]).nullish(),
  directional_allowed: z.boolean().nullish(),
  sources: z.array(fieldProvenanceSchema).nullish(),
  missing: z.array(fieldProvenanceSchema).nullish(),
  reason_codes: z.array(reasonCodeSchema).nullish(),
  agreement_checks: z.array(fieldAgreementSchema).nullish(),
});
export type DataConfidence = z.infer<typeof dataConfidenceSchema>;

export const scoreResponseSchema = z.looseObject({
  overall_score: z.number(),
  risk_preference: z.number(),
  risk_target: z.record(z.string(), z.unknown()),
  metrics: portfolioMetricsSchema,
  dimensions: z.record(z.string(), dimensionScoreSchema),
  price_provenance: priceProvenanceSchema.nullish(),
  options: optionScoreImpactSchema.nullish(),
  // Top-name / top-5 / HHI / sector roll-up over the equity book (cheap; lets
  // the score page show "what's dragging it" without the full report).
  concentration: concentrationSchema.nullish(),
  // Deterministic explainability + stabilization. base_overall is the score
  // BEFORE confidence dampening (== overall_score at full data); drivers rank
  // dimensions by points-cost; reason_codes are the structured penalties.
  base_overall: z.number().nullish(),
  drivers: z.array(scoreDriverSchema).nullish(),
  reason_codes: z.array(reasonCodeSchema).nullish(),
  // Methodology version that produced this score (auditable; links the number
  // to the rules on /methodology/health-score).
  score_version: z.string().nullish(),
  // Unified data-confidence + provenance block (rendered by <DataConfidence>).
  data_confidence: dataConfidenceSchema.nullish(),
  analysis_mode: z.enum(["live_market", "provided_returns", "synthetic_demo"]).nullish(),
});
export type ScoreResponse = z.infer<typeof scoreResponseSchema>;
