import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { RiskSnapshot } from "./risk-snapshot";

describe("RiskSnapshot", () => {
  it("formats actual values without conflating volatility and returns", () => {
    render(
      <RiskSnapshot
        metrics={{
          net_equity: 54169.85,
          annual_volatility: 0.254,
          leverage: 1.35,
        }}
      />,
    );
    expect(screen.getByText("$54,170")).toBeInTheDocument();
    expect(screen.getByText("25.4%")).toBeInTheDocument();
    expect(screen.getByText("1.35×")).toBeInTheDocument();
    expect(screen.queryByText(/YTD/)).not.toBeInTheDocument();
  });
  it("does not substitute gross assets or invent zeroes for missing data", () => {
    render(
      <RiskSnapshot
        metrics={{
          total_value: 90000,
          annual_volatility: NaN,
          leverage: Infinity,
        }}
      />,
    );
    expect(screen.queryByText("$90,000")).not.toBeInTheDocument();
    expect(screen.getAllByText("Unavailable")).toHaveLength(3);
  });
  it("preserves valid zero values and negative equity", () => {
    render(
      <RiskSnapshot
        metrics={{ net_equity: -500, annual_volatility: 0, leverage: 0 }}
      />,
    );
    expect(screen.getByText("-$500")).toBeInTheDocument();
    expect(screen.getByText("0.0%")).toBeInTheDocument();
    expect(screen.getByText("0.00×")).toBeInTheDocument();
  });
});
