/**
 * Build the compact `RiskExplainInput` from numbers the page ALREADY fetched.
 *
 * This is pure mapping — no computation, no new metrics. It exists so the AI
 * diagnosis literally cannot see anything beyond what the deterministic
 * endpoints already returned, and so the score page and the risk page produce a
 * consistent input shape.
 */

import type { RiskExplainInput } from "@/lib/queries";
import type { RiskReport, LastSnapshot } from "@/lib/queries";
import type { ScoreResponse } from "@/lib/schemas";
import { portfolioBeta } from "@/lib/portfolio-beta";

const _TOP_VAR = 6; // how many VaR contributors to ship
const _ILLIQUID_DAYS = 3; // surface holdings slower than this to exit

/** Health Score page / dashboard → explain input. */
export function explainInputFromScore(
  score: ScoreResponse,
  snapshot?: LastSnapshot["snapshot"] | null,
): RiskExplainInput {
  const m = score.metrics;
  const input: RiskExplainInput = {
    source: "score",
    overall_score: Math.round(score.overall_score),
    dimensions: Object.fromEntries(
      Object.entries(score.dimensions).map(([k, d]) => [
        k,
        { name: d.name, score: d.score, status: d.status },
      ]),
    ),
    metrics: {
      annual_return: m.annual_return,
      annual_volatility: m.annual_volatility,
      sharpe_ratio: m.sharpe_ratio,
      max_drawdown: m.max_drawdown,
      var_95_daily: m.var_95_daily,
      cvar_95_daily: m.cvar_95_daily,
      beta_to_benchmark: m.beta_to_benchmark,
      total_value: m.total_value,
      cash_weight: m.cash_weight,
    },
  };
  if (snapshot && snapshot.overall_score != null) {
    input.snapshot_delta = {
      as_of: snapshot.as_of ?? null,
      prev_overall_score: Math.round(snapshot.overall_score),
      prev_annual_volatility: snapshot.annual_volatility ?? null,
      prev_sharpe_ratio: snapshot.sharpe_ratio ?? null,
    };
  }
  return input;
}

/** Risk Report page → explain input (folds in the report-only context). */
export function explainInputFromReport(report: RiskReport): RiskExplainInput {
  return {
    source: "risk",
    metrics: {
      annual_return: report.annual_return,
      annual_volatility: report.annual_volatility,
      sharpe_ratio: report.sharpe_ratio,
      max_drawdown: report.max_drawdown,
      // report.var_95/cvar_95 are 21-DAY Monte-Carlo figures — feeding them
      // into the *_daily fields made the AI diagnosis narrate a month-scale
      // number as "Daily VaR". Omit rather than mislabel (fields optional).
      var_95_daily: null,
      cvar_95_daily: null,
      // Portfolio beta = the SPY factor-regression row; report.betas is the
      // PER-HOLDING beta map, whose "first entry" is an arbitrary holding.
      beta_to_benchmark: portfolioBeta(report),
    },
    top_component_var: [...report.component_var_pct]
      .sort((a, b) => b.pct - a.pct)
      .slice(0, _TOP_VAR)
      .map((c) => ({ ticker: c.ticker, pct: c.pct })),
    factor_betas: Object.fromEntries(
      report.factor_betas
        .filter((f) => f.beta != null)
        .map((f) => [f.factor, f.beta as number]),
    ),
    stress_loss: report.stress_loss,
    stress_market_shock: report.stress_market_shock,
    liquidity_outliers: report.liquidity
      .filter((l) => l.days_to_liquidate != null && l.days_to_liquidate >= _ILLIQUID_DAYS)
      .map((l) => ({ ticker: l.ticker, days_to_liquidate: l.days_to_liquidate })),
  };
}
