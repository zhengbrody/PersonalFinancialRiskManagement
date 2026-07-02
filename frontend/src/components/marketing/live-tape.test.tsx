/**
 * LiveTape: real movers when the public endpoint answers (labelled "Live"),
 * explicitly-labelled illustrative fallback otherwise.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { LiveTape } from "./live-tape";

function mockJson(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

const row = (ticker: string, change_pct: number, close: number | null = 100) => ({
  ticker,
  name: ticker,
  change_pct,
  close,
  avg_volume_ratio: null,
});

const MOVERS = {
  data: {
    scan_date: "2026-07-01",
    sectors: [],
    top_gainers: [row("NVDA", 4.13, 172.4), row("AMD", 2.5), row("META", 1.9)],
    top_losers: [row("INTC", -3.2, 30.1), row("TSLA", -1.8)],
    unusual_volume: [],
  },
  error: null,
  meta: { request_id: "r" },
};

describe("LiveTape", () => {
  it("renders real movers with a Live label when the endpoint answers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockJson(MOVERS));
    renderWithQuery(<LiveTape />);

    expect(await screen.findByText(/Live · today's movers/i)).toBeInTheDocument();
    // Marquee doubles the list — each ticker appears twice.
    expect(screen.getAllByText("NVDA").length).toBe(2);
    expect(screen.getAllByText(/\+4\.13%/).length).toBe(2);
    expect(screen.getAllByText(/-3\.20%/).length).toBe(2);
    expect(screen.queryByText(/illustrative/i)).not.toBeInTheDocument();
  });

  it("falls back to the labelled illustrative tape when the feed is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({
        data: { scan_date: null, sectors: [], top_gainers: [], top_losers: [], unusual_volume: [] },
        error: null,
        meta: { request_id: "r" },
      }),
    );
    renderWithQuery(<LiveTape />);

    expect(await screen.findByText(/illustrative/i)).toBeInTheDocument();
    expect(screen.getAllByText("NVDA").length).toBe(2); // fallback set still scrolls
    expect(screen.queryByText(/Live · today's movers/i)).not.toBeInTheDocument();
  });

  it("shows the illustrative label while loading (prerender state)", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    renderWithQuery(<LiveTape />);
    expect(screen.getByText(/illustrative/i)).toBeInTheDocument();
  });

  it("dedupes tickers and skips rows without a change figure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({
        data: {
          scan_date: "2026-07-01",
          sectors: [],
          top_gainers: [row("NVDA", 4.1), row("NVDA", 4.1), row("XXXX", null as unknown as number), row("A", 1), row("B", 1)],
          top_losers: [row("C", -1)],
          unusual_volume: [],
        },
        error: null,
        meta: { request_id: "r" },
      }),
    );
    renderWithQuery(<LiveTape />);
    await screen.findByText(/Live · today's movers/i);
    expect(screen.getAllByText("NVDA").length).toBe(2); // deduped, then doubled
    expect(screen.queryByText("XXXX")).not.toBeInTheDocument(); // no change_pct → skipped
  });
});
