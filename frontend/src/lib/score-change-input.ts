import type { ScoreResponse } from "@/lib/schemas";

/** Build the one canonical request for the deterministic score-change engine.
 * Both Today and the History report use this exact payload, so the headline,
 * summary and top driver can never disagree because of client-side math. */
export function scoreChangeInput(
  score: ScoreResponse,
  window: "previous" | "7d" | "30d" = "previous",
): Record<string, unknown> {
  const dimensions: Record<string, number> = {};
  for (const [key, dimension] of Object.entries(score.dimensions ?? {})) {
    if (dimension && typeof dimension.score === "number") {
      dimensions[key] = dimension.score;
    }
  }
  const metrics = score.metrics;
  return {
    window,
    overall_score: score.overall_score,
    risk_preference: score.risk_preference,
    risk_preference_source: score.risk_preference_source,
    base_overall: score.base_overall ?? score.overall_score,
    dimensions,
    metrics: {
      annual_volatility: metrics.annual_volatility ?? null,
      sharpe_ratio: metrics.sharpe_ratio ?? null,
      max_drawdown: metrics.max_drawdown ?? null,
      var_95_daily: metrics.var_95_daily ?? null,
      beta_to_benchmark: metrics.beta_to_benchmark ?? null,
      net_equity: metrics.net_equity ?? null,
      leverage: metrics.leverage ?? null,
    },
    confidence: metrics.confidence ?? null,
    data_quality: metrics.data_quality ?? null,
    observations: metrics.observations ?? null,
    data_coverage: metrics.data_coverage ?? null,
    dropped_tickers: metrics.dropped_tickers ?? [],
    option_penalty: score.options?.penalty ?? null,
  };
}
