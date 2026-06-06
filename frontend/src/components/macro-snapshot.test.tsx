/**
 * MacroSnapshot widget contract.
 *
 * Asserts:
 *   * KPI tiles render the latest_value + as_of from the FRED batch.
 *   * Yield curve mini-bar renders one bar per tenor with the right %.
 *   * Error envelope on either endpoint surfaces a friendly notice
 *     instead of breaking the home page layout.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { MacroSnapshot } from "./macro-snapshot";

function mockJson(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MacroSnapshot", () => {
  it("renders the four KPI tiles + yield curve from the API", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/macro/series")) {
        return mockJson({
          data: {
            source: "FRED",
            cache_ttl_seconds: 3600,
            series: [
              {
                series_id: "DFF",
                label: "Federal Funds Effective Rate (daily)",
                latest_value: 4.31,
                latest_date: "2026-05-27",
                points: [],
              },
              {
                series_id: "DGS10",
                label: "10-Year Treasury",
                latest_value: 4.45,
                latest_date: "2026-05-27",
                points: [],
              },
              {
                series_id: "CPIAUCSL",
                label: "CPI",
                latest_value: 320.4,
                latest_date: "2026-04-01",
                points: [],
              },
              {
                series_id: "UNRATE",
                label: "Unemployment",
                latest_value: 4.1,
                latest_date: "2026-04-01",
                points: [],
              },
            ],
          },
          error: null,
          meta: { request_id: "r-1" },
        });
      }
      if (url.includes("/macro/yield_curve")) {
        return mockJson({
          data: {
            as_of: "2026-05-28",
            source: "US Treasury",
            cache_ttl_seconds: 3600,
            points: [
              { tenor: "3M", yield_pct: 3.69 },
              { tenor: "2Y", yield_pct: 3.99 },
              { tenor: "10Y", yield_pct: 4.45 },
              { tenor: "30Y", yield_pct: 4.98 },
            ],
          },
          error: null,
          meta: { request_id: "r-2" },
        });
      }
      throw new Error("Unexpected URL in test: " + url);
    });

    renderWithQuery(<MacroSnapshot />);

    expect(await screen.findByText(/auto-refreshes after 1 hour/i)).toBeInTheDocument();
    expect(await screen.findByText("Fed Funds")).toBeInTheDocument();
    expect(screen.getByText("10Y Treasury")).toBeInTheDocument();
    expect(screen.getByText("CPI (level)")).toBeInTheDocument();
    expect(screen.getByText("Unemployment")).toBeInTheDocument();
    // Latest DFF value formatted to 2 decimals.
    expect(screen.getByText("4.31")).toBeInTheDocument();
    // CPI level → 1 decimal heuristic.
    expect(screen.getByText("320.4")).toBeInTheDocument();

    await waitFor(() =>
      expect(screen.getByText(/as of 2026-05-28/i)).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/US Treasury/i).length).toBeGreaterThan(0);
    // Yield curve bars: one per tenor.
    expect(screen.getByText("3M")).toBeInTheDocument();
    expect(screen.getByText("10Y")).toBeInTheDocument();
    expect(screen.getByText("4.45%")).toBeInTheDocument();
  });

  it("shows a friendly notice when the FRED endpoint errors out", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/macro/series")) {
        return mockJson(
          {
            data: null,
            error: { code: "server_error", message: "FRED fetch failed." },
            meta: { request_id: "r-3" },
          },
          { status: 500 },
        );
      }
      // Yield curve still works — separate query, separate fate.
      return mockJson({
        data: { as_of: "2026-05-28", points: [] },
        error: null,
        meta: { request_id: "r-4" },
      });
    });

    renderWithQuery(<MacroSnapshot />);

    expect(
      await screen.findByText(/could not load FRED data/i),
    ).toBeInTheDocument();
  });
});
