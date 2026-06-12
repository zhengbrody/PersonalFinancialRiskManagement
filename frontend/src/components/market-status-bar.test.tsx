/**
 * MarketStatusBar: terminal strip under the header.
 *   - renders session state + VIX/F&G/curve from the regime endpoint
 *   - renders NOTHING until regime data exists (fail-soft)
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const useMarketRegimeMock = vi.fn();
vi.mock("@/lib/queries", () => ({
  useMarketRegime: () => useMarketRegimeMock(),
}));

const isUsTradingHoursMock = vi.fn();
vi.mock("@/lib/market-hours", () => ({
  isUsTradingHours: () => isUsTradingHoursMock(),
}));

import { MarketStatusBar } from "./market-status-bar";

afterEach(() => vi.clearAllMocks());

const REGIME = {
  vix: { current: 14.2, change: -0.8, level: "calm" },
  fear_greed: { score: 62, rating: "Greed" },
  yield_curve: { status: "Normal", spread_3m_10y: 0.45, inverted: false },
};

describe("MarketStatusBar", () => {
  it("renders session + quotes from regime data", () => {
    isUsTradingHoursMock.mockReturnValue(true);
    useMarketRegimeMock.mockReturnValue({ data: REGIME });
    render(<MarketStatusBar />);

    expect(screen.getByText(/US market open/i)).toBeInTheDocument();
    expect(screen.getByText("14.2")).toBeInTheDocument();
    expect(screen.getByText("-0.8")).toBeInTheDocument(); // VIX delta
    expect(screen.getByText(/62 Greed/)).toBeInTheDocument();
    expect(screen.getByText(/Normal \(\+0\.45\)/)).toBeInTheDocument();
  });

  it("says closed outside trading hours", () => {
    isUsTradingHoursMock.mockReturnValue(false);
    useMarketRegimeMock.mockReturnValue({ data: REGIME });
    render(<MarketStatusBar />);
    expect(screen.getByText(/US market closed/i)).toBeInTheDocument();
  });

  it("renders nothing while regime data is missing", () => {
    isUsTradingHoursMock.mockReturnValue(true);
    useMarketRegimeMock.mockReturnValue({ data: undefined });
    const { container } = render(<MarketStatusBar />);
    expect(container.firstChild).toBeNull();
  });
});
