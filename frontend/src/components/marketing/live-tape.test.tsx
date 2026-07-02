/**
 * LiveTape: real movers when the public endpoint answers (labelled "Live"),
 * explicitly-labelled illustrative fallback otherwise. Sparse feeds are padded
 * by repetition so the marquee always fills wide viewports; the label only
 * says "today" when the scan is from today's ET session.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { LiveTape, etDateString } from "./live-tape";

function mockJson(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

const row = (ticker: string, change_pct: number | null, close: number | null = 100) => ({
  ticker,
  name: ticker,
  change_pct,
  close,
  avg_volume_ratio: null,
});

const G = ["NVDA", "AMD", "META", "AVGO", "AMZN", "MSFT"];
const L = ["INTC", "TSLA", "NKE", "BA", "PFE", "KO"];

function movers(scan_date: string | null, gainers = G.map((t) => row(t, 2.5)), losers = L.map((t) => row(t, -1.5))) {
  return {
    data: { scan_date, sectors: [], top_gainers: gainers, top_losers: losers, unusual_volume: [] },
    error: null,
    meta: { request_id: "r" },
  };
}

describe("LiveTape", () => {
  it("renders today's movers with a Live label when the scan is from today (ET)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson(movers(etDateString(), [row("NVDA", 4.13, 172.4), ...G.slice(1).map((t) => row(t, 2.5))])),
    );
    renderWithQuery(<LiveTape />);

    expect(await screen.findByText(/Live · today's movers/i)).toBeInTheDocument();
    // 12 items fill a half exactly — marquee doubles it, so each ticker ×2.
    expect(screen.getAllByText("NVDA").length).toBe(2);
    expect(screen.getAllByText(/\+4\.13%/).length).toBe(2);
    expect(screen.getAllByText(/-1\.50%/).length).toBe(12);
    expect(screen.queryByText(/illustrative/i)).not.toBeInTheDocument();
  });

  it("labels a stale scan (weekend/holiday) as last session, not today", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockJson(movers("2026-01-02")));
    renderWithQuery(<LiveTape />);

    expect(await screen.findByText(/Live · last session movers/i)).toBeInTheDocument();
    expect(screen.queryByText(/today's movers/i)).not.toBeInTheDocument();
  });

  it("falls back to the labelled illustrative tape when the feed is empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockJson(movers(null, [], [])));
    renderWithQuery(<LiveTape />);

    expect(await screen.findByText(/illustrative/i)).toBeInTheDocument();
    expect(screen.getAllByText("NVDA").length).toBe(2); // fallback set still scrolls
    expect(screen.queryByText(/Live ·/i)).not.toBeInTheDocument();
  });

  it("shows the illustrative label while loading (prerender state)", () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(() => {}));
    renderWithQuery(<LiveTape />);
    expect(screen.getByText(/illustrative/i)).toBeInTheDocument();
  });

  it("dedupes, skips null-change rows, and pads a sparse feed to fill the marquee", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson(
        movers(
          etDateString(),
          [row("NVDA", 4.1), row("NVDA", 4.1), row("XXXX", null), row("A", 1), row("B", 1)],
          [row("C", -1)],
        ),
      ),
    );
    renderWithQuery(<LiveTape />);
    await screen.findByText(/Live · today's movers/i);
    // 4 unique valid items → each half repeats them ×3 (≥12), doubled → ×6.
    expect(screen.getAllByText("NVDA").length).toBe(6);
    expect(screen.getAllByText("C").length).toBe(6);
    expect(screen.queryByText("XXXX")).not.toBeInTheDocument(); // no change_pct → skipped
  });
});
