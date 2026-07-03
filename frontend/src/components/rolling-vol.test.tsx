import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RollingVol } from "./rolling-vol";
import type { RollingVolatility } from "@/lib/queries";

function series(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    date: `2026-06-${String(i + 1).padStart(2, "0")}`,
    portfolio: 0.15 + i * 0.001,
    benchmark: 0.12,
  }));
}

function data(overrides: Partial<RollingVolatility> = {}): RollingVolatility {
  return {
    window_days: 21,
    series: series(10),
    current: 0.204,
    median: 0.155,
    state: "elevated",
    benchmark_ticker: "SPY",
    ...overrides,
  } as RollingVolatility;
}

describe("RollingVol", () => {
  it("renders the state chip + current-vs-median line + honest caption", () => {
    render(<RollingVol data={data()} />);
    expect(screen.getByText("Elevated")).toBeInTheDocument();
    expect(screen.getByText(/current 20\.4% vs 15\.5% median/i)).toBeInTheDocument();
    // methodology labelling: rolling window is leverage-adjusted, SPY is not,
    // and the EWMA headline is a different estimator.
    expect(screen.getByText(/SPY shown unadjusted/i)).toBeInTheDocument();
    expect(screen.getByText(/EWMA estimator/i)).toBeInTheDocument();
  });

  it("calm state renders the calm chip", () => {
    render(<RollingVol data={data({ state: "calm" })} />);
    expect(screen.getByText("Calm")).toBeInTheDocument();
  });

  it("renders nothing for a sub-2-point series", () => {
    const { container } = render(<RollingVol data={data({ series: series(1) })} />);
    expect(container.firstChild).toBeNull();
  });
});
