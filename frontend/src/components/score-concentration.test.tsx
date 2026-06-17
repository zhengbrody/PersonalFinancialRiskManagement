import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoreConcentration } from "./score-concentration";
import type { Concentration } from "@/lib/schemas";

const conc = (over: Partial<Concentration>): Concentration =>
  ({ num_holdings: 5, sectors: [], ...over }) as Concentration;

describe("ScoreConcentration", () => {
  it("renders the KPIs and flags a dominant single name (>25%)", () => {
    render(
      <ScoreConcentration
        concentration={conc({
          top_holding_ticker: "NVDA",
          top_holding_weight: 0.42,
          top5_weight: 0.9,
          effective_holdings: 2.3,
          top_sector: "Information Technology",
          top_sector_weight: 0.6,
        })}
      />,
    );
    expect(screen.getByText(/Concentration/i)).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    // amber callout names the concentrated holding + sector
    expect(screen.getByText(/NVDA is 42% of your book/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Full sector \+ liquidity breakdown/i })).toHaveAttribute(
      "href",
      "/risk",
    );
  });

  it("no amber flag for a diversified book; renders nothing without data", () => {
    const { rerender, container } = render(
      <ScoreConcentration
        concentration={conc({ top_holding_ticker: "SPY", top_holding_weight: 0.12, top5_weight: 0.5 })}
      />,
    );
    expect(screen.queryByText(/of your book — a shock/i)).not.toBeInTheDocument();

    rerender(<ScoreConcentration concentration={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
