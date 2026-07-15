import type { ScoreResponse } from "@/lib/schemas";

/**
 * Extract the metric snapshot a risk plan stores (baseline / expected_impact)
 * and the review engine compares. Keys match the backend's tracked metric set
 * (plan_review.py); `overall_score` is top-level, the rest live under `metrics`.
 * Only finite numbers are included so the plan blob stays finite (the backend
 * also rejects NaN/Inf).
 */
export function planMetrics(score: ScoreResponse | null | undefined): Record<string, number> {
  if (!score) return {};
  const m = (score.metrics ?? {}) as Record<string, unknown>;
  const out: Record<string, number> = {};
  const put = (k: string, v: unknown) => {
    if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
  };
  put("overall_score", score.overall_score);
  put("annual_volatility", m.annual_volatility);
  put("sharpe_ratio", m.sharpe_ratio);
  put("max_drawdown", m.max_drawdown);
  put("var_95_daily", m.var_95_daily);
  put("cvar_95_daily", m.cvar_95_daily);
  put("beta_to_benchmark", m.beta_to_benchmark);
  put("top_holding_weight", m.top_holding_weight);
  return out;
}
