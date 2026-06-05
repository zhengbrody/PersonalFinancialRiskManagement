/**
 * Frontend ↔ backend schema bridge.
 *
 * **Request types** are sourced from the OpenAPI-generated
 * `api-types.ts` so the contract can never drift. Re-run
 * `npm run gen:api` (backend must be reachable) to refresh.
 *
 * **Response types** are hand-mirrored below because the Phase-1 risk
 * router uses `response_model=None` (it returns a manually-wrapped
 * envelope, not a typed Pydantic model). When the backend declares
 * `response_model=ScoreResponse` in a later pass, this hand mirror
 * disappears and we re-export from `api-types.ts` like the requests.
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
});
export type PortfolioMetrics = z.infer<typeof portfolioMetricsSchema>;

export const scoreResponseSchema = z.looseObject({
  overall_score: z.number(),
  risk_preference: z.number(),
  risk_target: z.record(z.string(), z.unknown()),
  metrics: portfolioMetricsSchema,
  dimensions: z.record(z.string(), dimensionScoreSchema),
});
export type ScoreResponse = z.infer<typeof scoreResponseSchema>;
