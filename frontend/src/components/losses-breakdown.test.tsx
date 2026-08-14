/**
 * LossesBreakdown: shows each loss in BOTH % and $, distinguishes 1-day VaR/CVaR
 * from the 21-day VaR, and renders the margin-buffer status. Pure component.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LossesBreakdown } from "./losses-breakdown";
import type { LossBreakdown } from "@/lib/queries";
import type { FinancingResilience } from "@/lib/schemas";

const FINANCING: FinancingResilience = {
  status: "covered",
  gross_assets: 150000,
  net_equity: 100000,
  margin_loan: 50000,
  cash_balance: 0,
  cash_equivalent_value: 50000,
  liquid_resources: 50000,
  risk_asset_value: 100000,
  margin_coverage_ratio: 1,
  residual_margin: 0,
  gross_leverage: 1.5,
  post_offset_risk_leverage: 1,
  cash_equivalents: [
    { ticker: "SGOV", market_value: 50000, classification_source: "known_treasury_fund" },
  ],
  unpriced_holdings: 0,
  methodology_note: "Current-value liquidation estimate; not a broker guarantee.",
};

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

  it("separates gross leverage from cash-equivalent margin coverage", () => {
    render(
      <LossesBreakdown
        losses={LOSSES}
        financing={{
          status: "covered",
          gross_assets: 150000,
          net_equity: 100000,
          margin_loan: 50000,
          cash_balance: 0,
          cash_equivalent_value: 50000,
          liquid_resources: 50000,
          risk_asset_value: 100000,
          margin_coverage_ratio: 1,
          residual_margin: 0,
          gross_leverage: 1.5,
          post_offset_risk_leverage: 1,
          cash_equivalents: [
            { ticker: "SGOV", market_value: 50000, classification_source: "known_treasury_fund" },
          ],
          unpriced_holdings: 0,
          methodology_note: "Current-value liquidation estimate; not a broker guarantee.",
        }}
      />,
    );
    expect(screen.getByText(/100%/)).toBeInTheDocument();
    expect(screen.getByText("Post-offset risk leverage")).toBeInTheDocument();
    expect(screen.getByText("1.00×")).toBeInTheDocument();
    expect(screen.getByText(/not a broker guarantee/i)).toBeInTheDocument();
  });

  it("clamps the coverage display and names a self-classified offset", () => {
    render(
      <LossesBreakdown
        losses={LOSSES}
        financing={{
          ...FINANCING,
          margin_coverage_ratio: 2.5, // over-collateralised — must not read "250%"
          cash_equivalents: [
            { ticker: "TSLA", market_value: 500000, classification_source: "explicit" },
          ],
        }}
      />,
    );
    expect(screen.getByText(/100%/)).toBeInTheDocument();
    expect(screen.queryByText(/250%/)).not.toBeInTheDocument();
    // A user-classified offset must be labelled as self-attested, never shown
    // with the same authority as an auto-matched Treasury fund.
    expect(screen.getByText(/you classified as cash-like/i)).toBeInTheDocument();
    expect(screen.getByText(/TSLA/)).toBeInTheDocument();
  });

  it("uses friendly labels for every financing status", () => {
    render(
      <LossesBreakdown
        losses={LOSSES}
        financing={{ ...FINANCING, status: "uncovered", margin_coverage_ratio: 0 }}
      />,
    );
    expect(screen.getByText("Not covered")).toBeInTheDocument();
    expect(screen.queryByText("uncovered")).not.toBeInTheDocument();
  });

  it("renders nothing when losses is null", () => {
    const { container } = render(<LossesBreakdown losses={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when there are no losses and the book carries no margin", () => {
    // financing alone doesn't justify the card — its block only shows with a
    // loan, so this would otherwise be five empty "—" tiles.
    const { container } = render(
      <LossesBreakdown losses={null} financing={{ ...FINANCING, margin_loan: 0 }} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
