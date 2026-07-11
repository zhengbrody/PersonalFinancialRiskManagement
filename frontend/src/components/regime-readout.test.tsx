import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RegimeReadout, type RegimeSummary } from "./regime-readout";

const BASE: RegimeSummary = {
  headline: "Elevated-risk probability: 58%",
  elevated_risk_probability: 0.58,
  probability_band: "Very high",
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
  model_version: "regime-v1.1.0",
  health_status: "healthy",
  degraded: false,
  degraded_reason: null,
  caveat:
    "Risk-state only — not a price forecast, not investment advice, and it does not change your Health Score.",
  post_text:
    "Elevated-risk probability 58% (Very high). VIX 18.4 (+0.6). Experimental probability signal — not a price or return forecast. Context, not advice. mindmarket.app/risk-today",
};

describe("RegimeReadout", () => {
  it("leads with the elevated-risk PROBABILITY + band, not the 4-class label", () => {
    render(<RegimeReadout summary={BASE} />);
    // Primary output = probability.
    expect(screen.getByText("Elevated-risk probability: 58%")).toBeInTheDocument();
    expect(screen.getByText("Very high")).toBeInTheDocument();
    expect(screen.getAllByText(/probability-ranking signal/).length).toBeGreaterThan(0);
    // The 4-class label appears only as SECONDARY context.
    expect(screen.getByText(/Secondary context/)).toBeInTheDocument();
    expect(screen.getByText(/does not beat a naive persistence baseline/)).toBeInTheDocument();
    // Method note (limitations) + model-card link.
    expect(screen.getAllByText(/predict prices or returns/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/persistence baseline/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /model card/i })).toHaveAttribute(
      "href",
      "/methodology/regime-model",
    );
    // Provenance carries model version + data as-of + drift check.
    expect(screen.getByText(/model regime-v1\.1\.0 · data as of 2026-06-23 · drift check: healthy/)).toBeInTheDocument();
    expect(screen.getByText("18.4")).toBeInTheDocument(); // VIX still shown
  });

  it("degrades to deterministic market context when the model is unavailable — NO probability", () => {
    const degraded: RegimeSummary = {
      ...BASE,
      headline: "Today's market snapshot",
      elevated_risk_probability: null,
      probability_band: null,
      degraded: true,
      degraded_reason: "model_drift",
    };
    render(<RegimeReadout summary={degraded} />);
    expect(screen.getByText("Today's market snapshot")).toBeInTheDocument();
    // No probability figure, no drivers.
    expect(screen.queryByText(/Elevated-risk probability:/)).not.toBeInTheDocument();
    expect(screen.queryByText("What the model is weighing")).not.toBeInTheDocument();
    // Explains the degrade + still shows the market data (VIX).
    expect(screen.getByText(/drifting from its training data/)).toBeInTheDocument();
    expect(screen.getByText("18.4")).toBeInTheDocument();
    // The method note (with limitations) is always present.
    expect(screen.getAllByText(/persistence baseline/i).length).toBeGreaterThan(0);
  });
});
