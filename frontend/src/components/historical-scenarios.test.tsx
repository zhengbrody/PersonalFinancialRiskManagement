/**
 * HistoricalScenarios: renders one card per replayed crisis; renders nothing
 * when there are no usable episodes (fail-soft).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { HistoricalScenarios } from "./historical-scenarios";
import type { HistoricalScenarios as HS } from "@/lib/queries";

const DATA: HS = {
  scenarios: [
    {
      label: "COVID-19 crash",
      start: "2020-02-19",
      end: "2020-03-23",
      portfolio_return: -0.28,
      market_return: -0.34,
      max_drawdown: -0.3,
      coverage: 1.0,
      recovery_days: 120,
    },
    {
      label: "Global Financial Crisis",
      start: "2007-10-09",
      end: "2009-03-09",
      portfolio_return: -0.5,
      market_return: -0.55,
      max_drawdown: -0.56,
      coverage: 0.6,
      recovery_days: null, // not recovered within data
    },
  ],
};

describe("HistoricalScenarios", () => {
  it("renders an episode card per crisis with the portfolio return", () => {
    render(<HistoricalScenarios data={DATA} loading={false} />);
    expect(screen.getByText("If history repeated")).toBeInTheDocument();
    expect(screen.getByText("COVID-19 crash")).toBeInTheDocument();
    expect(screen.getByText("-28.0%")).toBeInTheDocument(); // portfolio return
    expect(screen.getByText("had not recovered")).toBeInTheDocument(); // GFC
    expect(screen.getByText(/60% of holdings traded then/i)).toBeInTheDocument();
  });

  it("renders nothing when there are no episodes", () => {
    const { container } = render(
      <HistoricalScenarios data={{ scenarios: [] }} loading={false} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
