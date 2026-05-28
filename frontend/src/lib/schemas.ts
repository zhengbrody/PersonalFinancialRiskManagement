/**
 * Mirror types for the backend's `/api/v1/risk/score` payload.
 *
 * Kept as plain TypeScript shapes (no runtime validation) — the
 * backend is the source of truth, the envelope is contract-tested
 * server-side, and we don't want a Zod round-trip on the hot path.
 *
 * If a field is added server-side, add it here and the typed `apiFetch`
 * call will pick it up at the next build.
 */

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

export type Holding = {
  ticker: string;
  market_value: number;
  asset_type?: "public_security" | "cash" | "crypto" | "real_estate";
};

export type ScoreRequest = {
  holdings: Holding[];
  risk_preference?: number;
  risk_free_rate?: number;
};
