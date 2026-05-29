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

import type { components } from "./api-types";

// ── request types (single source of truth: generated) ─────────────
export type Holding = components["schemas"]["HoldingIn"];
export type ScoreRequest = components["schemas"]["ScoreRequest"];
export type ScoreFromActiveRequest = components["schemas"]["ScoreFromActiveRequest"];

// ── response types (hand-mirrored — see file header) ──────────────
export type DimensionScore = {
  name: string;
  score: number;
  status: string;
  detail: string;
};

export type PortfolioMetrics = {
  annual_return: number | null;
  annual_volatility: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  var_95_daily: number | null;
  cvar_95_daily: number | null;
  beta_to_benchmark: number | null;
  total_value: number | null;
  cash_weight: number | null;
  data_coverage: number | null;
  observations: number | null;
  data_quality_notes: string[];
};

export type ScoreResponse = {
  overall_score: number;
  risk_preference: number;
  risk_target: Record<string, unknown>;
  metrics: PortfolioMetrics;
  dimensions: Record<string, DimensionScore>;
};
