/**
 * MarketSeason panel contract.
 *
 * Asserts: current regime + confidence + sub-signals render; a regime
 * history ribbon appears; a partially-null payload still renders (no
 * crash); an error envelope shows a friendly notice.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { MarketSeason } from "./market-season";

function envelope(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, error: null, meta: { request_id: "r" } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MarketSeason", () => {
  it("renders the current regime, confidence and signals", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      envelope({
        current_regime: "Bullish",
        confidence: 0.72,
        regime_since_date: "2026-03-01",
        vix_regime: "Calm",
        trend_regime: "Uptrend",
        vol_regime: "Low Vol",
        history: [
          { date: "2026-01-02", regime: "Bearish" },
          { date: "2026-02-02", regime: "Transition" },
          { date: "2026-03-02", regime: "Bullish" },
        ],
      }),
    );

    renderWithQuery(<MarketSeason />);

    expect(await screen.findByText("Bullish")).toBeInTheDocument();
    expect(screen.getByText(/72% confidence/)).toBeInTheDocument();
    expect(screen.getByText(/since 2026-03-01/)).toBeInTheDocument();
    expect(screen.getByText("Uptrend")).toBeInTheDocument();
    // ribbon legend present
    expect(screen.getByText("Transition")).toBeInTheDocument();
  });

  it("renders without crashing on a fully-null payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      envelope({
        current_regime: null,
        confidence: null,
        regime_since_date: null,
        vix_regime: null,
        trend_regime: null,
        vol_regime: null,
        history: [],
      }),
    );

    renderWithQuery(<MarketSeason />);

    // Dash placeholders render for the unknown regime + signals (no crash).
    expect((await screen.findAllByText("—")).length).toBeGreaterThanOrEqual(1);
  });

  it("shows a friendly notice on an error envelope", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      envelope({ data: null }, 500),
    );

    renderWithQuery(<MarketSeason />);

    expect(
      await screen.findByText(/could not load the market regime/i),
    ).toBeInTheDocument();
  });
});
