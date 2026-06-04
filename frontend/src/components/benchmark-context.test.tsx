/**
 * BenchmarkContext: renders the "You vs S&P 500 vs 60/40" comparison from the
 * public /risk/benchmarks endpoint, and renders nothing when it's empty.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { BenchmarkContext } from "./benchmark-context";

function mockJson(body: Record<string, unknown>) {
  return new Response(JSON.stringify({ ...body, meta: { request_id: "r" } }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const MINE = { annual_return: 0.08, annual_volatility: 0.18, sharpe_ratio: 0.4, max_drawdown: -0.25 };

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BenchmarkContext", () => {
  it("renders the comparison vs SPY + 60/40", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({
        data: {
          as_of: "2026-06-03",
          benchmarks: [
            { name: "S&P 500 (SPY)", annual_return: 0.12, annual_volatility: 0.16, sharpe_ratio: 0.7, max_drawdown: -0.2 },
            { name: "Balanced 60/40", annual_return: 0.08, annual_volatility: 0.1, sharpe_ratio: 0.6, max_drawdown: -0.12 },
          ],
        },
        error: null,
      }),
    );

    renderWithQuery(<BenchmarkContext mine={MINE} />);

    expect(await screen.findByText("How you compare")).toBeInTheDocument();
    expect(screen.getByText("S&P 500 (SPY)")).toBeInTheDocument();
    expect(screen.getByText("Balanced 60/40")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Sharpe")).toBeInTheDocument();
  });

  it("renders nothing when benchmarks are empty (fail-soft)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson({ data: { as_of: null, benchmarks: [] }, error: null }),
    );
    const { container } = renderWithQuery(<BenchmarkContext mine={MINE} />);
    // Give the query a tick; nothing should render.
    await new Promise((r) => setTimeout(r, 20));
    expect(container.querySelector("table")).toBeNull();
  });
});
