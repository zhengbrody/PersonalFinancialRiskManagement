import { describe, expect, it } from "vitest";
import { planMetrics } from "./plan-snapshot";
import type { ScoreResponse } from "@/lib/schemas";

function score(overall: number, metrics: Record<string, unknown>): ScoreResponse {
  return { overall_score: overall, metrics } as unknown as ScoreResponse;
}

describe("planMetrics", () => {
  it("extracts overall_score + tracked metric fields", () => {
    const out = planMetrics(
      score(720, { annual_volatility: 0.18, sharpe_ratio: 0.9, top_holding_weight: 0.3 }),
    );
    expect(out.overall_score).toBe(720);
    expect(out.annual_volatility).toBe(0.18);
    expect(out.top_holding_weight).toBe(0.3);
  });

  it("drops non-finite and null metrics", () => {
    const out = planMetrics(
      score(700, { annual_volatility: NaN, sharpe_ratio: null, var_95_daily: Infinity }),
    );
    expect("annual_volatility" in out).toBe(false);
    expect("sharpe_ratio" in out).toBe(false);
    expect("var_95_daily" in out).toBe(false);
    expect(out.overall_score).toBe(700);
  });

  it("returns empty for a null score", () => {
    expect(planMetrics(null)).toEqual({});
  });
});
