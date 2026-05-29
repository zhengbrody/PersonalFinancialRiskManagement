/**
 * /portfolios/[id]/risk page contract.
 *
 *   1. Anonymous → redirected to /login.
 *   2. Authed, no report yet → "No report yet" + Run button.
 *   3. Run button → calls POST /api/v1/risk/report_from_active with the
 *      bearer token; renders KPIs + factor + component tables.
 *   4. Specific error codes show user-friendly copy
 *      (no_active_portfolio).
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const replaceMock = vi.fn();
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "p-default" }),
  useRouter: () => ({ replace: replaceMock, push: pushMock }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import PortfolioRiskPage from "./page";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt-here",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  });
}

function mockJson(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

const PORTFOLIO_LIST = {
  data: {
    user_id: "u-1",
    email: "owner@mindmarket.test",
    portfolios: [
      {
        id: "p-default",
        user_id: "u-1",
        name: "Default",
        holdings: { SPY: { shares: 100 }, BND: { shares: 50 } },
        margin_loan: 0,
        contributed_capital: 40000,
        cash_balance: 0,
        is_default: true,
        created_at: null,
        updated_at: null,
      },
    ],
  },
  error: null,
  meta: { request_id: "r-list" },
};

const SAMPLE_REPORT = {
  data: {
    annual_return: 0.08,
    annual_volatility: 0.12,
    sharpe_ratio: 0.5,
    max_drawdown: -0.07,
    var_95: 0.012,
    var_99: 0.018,
    cvar_95: 0.017,
    risk_free_rate: 0.045,
    betas: { SPY: 0.96 },
    factor_betas: [
      {
        factor: "SPY",
        beta: 1.02,
        r_squared: 0.91,
        t_stat: 42,
        p_value: 0,
      },
      {
        factor: "QQQ",
        beta: 0.85,
        r_squared: 0.8,
        t_stat: 18,
        p_value: 0,
      },
    ],
    component_var_pct: [
      { ticker: "SPY", pct: 0.6 },
      { ticker: "BND", pct: 0.4 },
    ],
    stress_loss: 0.09,
    stress_market_shock: -0.1,
    stress_asset_losses: [
      { ticker: "SPY", loss_pct: 0.1 },
      { ticker: "BND", loss_pct: 0.02 },
    ],
    macro_betas: { rates: 0.4, usd: -0.1, oil: 0.05 },
    liquidity: [],
    drawdown_stats: null,
  },
  error: null,
  meta: { request_id: "r-report" },
};

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("PortfolioRiskPage", () => {
  it("redirects anonymous users to /login", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp: vi.fn(),
      signOut: vi.fn(),
    });
    renderWithQuery(<PortfolioRiskPage />);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("renders idle state with a Run button after portfolios load", async () => {
    authed();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      mockJson(PORTFOLIO_LIST),
    );

    renderWithQuery(<PortfolioRiskPage />);

    expect(await screen.findByText(/no report yet/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^run report$/i }),
    ).toBeInTheDocument();
  });

  it("renders the full report on a successful Run", async () => {
    authed();
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(PORTFOLIO_LIST))
      .mockResolvedValueOnce(mockJson(SAMPLE_REPORT));

    const user = userEvent.setup();
    renderWithQuery(<PortfolioRiskPage />);

    await user.click(
      await screen.findByRole("button", { name: /^run report$/i }),
    );

    // KPI tiles: VaR / CVaR / Sharpe values.
    expect(await screen.findByText("1.20%")).toBeInTheDocument(); // var_95
    expect(screen.getByText("1.70%")).toBeInTheDocument(); // cvar_95
    expect(screen.getByText("0.50")).toBeInTheDocument(); // sharpe

    // Factor betas table rows.
    expect(screen.getByText("1.020")).toBeInTheDocument();
    expect(screen.getByText("0.850")).toBeInTheDocument();

    // Component VaR rendered with tickers.
    const componentVarMatches = screen.getAllByText("SPY");
    expect(componentVarMatches.length).toBeGreaterThan(0);

    // After success the button becomes Re-run.
    expect(
      screen.getByRole("button", { name: /re-?run/i }),
    ).toBeInTheDocument();

    // The mutation must have used the bearer token.
    const reportCall = fetchSpy.mock.calls.find(
      (c) => String(c[0]).includes("report_from_active"),
    );
    expect(reportCall).toBeDefined();
    const init = reportCall![1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer jwt-here");
    expect(init.method).toBe("POST");
  });

  it("renders the no_active_portfolio specific copy", async () => {
    authed();
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(mockJson(PORTFOLIO_LIST))
      .mockResolvedValueOnce(
        mockJson(
          {
            data: null,
            error: {
              code: "no_active_portfolio",
              message: "No active portfolio.",
            },
            meta: { request_id: "r" },
          },
          { status: 422 },
        ),
      );

    const user = userEvent.setup();
    renderWithQuery(<PortfolioRiskPage />);
    await user.click(
      await screen.findByRole("button", { name: /^run report$/i }),
    );

    expect(
      await screen.findByText(/no active portfolio/i),
    ).toBeInTheDocument();
    // The structured code shows in the small caption too.
    expect(screen.getByText(/no_active_portfolio/i)).toBeInTheDocument();
  });
});
