import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  DeskStatStrip,
  MetricsDeskStrip,
  ReportDeskStrip,
} from "./desk-stat-strip";
import type { RiskReport } from "@/lib/queries";
import type { PortfolioMetrics } from "@/lib/schemas";

const baseReport = {
  annual_return: 0.08,
  annual_volatility: 0.18,
  sharpe_ratio: 0.9,
  max_drawdown: -0.22,
  var_95: 0.021,
  var_99: 0.03,
  cvar_95: 0.028,
  risk_free_rate: 0.04,
  total_value: 120_000,
  net_equity: 60_000,
  // PER-HOLDING beta map (the real production shape) — the strip must NOT
  // read this; portfolio β comes from the SPY factor-regression row below.
  betas: { BND: 0.05, QQQ: 1.3 },
  factor_betas: [{ factor: "SPY", beta: 1.2, r_squared: 0.9, t_stat: 40, p_value: 0 }],
  component_var_pct: [],
  component_return: [],
  stress_loss: null,
  stress_market_shock: null,
  stress_asset_losses: [],
  macro_betas: {},
  liquidity: [],
  drawdown_stats: null,
  data_quality_notes: [],
  rolling_volatility: {
    window_days: 21,
    series: [{ date: "2026-06-30", portfolio: 0.2, benchmark: null }],
    current: 0.2,
    median: 0.19,
    state: "normal" as const,
    benchmark_ticker: null,
  },
} as unknown as RiskReport;

describe("ReportDeskStrip", () => {
  it("renders exposure-first desk items with dollar-beta and leverage", () => {
    render(<ReportDeskStrip report={baseReport} />);
    const strip = screen.getByTestId("desk-stat-strip");
    expect(strip).toHaveTextContent("gross $120,000");
    expect(strip).toHaveTextContent("net $60,000");
    expect(strip).toHaveTextContent("lev 2.00×");
    // Portfolio β from the SPY factor-regression row — NOT the per-holding
    // betas map (whose first entry here is BND 0.05).
    expect(strip).toHaveTextContent("β 1.20");
    expect(strip).not.toHaveTextContent("0.05");
    // β-adjusted exposure = 1.2 × equity (120k gross, no cash)
    expect(strip).toHaveTextContent("β-adj exp $144,000");
    // 21-day Monte-Carlo horizon is labelled, not implied daily.
    expect(strip).toHaveTextContent("var95 21d 2.1%");
    expect(strip).toHaveTextContent("cvar95 21d 2.8%");
    expect(strip).toHaveTextContent("as of 2026-06-30");
  });

  it("multiplies dollar-beta by the EQUITY book (gross minus cash)", () => {
    const withCash = { ...baseReport, cash_balance: 20_000 } as unknown as RiskReport;
    render(<ReportDeskStrip report={withCash} />);
    // 1.2 × (120k − 20k cash) — cash carries no market beta.
    expect(screen.getByTestId("desk-stat-strip")).toHaveTextContent("β-adj exp $120,000");
  });

  it("degrades cell-by-cell: null fields disappear instead of rendering junk", () => {
    const sparse = {
      ...baseReport,
      total_value: null,
      net_equity: null,
      betas: {},
      factor_betas: [],
      rolling_volatility: null,
    } as unknown as RiskReport;
    render(<ReportDeskStrip report={sparse} />);
    const strip = screen.getByTestId("desk-stat-strip");
    expect(strip).not.toHaveTextContent("gross");
    expect(strip).not.toHaveTextContent("β-adj");
    expect(strip).not.toHaveTextContent("as of");
    expect(strip).toHaveTextContent("vol 18.0%"); // survivors still show
  });

  it("hides LEV for an unlevered book (matches the dashboard strip rule)", () => {
    const unlevered = { ...baseReport, net_equity: 120_000 } as unknown as RiskReport;
    render(<ReportDeskStrip report={unlevered} />);
    expect(screen.getByTestId("desk-stat-strip")).not.toHaveTextContent("lev");
  });
});

describe("MetricsDeskStrip", () => {
  const metrics = {
    annual_return: 0.1,
    annual_volatility: 0.14,
    sharpe_ratio: 1.1,
    max_drawdown: -0.12,
    var_95_daily: 0.015,
    cvar_95_daily: 0.02,
    beta_to_benchmark: 0.8,
    total_value: 50_000,
    net_equity: 50_000,
    leverage: 1.0,
  } as unknown as PortfolioMetrics;

  it("hides LEV at 1.0 and shows β-adjusted exposure off NET equity", () => {
    render(<MetricsDeskStrip metrics={metrics} />);
    const strip = screen.getByTestId("desk-stat-strip");
    expect(strip).not.toHaveTextContent("lev");
    expect(strip).toHaveTextContent("β-adj exp $40,000"); // 0.8 × 50k net
    // The score endpoint's VaR is the 1-DAY figure — labelled as such.
    expect(strip).toHaveTextContent("var95 1d 1.5%");
  });

  it("shows LEV with a warn tone once levered", () => {
    render(
      <MetricsDeskStrip metrics={{ ...metrics, leverage: 1.8 } as unknown as PortfolioMetrics} />,
    );
    expect(screen.getByTestId("desk-stat-strip")).toHaveTextContent("lev 1.80×");
  });
});

describe("DeskStatStrip", () => {
  it("renders nothing when every item is empty", () => {
    const { container } = render(<DeskStatStrip items={[{ label: "x", value: "—" }]} />);
    expect(container.firstChild).toBeNull();
  });
});
