/**
 * OptionsAnalysis: renders Greeks + payoff for the active book's option
 * contracts (POST /options/analyze), and renders nothing when there are none.
 * optionContractsFromHoldings extracts only the option entries from a holdings
 * dict.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u-1" }, accessToken: "jwt", configured: true, loading: false }),
}));
// recharts needs a sized parent jsdom lacks — stub the payoff chart.
vi.mock("recharts", () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  return {
    ResponsiveContainer: Pass,
    LineChart: Pass,
    Line: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    ReferenceLine: () => null,
  };
});

import { OptionsAnalysis } from "./options-analysis";
import { optionContractsFromHoldings, type OptionContract } from "@/lib/queries";

const CONTRACT: OptionContract = {
  underlying: "AAPL",
  option_type: "call",
  strike: 150,
  expiry: "2027-01-15",
  quantity: 2,
  avg_premium: 5,
  contract_multiplier: 100,
};

function analyzeJson() {
  return new Response(
    JSON.stringify({
      data: {
        results: [
          {
            contract_symbol: "AAPL270115C00150000",
            underlying: "AAPL",
            option_type: "call",
            strike: 150,
            expiry: "2027-01-15",
            quantity: 2,
            contract_multiplier: 100,
            days_to_expiry: 200,
            spot: 180,
            mark: 40,
            iv: 0.3,
            greeks: { delta: 0.7, gamma: 0.01, theta: -0.05, vega: 0.2, rho: 0.1 },
            delta_notional: 25200,
            market_value: 8000,
            cost_basis: 1000,
            unrealized_pnl: 7000,
            break_even: 155,
            moneyness: "ITM",
            payoff: [{ price: 150, pnl: -1000 }, { price: 200, pnl: 9000 }],
            source: "yfinance",
            warnings: [],
          },
        ],
        totals: {
          net_delta: 140,
          net_gamma: 2,
          net_theta: -10,
          net_vega: 40,
          delta_notional: 25200,
          market_value: 8000,
          unrealized_pnl: 7000,
          contracts: 1,
        },
        exposure: {
          net_delta: 140,
          gross_delta: 140,
          net_gamma: 2,
          net_theta: -10,
          net_vega: 40,
          option_market_value: 8000,
          option_notional: 25200,
          short_collateral_estimate: 0,
          contracts: 1,
          short_contracts: 0,
          expiry_ladder: [
            { expiry: "2027-01-15", days_to_expiry: 200, contracts: 1, net_delta: 140, net_notional: 25200 },
          ],
          underlying_exposure: [
            { underlying: "AAPL", contracts: 1, net_delta: 140, net_notional: 25200, equity_shares: null },
          ],
          flags: [{ code: "high_single_underlying", severity: "watch", detail: "Concentrated in AAPL." }],
        },
        scenarios: {
          grid: [{ underlying_shock: -0.2, iv_shock: 0.1, horizon: 0, total_pnl: -500 }],
          top_positions: [{ underlying: "AAPL", option_type: "call", strike: 150, quantity: 2, pnl: -500 }],
          stress_cell: { underlying_shock: -0.2, iv_shock: 0.1, horizon: 0 },
          underlying_shocks: [-0.2],
          iv_shocks: [0.1],
          horizons: [0, 7, 30, "expiry"],
          repriced: 1,
          skipped: [],
          as_of: "2026-06-13",
        },
        as_of: "2026-06-13",
        warnings: [],
      },
      error: null,
      meta: { request_id: "r" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function explainJson() {
  return new Response(
    JSON.stringify({
      data: {
        severity: "elevated",
        headline: "Elevated option risk — Concentrated in AAPL.",
        summary_bullets: ["Most exposure is one name."],
        suggested_actions: [
          { title: "Inspect concentration", reason: "Concentrated in AAPL.", next_step: "Size accordingly." },
        ],
        caveats: ["Educational, not financial advice."],
        ai_generated: false,
      },
      error: null,
      meta: { request_id: "r" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

// Route fetch by URL: /explain vs /analyze (which now carries scenarios).
function mockFetchByUrl() {
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/explain")) return Promise.resolve(explainJson());
    return Promise.resolve(analyzeJson());
  });
}

afterEach(() => vi.restoreAllMocks());

describe("optionContractsFromHoldings", () => {
  it("extracts only option entries, ignoring equities", () => {
    const contracts = optionContractsFromHoldings({
      AAPL: { shares: 10, avg_cost: 180 },
      AAPL270115C00150000: {
        shares: 2,
        avg_cost: 5,
        asset_type: "option",
        option_type: "call",
        underlying: "AAPL",
        strike: 150,
        expiry: "2027-01-15",
      },
    });
    expect(contracts).toHaveLength(1);
    expect(contracts[0]).toMatchObject({ underlying: "AAPL", strike: 150, quantity: 2, avg_premium: 5 });
  });

  it("drops option entries missing required contract fields", () => {
    const contracts = optionContractsFromHoldings({
      BAD: { shares: 1, asset_type: "option", option_type: "put", underlying: "SPY" }, // no strike/expiry
    });
    expect(contracts).toHaveLength(0);
  });
});

describe("OptionsAnalysis", () => {
  it("renders nothing when there are no option contracts", () => {
    const { container } = renderWithQuery(<OptionsAnalysis contracts={[]} />);
    expect(container.textContent).not.toContain("Options");
  });

  it("renders exposure, flags, stress grid + contract once analytics load", async () => {
    mockFetchByUrl();
    renderWithQuery(<OptionsAnalysis contracts={[CONTRACT]} />);
    // exposure summary
    expect(await screen.findByText("Portfolio option exposure", { exact: false })).toBeInTheDocument();
    // risk flag surfaced
    expect(await screen.findByText("Concentrated in AAPL.")).toBeInTheDocument();
    // per-contract delta + moneyness
    expect(await screen.findByText("0.700")).toBeInTheDocument();
    expect(screen.getAllByText("ITM").length).toBeGreaterThan(0);
    // stress grid repriced
    expect(await screen.findByText("Stress grid", { exact: false })).toBeInTheDocument();
  });
});
