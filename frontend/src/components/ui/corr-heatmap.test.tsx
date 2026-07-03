import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CorrHeatmap } from "./corr-heatmap";

const TICKERS = ["SPY", "QQQ", "BND"];
const MATRIX: (number | null)[][] = [
  [1.0, 0.9, null],
  [0.9, 1.0, 0.1],
  [null, 0.1, 1.0],
];

describe("CorrHeatmap", () => {
  it("renders cells with hover titles and em-dash for missing pairs", () => {
    const { container } = render(<CorrHeatmap tickers={TICKERS} matrix={MATRIX} />);
    expect(
      container.querySelector('[title="SPY × QQQ · ρ = 0.90"]'),
    ).toBeTruthy();
    // null pair renders an em dash, no title
    expect(screen.getAllByText("—").length).toBe(2); // symmetric pair
    // diagonal shows 1.0 without a tooltip
    expect(screen.getAllByText("1.0").length).toBe(3);
  });

  it("notes the top-N cut when the universe is larger than the display", () => {
    const many = Array.from({ length: 20 }, (_, i) => `T${i.toString().padStart(2, "0")}`);
    const m = many.map((_, i) => many.map((_, j) => (i === j ? 1 : 0.5)));
    render(<CorrHeatmap tickers={many} matrix={m} totalTickers={31} />);
    expect(screen.getByText(/Showing the top 14 of 31 holdings/i)).toBeInTheDocument();
  });

  it("renders nothing for a single ticker", () => {
    const { container } = render(<CorrHeatmap tickers={["SPY"]} matrix={[[1]]} />);
    expect(container.firstChild).toBeNull();
  });
});
