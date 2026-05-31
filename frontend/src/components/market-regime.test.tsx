/**
 * MarketRegime panel contract.
 *
 * Asserts:
 *   * VIX / Fear & Greed / yield-curve tiles render from the API.
 *   * Inverted curve shows the "Inverted" badge.
 *   * A partially-null payload (dead VIX leg) still renders the other
 *     tiles — the whole panel never blanks on one dead upstream.
 *   * An error envelope surfaces a friendly notice.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { MarketRegime } from "./market-regime";

function mockJson(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

function regimeEnvelope(data: unknown, status = 200) {
  return mockJson({ data, error: null, meta: { request_id: "r" } }, { status });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MarketRegime", () => {
  it("renders VIX, Fear & Greed and yield-curve tiles", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      regimeEnvelope({
        vix: { current: 18.42, change: -0.031, level: "Calm" },
        fear_greed: { score: 62, rating: "Greed" },
        yield_curve: { status: "Normal", spread_3m_10y: 0.76, inverted: false },
      }),
    );

    renderWithQuery(<MarketRegime />);

    expect(await screen.findByText("18.42")).toBeInTheDocument();
    expect(screen.getByText("Calm")).toBeInTheDocument();
    expect(screen.getByText("62")).toBeInTheDocument();
    expect(screen.getByText("Greed")).toBeInTheDocument();
    expect(screen.getByText("+0.76%")).toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeInTheDocument();
  });

  it("flags an inverted curve", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      regimeEnvelope({
        vix: { current: 30.1, change: 0.08, level: "Stressed" },
        fear_greed: { score: 20, rating: "Extreme Fear" },
        yield_curve: { status: "Inverted", spread_3m_10y: -0.45, inverted: true },
      }),
    );

    renderWithQuery(<MarketRegime />);

    // "Inverted" shows in BOTH the status sub-text and the badge.
    expect((await screen.findAllByText("Inverted")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("-0.45%")).toBeInTheDocument();
  });

  it("renders surviving tiles when one leg is null (dead upstream)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      regimeEnvelope({
        vix: { current: null, change: null, level: null },
        fear_greed: { score: 55, rating: "Neutral" },
        yield_curve: { status: "Normal", spread_3m_10y: 0.5, inverted: false },
      }),
    );

    renderWithQuery(<MarketRegime />);

    // F&G still rendered…
    expect(await screen.findByText("55")).toBeInTheDocument();
    expect(screen.getByText("Neutral")).toBeInTheDocument();
    // …while the dead VIX leg shows dashes (value + level), not a crash.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });

  it("shows a friendly notice on an error envelope", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson(
        {
          data: null,
          error: { code: "server_error", message: "down" },
          meta: { request_id: "r" },
        },
        { status: 500 },
      ),
    );

    renderWithQuery(<MarketRegime />);

    expect(
      await screen.findByText(/could not load market-regime data/i),
    ).toBeInTheDocument();
  });
});
