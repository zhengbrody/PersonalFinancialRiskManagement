/**
 * VarBacktest: renders the breach-vs-expected insight + stats; renders nothing
 * on too-short / missing data (fail-soft).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { VarBacktest } from "./var-backtest";
import type { VarBacktest as VB } from "@/lib/queries";

function base(over: Partial<VB> = {}): VB {
  return {
    n_days: 252,
    mean_daily: 0.0005,
    vol_daily: 0.012,
    var_95: 0.019,
    var_99: 0.027,
    hist_var_95: 0.02,
    hist_var_99: 0.03,
    breaches_95: 20,
    expected_95: 12.6,
    breaches_99: 5,
    expected_99: 2.5,
    worst_day: 0.06,
    histogram: [
      { x: -0.03, count: 3 },
      { x: 0.0, count: 200 },
      { x: 0.03, count: 49 },
    ],
    ...over,
  };
}

describe("VarBacktest", () => {
  it("renders the breach insight with a fat-tails read when breaches exceed expected", () => {
    render(<VarBacktest data={base()} loading={false} />);
    expect(screen.getByText(/does your VaR hold up/i)).toBeInTheDocument();
    expect(screen.getByText(/fatter tails/i)).toBeInTheDocument();
    // 95% VaR shown as a percentage.
    expect(screen.getByText("1.9%")).toBeInTheDocument();
  });

  it("shows PASS/FAIL reliability badges with a plain-English tooltip", () => {
    const cov = (passed: boolean, p_cc: number) => ({
      n: 252,
      breaches: 12,
      expected: 12.6,
      alpha: 0.05,
      lr_uc: 0.02,
      p_uc: 0.9,
      lr_ind: passed ? 0.1 : 30,
      p_ind: passed ? 0.75 : 0.00001,
      lr_cc: passed ? 0.12 : 30.02,
      p_cc,
      passed,
    });
    render(
      <VarBacktest
        data={base({ coverage_95: cov(true, 0.94), coverage_99: cov(false, 0.001) })}
        loading={false}
      />,
    );
    const strip = screen.getByTestId("var-reliability");
    expect(strip).toHaveTextContent("95% PASS");
    expect(strip).toHaveTextContent("99% FAIL");
    expect(strip).toHaveTextContent("p=0.94");
    // Plain-English tooltip on the badge.
    expect(screen.getByTitle(/nor the joint count\+clustering test rejects/i)).toBeInTheDocument();
    expect(screen.getByTitle(/Treat this VaR level with caution/i)).toBeInTheDocument();
  });

  it("omits the reliability strip when coverage fields are absent (old backend)", () => {
    render(<VarBacktest data={base()} loading={false} />);
    expect(screen.queryByTestId("var-reliability")).not.toBeInTheDocument();
  });

  it("renders nothing when the window is too short", () => {
    const { container } = render(<VarBacktest data={base({ n_days: 20 })} loading={false} />);
    expect(container.firstChild).toBeNull();
  });
});
