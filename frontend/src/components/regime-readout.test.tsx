import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RegimeReadout, type RegimeSummary } from "./regime-readout";

const BASE: RegimeSummary = {
  headline: "Market risk-state: Elevated",
  regime_state: "volatile",
  label: "Elevated",
  blurb: "Choppier, higher-volatility conditions look more likely.",
  confidence: 0.72,
  drivers: [
    { label: "3-month volatility", vs_normal: "above normal" },
    { label: "VIX level", vs_normal: "elevated" },
  ],
  vix: { current: 18.4, change: 0.6, level: "Elevated" },
  fear_greed: { score: 55, rating: "Greed" },
  curve: { status: "Normal", spread_3m_10y: 0.45, inverted: false },
  as_of: "2026-06-23",
  source: "model",
  model_version: "v1",
  caveat: "Risk-state only — not a price forecast, not investment advice, and it does not change your Health Score.",
  post_text: "Market risk-state: Elevated (72% confidence). VIX 18.4 (+0.6). Context, not advice. mindmarket.app/risk-today",
};

describe("RegimeReadout", () => {
  it("renders the headline, label+confidence, drivers, macro stats and caveat", () => {
    render(<RegimeReadout summary={BASE} />);
    expect(screen.getByText("Market risk-state: Elevated")).toBeInTheDocument();
    expect(screen.getByText(/Elevated · 72%/)).toBeInTheDocument();
    expect(screen.getByText("3-month volatility")).toBeInTheDocument();
    expect(screen.getByText("18.4")).toBeInTheDocument(); // VIX
    expect(screen.getByText("Greed")).toBeInTheDocument();
    expect(screen.getByText(/not investment advice/)).toBeInTheDocument();
    expect(screen.getByText(/model v1 · as of 2026-06-23/)).toBeInTheDocument();
  });

  it("degrades gracefully when the model is unavailable (no label/drivers)", () => {
    const down: RegimeSummary = {
      ...BASE,
      headline: "Market risk read temporarily unavailable",
      regime_state: null,
      label: null,
      blurb: null,
      confidence: null,
      drivers: [],
      source: "unavailable",
      model_version: null,
      as_of: null,
    };
    render(<RegimeReadout summary={down} />);
    expect(screen.getByText("Market risk read temporarily unavailable")).toBeInTheDocument();
    expect(screen.queryByText("What the model is weighing")).not.toBeInTheDocument();
    expect(screen.getByText(/market data unavailable/)).toBeInTheDocument();
  });
});
