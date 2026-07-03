import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DiversificationCard } from "./diversification-card";
import type { Correlation } from "@/lib/queries";

function corr(overrides: Partial<Correlation> = {}): Correlation {
  return {
    tickers: ["SPY", "QQQ", "BND"],
    matrix: [
      [1, 0.9, 0.2],
      [0.9, 1, 0.1],
      [0.2, 0.1, 1],
    ],
    avg_pairwise: 0.4,
    top_pair: { a: "SPY", b: "QQQ", rho: 0.9 },
    best_diversifier: { ticker: "BND", avg_rho: 0.15 },
    diversification_ratio: 1.5,
    truncated: false,
    total_tickers: 3,
    ...overrides,
  } as Correlation;
}

describe("DiversificationCard", () => {
  it("renders the desk insights: avg ρ, DR, top pair, best diversifier", () => {
    render(<DiversificationCard correlation={corr()} />);
    expect(screen.getByText("0.40")).toBeInTheDocument();
    expect(screen.getByText("1.50×")).toBeInTheDocument();
    expect(screen.getByText(/ρ 0\.90/)).toBeInTheDocument();
    expect(screen.getByText(/avg ρ 0\.15/)).toBeInTheDocument();
    // DR 1.5 → cutting ~33% of standalone risk
    expect(screen.getByText(/cutting ~33% of the risk/i)).toBeInTheDocument();
    // learn deep-link into the diversification guide
    expect(
      screen.getByRole("link", { name: /learn what this means/i }),
    ).toHaveAttribute("href", "/learn/diversification-correlation");
  });

  it.each([
    [0.8, /move largely as one block/i],
    [0.5, /moderate co-movement/i],
    [0.2, /meaningful diversification/i],
  ])("avg ρ %s picks the matching deterministic takeaway", (avg, phrase) => {
    render(<DiversificationCard correlation={corr({ avg_pairwise: avg as number })} />);
    expect(screen.getByText(phrase)).toBeInTheDocument();
  });
});
