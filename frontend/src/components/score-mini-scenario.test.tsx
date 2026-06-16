import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ScoreMiniScenario } from "./score-mini-scenario";
import type { PortfolioMetrics } from "@/lib/schemas";

function metrics(over: Partial<PortfolioMetrics> = {}): PortfolioMetrics {
  return {
    annual_return: 0.1,
    annual_volatility: 0.2,
    sharpe_ratio: 1,
    max_drawdown: -0.3,
    var_95_daily: 0.02,
    cvar_95_daily: 0.03,
    beta_to_benchmark: 1.5,
    total_value: 100_000,
    net_equity: 100_000,
    cash_weight: 0,
    data_coverage: 1,
    observations: 252,
    data_quality_notes: [],
    ...over,
  } as PortfolioMetrics;
}

describe("ScoreMiniScenario", () => {
  it("computes a deterministic beta×shock loss (-10% default)", () => {
    render(<ScoreMiniScenario metrics={metrics()} />);
    // 100k × 1.5 × -10% = -$15,000
    expect(screen.getByText("-$15,000")).toBeInTheDocument();
    // 1-day VaR: 2% × 100k = -$2,000
    expect(screen.getByText("-$2,000")).toBeInTheDocument();
  });

  it("recomputes at -30%", () => {
    render(<ScoreMiniScenario metrics={metrics()} />);
    fireEvent.click(screen.getByRole("button", { name: "-30%" }));
    // 100k × 1.5 × -30% = -$45,000
    expect(screen.getByText("-$45,000")).toBeInTheDocument();
  });

  it("renders nothing without an equity base or beta", () => {
    const { container } = render(
      <ScoreMiniScenario metrics={metrics({ beta_to_benchmark: null })} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
