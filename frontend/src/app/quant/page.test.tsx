/**
 * `/quant` Backtest page state-machine.
 *
 * Branches asserted:
 *   1. controls render (strategy / period / rebalance + Run button).
 *   2. running a backtest renders the friendly KPI cards + the equity
 *      curve container from a mocked response.
 *   3. a no_active_portfolio error shows the friendly "Create a
 *      portfolio first" CTA (no raw error code).
 *
 * Auth + navigation are mocked the same way as /copilot.
 *
 * recharts is mocked: its ResponsiveContainer needs a sized parent that
 * jsdom never provides, so we stub the wrapper to a plain element that
 * echoes the point count. Tests assert on data/labels, not SVG pixels.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

// Stub the chart wrapper: recharts' ResponsiveContainer renders nothing
// without a measured parent in jsdom. We expose the point count via a
// test id so we can assert the data reached the chart without touching
// chart internals.
vi.mock("@/components/ui/chart-line", () => ({
  TimeSeriesChart: ({
    data,
    ariaLabel,
  }: {
    data: unknown[];
    ariaLabel?: string;
  }) => (
    <div data-testid="time-series-chart" aria-label={ariaLabel}>
      {data.length} points
    </div>
  ),
}));

import QuantPage from "./page";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "test-jwt",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signOut: vi.fn(),
  });
}

function envelope(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function routeFetch(backtest: { body: unknown; status?: number }) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/quant/backtest")) {
        return envelope(backtest.body, backtest.status ?? 200);
      }
      return envelope({ data: {}, error: null, meta: { request_id: "r" } });
    });
}

const successBody = {
  data: {
    strategy: "static",
    start_date: "2022-05-01",
    end_date: "2025-05-01",
    benchmark: "SPY",
    stats: {
      total_return: 0.42,
      annual_return: 0.124,
      annual_volatility: 0.18,
      sharpe_ratio: 1.3,
      sortino_ratio: 1.8,
      calmar_ratio: 0.9,
      max_drawdown: -0.22,
      win_rate: 0.55,
      alpha: 0.03,
      beta: 1.05,
    },
    equity_curve: [
      { date: "2022-05-01", value: 1.0 },
      { date: "2023-05-01", value: 1.2 },
      { date: "2025-05-01", value: 1.42 },
    ],
    drawdown_series: [
      { date: "2022-05-01", value: 0 },
      { date: "2023-01-01", value: -0.22 },
    ],
    benchmark_total_return: 0.3,
  },
  error: null,
  meta: { request_id: "r-bt" },
};

beforeEach(() => {
  authed();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("QuantPage", () => {
  it("renders the controls and the run button", () => {
    routeFetch({ body: { data: {}, error: null, meta: { request_id: "r" } } });
    renderWithQuery(<QuantPage />);

    expect(
      screen.getByRole("heading", { name: /quant lab/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /backtest/i })).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: /strategy/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: /time period/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: /rebalance/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /run backtest/i }),
    ).toBeInTheDocument();
  });

  it("renders KPIs and the equity curve after running a backtest", async () => {
    routeFetch({ body: successBody });
    const user = userEvent.setup();
    renderWithQuery(<QuantPage />);

    await user.click(screen.getByRole("button", { name: /run backtest/i }));

    // Friendly KPI labels + translated values.
    expect(await screen.findByText(/total return/i)).toBeInTheDocument();
    expect(screen.getByText("42.0%")).toBeInTheDocument();
    expect(screen.getByText(/worst drop/i)).toBeInTheDocument();
    expect(screen.getByText("-22.0%")).toBeInTheDocument();
    expect(screen.getByText(/risk-adjusted return/i)).toBeInTheDocument();
    expect(screen.getByText("1.30")).toBeInTheDocument();

    // vs-benchmark chip: 0.42 - 0.30 = +12.0%.
    expect(screen.getByText(/vs SPY/i)).toBeInTheDocument();

    // Both charts received their data (equity + drawdown).
    const charts = screen.getAllByTestId("time-series-chart");
    expect(charts).toHaveLength(2);
    expect(
      screen.getByLabelText(/portfolio value over time/i),
    ).toHaveTextContent("3 points");
    expect(screen.getByLabelText(/drawdown over time/i)).toHaveTextContent(
      "2 points",
    );
  });

  it("shows the create-a-portfolio CTA on no_active_portfolio", async () => {
    routeFetch({
      body: {
        data: null,
        error: {
          code: "no_active_portfolio",
          message: "No active portfolio.",
        },
        meta: { request_id: "r-none" },
      },
      status: 422,
    });

    const user = userEvent.setup();
    renderWithQuery(<QuantPage />);

    await user.click(screen.getByRole("button", { name: /run backtest/i }));

    expect(
      await screen.findByText(/create a portfolio first/i),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /create a portfolio/i });
    expect(link).toHaveAttribute("href", "/portfolios/new");
    // No raw error code leaks to the user.
    expect(screen.queryByText(/no_active_portfolio/i)).not.toBeInTheDocument();
  });

  it("Attribution tab runs + renders KPIs", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/quant/attribution")) {
        return envelope({
          data: {
            tracking_error: 0.04,
            information_ratio: 0.6,
            hit_ratio: 0.55,
            active_return_annual: 0.03,
            brinson: {
              total_active_return: 0.03,
              allocation_effect: 0.01,
              selection_effect: 0.02,
              interaction_effect: 0,
              sector_detail: [
                { sector: "Technology", weight_diff: 0.2, allocation_effect: 0.01, selection_effect: 0.02, total_effect: 0.03 },
              ],
            },
            factor: { alpha: 0.02, r_squared: 0.88, residual_return: 0.005, factor_betas: { SPY: 1.05 }, factor_contributions: { SPY: 0.04 } },
          },
          error: null,
          meta: { request_id: "r-attr" },
        });
      }
      return envelope({ data: {}, error: null, meta: { request_id: "r" } });
    });

    const user = userEvent.setup();
    renderWithQuery(<QuantPage />);
    await user.click(screen.getByRole("tab", { name: /attribution/i }));
    await user.click(screen.getByRole("button", { name: /run attribution/i }));

    expect(await screen.findByText("Information ratio")).toBeInTheDocument();
    expect(screen.getByText("0.60")).toBeInTheDocument(); // IR
    expect(screen.getByText(/brinson decomposition/i)).toBeInTheDocument();
  });

  it("Regime tab renders the current regime + transition matrix", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/macro/regime_detail")) {
        return envelope({
          data: {
            current_regime: "Bull",
            confidence: 0.8,
            regime_since_date: "2026-01-02",
            vix_regime: "Calm",
            trend_regime: "Up",
            vol_regime: "Low",
            history: [
              { date: "2026-01-01", regime: "Bull" },
              { date: "2026-01-02", regime: "Bull" },
              { date: "2026-01-03", regime: "Bear" },
            ],
          },
          error: null,
          meta: { request_id: "r-reg" },
        });
      }
      return envelope({ data: {}, error: null, meta: { request_id: "r" } });
    });

    const user = userEvent.setup();
    renderWithQuery(<QuantPage />);
    await user.click(screen.getByRole("tab", { name: /regime/i }));

    // "Bull" shows in the hero + the matrix; just assert it appeared.
    expect((await screen.findAllByText("Bull")).length).toBeGreaterThan(0);
    expect(screen.getByText(/regime transitions/i)).toBeInTheDocument();
    expect(screen.getByText(/current regime/i)).toBeInTheDocument();
  });
});
