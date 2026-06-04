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

  it("renders nothing when the window is too short", () => {
    const { container } = render(<VarBacktest data={base({ n_days: 20 })} loading={false} />);
    expect(container.firstChild).toBeNull();
  });
});
