/**
 * Phase 5b — the data-coverage matrix card: grouped rows, core badges,
 * honest Unavailable + typed reasons (never fake values), source-tier
 * labelling (fallback/derived marked), hidden on error.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const coverageMock = vi.fn();
vi.mock("@/lib/queries", () => ({
  useResearchCoverage: () => coverageMock(),
}));

import { ResearchCoverageCard } from "./research-coverage";

const DATA = {
  ticker: "AAPL",
  as_of: "2026-07-14",
  fields: [
    {
      field: "price",
      source: "fmp",
      source_type: "primary",
      label: "FMP",
      group: "Price & history",
      as_of: "2026-07-14",
      coverage: 1.0,
      critical: true,
    },
    {
      field: "analyst_estimates",
      source: "yfinance",
      source_type: "secondary",
      label: "Yahoo Finance",
      group: "Analysts & earnings",
      coverage: 1.0,
      critical: false,
      fallback_used: true,
    },
  ],
  missing: [
    {
      field: "cashflow_statement_quarterly",
      source: "unavailable",
      source_type: "derived",
      group: "Financial statements",
      coverage: 0.0,
      critical: true,
      missing_reason: "unsupported",
    },
  ],
  data_confidence: {
    label: "medium",
    confidence: 0.6,
    overall_coverage: 0.66,
    critical_coverage: 0.66,
    conviction_cap: "low",
    directional_allowed: true,
    stale: false,
    fallback_used: true,
    sources: [],
    missing: [],
    reason_codes: [],
  },
};

beforeEach(() => {
  coverageMock.mockReturnValue({ data: DATA, isLoading: false, isError: false });
});

describe("ResearchCoverageCard", () => {
  it("renders grouped rows with core badges and honest source tiers", () => {
    render(<ResearchCoverageCard ticker="AAPL" />);
    expect(screen.getByText("Price & history")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getAllByText("core").length).toBe(2); // price + cashflow
    // fallback stays labelled a fallback — never dressed as primary
    expect(screen.getByText(/Yahoo Finance · fallback/)).toBeInTheDocument();
  });

  it("absent datasets say Unavailable with the typed reason — no fake values", () => {
    render(<ResearchCoverageCard ticker="AAPL" />);
    expect(
      screen.getByText(/Unavailable — not included in the current data plan/),
    ).toBeInTheDocument();
    expect(screen.queryByText("0.0")).not.toBeInTheDocument();
    expect(screen.queryByText("N/A")).not.toBeInTheDocument();
  });

  it("hides entirely on error and without a ticker", () => {
    coverageMock.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    const { container } = render(<ResearchCoverageCard ticker="AAPL" />);
    expect(container.innerHTML).toBe("");
    const { container: c2 } = render(<ResearchCoverageCard ticker={null} />);
    expect(c2.innerHTML).toBe("");
  });
});
