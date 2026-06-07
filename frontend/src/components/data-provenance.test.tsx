/**
 * DataProvenance footer contract.
 *
 * Asserts the price-source line:
 *   * with a Massive fallback → "Massive fallback" text + the missing list.
 *   * with no fallback → "Price source: yfinance" and NO "Massive" text.
 *   * absent priceProvenance → existing behaviour unchanged (no crash).
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataProvenance } from "./data-provenance";

describe("DataProvenance price-source line", () => {
  it("renders Massive fallback + missing list when fallback was used", () => {
    render(
      <DataProvenance
        source="Computed from yfinance history"
        priceProvenance={{
          primary: "yfinance",
          fallback: "Massive",
          massive_fallback_used: ["XYZ"],
          missing: ["ABC", "DEF"],
          trading_days: 252,
        }}
      />,
    );
    expect(screen.getByText(/Massive fallback/i)).toBeInTheDocument();
    expect(screen.getByText(/\(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Historical coverage: 252 trading days/i)).toBeInTheDocument();
    expect(screen.getByText(/Missing: ABC, DEF/)).toBeInTheDocument();
  });

  it("renders plain yfinance source and NO Massive text when no fallback", () => {
    render(
      <DataProvenance
        priceProvenance={{
          primary: "yfinance",
          fallback: "massive",
          massive_fallback_used: [],
          missing: [],
          trading_days: null,
        }}
      />,
    );
    expect(screen.getByText("Price source: yfinance")).toBeInTheDocument();
    expect(screen.queryByText(/Massive/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Missing:/)).not.toBeInTheDocument();
  });

  it("renders unchanged with no priceProvenance prop", () => {
    render(<DataProvenance source="Computed from yfinance history" coverage={0.9} />);
    expect(screen.getByText(/Computed from yfinance history/)).toBeInTheDocument();
    expect(screen.queryByText(/Price source:/)).not.toBeInTheDocument();
  });
});
