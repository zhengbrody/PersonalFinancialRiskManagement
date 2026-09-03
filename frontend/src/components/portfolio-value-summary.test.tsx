import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, accessToken: "jwt", configured: true, loading: false }),
}));

import { cashAdjustedPerformance, PortfolioValueSummary } from "./portfolio-value-summary";

function mockJson(snapshots: unknown[]) {
  return new Response(JSON.stringify({ data: { snapshots }, error: null, meta: { request_id: "r" } }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.restoreAllMocks());

describe("PortfolioValueSummary", () => {
  it("renders value, daily pnl, total return, and history delta", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson([
        { as_of: "2026-05-20", net_equity: 48000 },
        { as_of: "2026-05-28", net_equity: 51000 },
      ]),
    );

    renderWithQuery(
      <PortfolioValueSummary
        metrics={{
          net_equity: 51000,
          daily_pnl: 450,
          daily_return: 0.0089,
          total_pnl: 11000,
          total_return: 0.275,
        }}
      />,
    );

    expect(screen.getByText("$51,000")).toBeInTheDocument();
    expect(screen.getByText("+$450")).toBeInTheDocument();
    expect(screen.getByText("+0.89%")).toBeInTheDocument();
    expect(screen.getByText("+$11,000")).toBeInTheDocument();
    expect(screen.getByText("+27.50%")).toBeInTheDocument();
    expect(await screen.findByText("+$3,000")).toBeInTheDocument();
    expect(screen.getByText("+6.25%")).toBeInTheDocument();
  });

  it("formats negative dollar moves as -$n, not $-n", () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockJson([]));

    renderWithQuery(
      <PortfolioValueSummary
        metrics={{
          net_equity: 39000,
          daily_pnl: -1000,
          daily_return: -0.025,
          total_pnl: -2500,
          total_return: -0.0609,
        }}
      />,
    );

    expect(screen.getByText("-$1,000")).toBeInTheDocument();
    expect(screen.getByText("-$2,500")).toBeInTheDocument();
  });

  it("removes new contributions from tracked investment profit", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockJson([
        { as_of: "2026-01-02T00:00:00Z", net_equity: 48000, contributed_capital: 40000 },
        { as_of: "2026-06-30T00:00:00Z", net_equity: 53000, contributed_capital: 45000 },
      ]),
    );
    renderWithQuery(
      <PortfolioValueSummary metrics={{ net_equity: 51000, contributed_capital: 45000 }} />,
    );
    expect(await screen.findByText("-$2,000")).toBeInTheDocument();
    expect(screen.getByText("+$5,000 net flows removed")).toBeInTheDocument();
  });

  it("uses time-weighted cash flows in its Modified-Dietz denominator", () => {
    const performance = cashAdjustedPerformance(
      [
        { as_of: "2026-01-01T00:00:00Z", net_equity: 48000, contributed_capital: 40000 },
        { as_of: "2026-07-02T00:00:00Z", net_equity: 53000, contributed_capital: 45000 },
      ],
      51000,
      45000,
      new Date("2027-01-01T00:00:00Z"),
    );
    expect(performance.pnl).toBe(-2000);
    expect(performance.netFlows).toBe(5000);
    expect(performance.flowAdjusted).toBe(true);
    expect(performance.returnPct).toBeCloseTo(-2000 / 50506.85, 4);
  });
});
