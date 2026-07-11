/**
 * DataProvenance footer contract.
 *
 * Asserts the price-source line:
 *   * with per-ticker provenance → source counts + fallback label.
 *   * with no fallback → "Price source: Massive".
 *   * absent priceProvenance → existing behaviour unchanged (no crash).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataProvenance } from "./data-provenance";

describe("DataProvenance price-source line", () => {
  it("renders source counts + missing list when per-ticker provenance is present", () => {
    render(
      <DataProvenance
        source="Computed from market history"
        priceProvenance={{
          primary: "massive",
          fallback: "yfinance",
          by_ticker: { SPY: "massive", BND: "yfinance" },
          yfinance_fallback_used: ["BND"],
          massive_fallback_used: ["SPY"],
          missing: ["ABC", "DEF"],
          trading_days: 252,
        }}
      />,
    );
    expect(screen.getByText(/Price sources: Massive \(1\) · Yahoo fallback \(1\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Historical coverage: 252 trading days/i)).toBeInTheDocument();
    expect(screen.getByText(/Missing: ABC, DEF/)).toBeInTheDocument();
  });

  it("renders plain Massive source when no fallback details are present", () => {
    render(
      <DataProvenance
        priceProvenance={{
          primary: "massive",
          fallback: "yfinance",
          massive_fallback_used: [],
          missing: [],
          trading_days: null,
        }}
      />,
    );
    expect(screen.getByText("Price source: Massive")).toBeInTheDocument();
    expect(screen.queryByText(/Yahoo fallback/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Missing:/)).not.toBeInTheDocument();
  });

  it("renders unchanged with no priceProvenance prop", () => {
    render(<DataProvenance source="Computed from market history" coverage={0.9} />);
    expect(screen.getByText(/Computed from market history/)).toBeInTheDocument();
    expect(screen.queryByText(/Price source:/)).not.toBeInTheDocument();
  });

  it("shows the methodology version + a link when scoreVersion is passed", () => {
    render(<DataProvenance scoreVersion="mindmarket-score-v1.0.0" />);
    expect(screen.getByText(/Methodology mindmarket-score-v1\.0\.0/)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /how the score is calculated/i });
    expect(link).toHaveAttribute("href", "/methodology/health-score");
  });

  it("omits the methodology line when scoreVersion is absent", () => {
    render(<DataProvenance source="x" />);
    expect(screen.queryByText(/Methodology/)).not.toBeInTheDocument();
  });
});
