/**
 * LossesBreakdown: shows each loss in BOTH % and $, distinguishes 1-day VaR/CVaR
 * from the 21-day VaR, and renders the margin-buffer status. Pure component.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LossesBreakdown } from "./losses-breakdown";
import type { LossBreakdown } from "@/lib/queries";

const LOSSES: LossBreakdown = {
  basis_value: 100000,
  var_1d_95: { label: "1-day VaR (95%)", horizon: "1d", pct: 0.03, usd: 3000 },
  cvar_1d_95: { label: "1-day CVaR (95%)", horizon: "1d", pct: 0.045, usd: 4500 },
  var_21d_95: { label: "21-day VaR (95%)", horizon: "21d", pct: 0.18, usd: 18000 },
  stress: { label: "Stress (-10% market)", horizon: "scenario", pct: 0.12, usd: 12000 },
  current_drawdown: { label: "Current drawdown", horizon: "current", pct: 0.05, usd: 5000 },
  margin_buffer: {
    net_equity: 100000,
    margin_loan: 0,
    gross_assets: 100000,
    buffer_usd: 75000,
    buffer_pct: 0.75,
    status: "comfortable",
  },
};

describe("LossesBreakdown", () => {
  it("shows losses in BOTH percent and dollars", () => {
    render(<LossesBreakdown losses={LOSSES} />);
    // 1-day VaR: percent value + dollar magnitude
    expect(screen.getByText("3.0%")).toBeInTheDocument();
    expect(screen.getByText("$3,000")).toBeInTheDocument();
    // CVaR $
    expect(screen.getByText("$4,500")).toBeInTheDocument();
  });

  it("distinguishes 1-day VaR from the 21-day VaR", () => {
    render(<LossesBreakdown losses={LOSSES} />);
    expect(screen.getByText("1-day VaR (95%)")).toBeInTheDocument();
    expect(screen.getByText("21-day VaR (95%)")).toBeInTheDocument();
    expect(screen.getByText(/different horizons, not a discrepancy/)).toBeInTheDocument();
  });

  it("renders the margin-buffer status", () => {
    render(<LossesBreakdown losses={LOSSES} />);
    expect(screen.getByText("Margin buffer")).toBeInTheDocument();
    expect(screen.getByText("Comfortable")).toBeInTheDocument();
    expect(screen.getByText("$75,000")).toBeInTheDocument();
  });

  it("renders nothing when losses is null", () => {
    const { container } = render(<LossesBreakdown losses={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
