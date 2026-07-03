import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskFingerprint, fingerprintAxes } from "./risk-fingerprint";
import type { RiskReport } from "@/lib/queries";

function report(overrides: Record<string, unknown> = {}): RiskReport {
  return {
    annual_return: 0.08,
    annual_volatility: 0.2,
    sharpe_ratio: 0.8,
    max_drawdown: -0.25,
    var_95: 0.02,
    var_99: 0.03,
    cvar_95: 0.03,
    risk_free_rate: 0.04,
    // Per-holding beta map (production shape) — must be IGNORED by the radar.
    betas: { BND: 0.05 },
    factor_betas: [{ factor: "SPY", beta: 1.0, r_squared: 0.9, t_stat: 40, p_value: 0 }],
    component_var_pct: [],
    component_return: [],
    stress_loss: null,
    stress_market_shock: null,
    stress_asset_losses: [],
    macro_betas: {},
    liquidity: [],
    drawdown_stats: null,
    data_quality_notes: [],
    concentration: { num_holdings: 5, hhi: 0.275 },
    ...overrides,
  } as unknown as RiskReport;
}

describe("fingerprintAxes (pure, deterministic)", () => {
  it("normalizes against the documented bands", () => {
    const axes = Object.fromEntries(fingerprintAxes(report()).map((a) => [a.axis, a.value]));
    expect(axes["Market beta"]).toBe(5.0); // β 1.0 / 2.0 band
    expect(axes["Volatility"]).toBe(5.0); // 20% / 40% band
    expect(axes["Concentration"]).toBe(5.0); // (0.275-0.05)/0.45
    expect(axes["Drawdown"]).toBe(5.0); // 25% / 50%
    expect(axes["Tail risk"]).toBe(5.0); // 3% / 6%
  });

  it("clamps at 10 and omits null axes", () => {
    const axes = fingerprintAxes(
      report({ annual_volatility: 0.9, cvar_95: null, concentration: null }),
    );
    const vol = axes.find((a) => a.axis === "Volatility");
    expect(vol?.value).toBe(10);
    expect(axes.some((a) => a.axis === "Tail risk")).toBe(false);
    expect(axes.some((a) => a.axis === "Concentration")).toBe(false);
  });

  it("returns [] below 3 usable axes (radar suppressed)", () => {
    const axes = fingerprintAxes(
      report({
        factor_betas: [],
        annual_volatility: null,
        cvar_95: null,
        concentration: null,
      }),
    );
    expect(axes).toEqual([]);
  });

  it("uses the SPY factor-regression beta, never a holding's beta", () => {
    // Only per-holding betas available (no SPY factor row) → no beta axis.
    const axes = fingerprintAxes(report({ factor_betas: [] }));
    expect(axes.some((a) => a.axis === "Market beta")).toBe(false);
  });
});

describe("RiskFingerprint", () => {
  it("renders the axis readout list + not-a-score caption", () => {
    render(<RiskFingerprint report={report()} />);
    expect(screen.getByText("Risk fingerprint")).toBeInTheDocument();
    expect(screen.getByText(/Market beta: 5\.0/)).toBeInTheDocument();
    expect(screen.getByText(/educational scaling, not a score/i)).toBeInTheDocument();
  });

  it("renders nothing when under 3 axes", () => {
    const { container } = render(
      <RiskFingerprint
        report={report({
          factor_betas: [],
          annual_volatility: null,
          cvar_95: null,
          concentration: null,
        })}
      />,
    );
    expect(container.firstChild).toBeNull();
  });
});
