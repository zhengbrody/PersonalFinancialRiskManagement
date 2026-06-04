/**
 * MarketMovers: renders the sector heatmap + gainers/losers/unusual-volume from
 * the public /macro/movers endpoint (mocked).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { MarketMovers } from "./market-movers";

function mockJson(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

const MOVERS = {
  data: {
    scan_date: "2026-06-04",
    sectors: [{ sector: "Technology", ticker: "XLK", change_pct: 1.2, ytd_return: 0.18 }],
    top_gainers: [{ ticker: "NVDA", name: "NVIDIA", change_pct: 4.1, close: 120, avg_volume_ratio: 1.3 }],
    top_losers: [{ ticker: "INTC", name: "Intel", change_pct: -3.2, close: 30, avg_volume_ratio: 1.1 }],
    unusual_volume: [{ ticker: "TSLA", name: "Tesla", change_pct: 2.0, close: 250, avg_volume_ratio: 3.4 }],
  },
  error: null,
  meta: { request_id: "r" },
};

describe("MarketMovers", () => {
  it("renders sectors + movers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockJson(MOVERS));
    renderWithQuery(<MarketMovers />);

    expect(await screen.findByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("INTC")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("3.4× vol")).toBeInTheDocument();
  });

  it("shows fail-soft empties when data is missing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({
        data: { scan_date: null, sectors: [], top_gainers: [], top_losers: [], unusual_volume: [] },
        error: null,
        meta: {},
      }),
    );
    renderWithQuery(<MarketMovers />);
    expect(await screen.findByText(/sector data unavailable/i)).toBeInTheDocument();
  });
});
