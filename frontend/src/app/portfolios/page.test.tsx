/**
 * `/portfolios` page state-machine.
 *
 * Branches asserted:
 *   1. Anonymous (auth loaded, no user) → redirected to /login.
 *   2. Authed + envelope OK + empty list → empty-state CTA visible.
 *   3. Authed + envelope OK + 1 row → portfolio card with name + tickers.
 *   4. Authed + envelope error → destructive panel with API code.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
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

import PortfoliosPage from "./page";

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

function mockEnvelope(body: unknown, init: { status?: number } = {}) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
    new Response(JSON.stringify(body), {
      status: init.status ?? 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("PortfoliosPage", () => {
  it("redirects to /login when signed out", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signOut: vi.fn(),
    });

    renderWithQuery(<PortfoliosPage />);
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("renders the empty-state CTA when the user has no portfolios", async () => {
    authed();
    mockEnvelope({
      data: { user_id: "u-1", email: "owner@mindmarket.test", portfolios: [] },
      error: null,
      meta: { request_id: "r-1" },
    });

    renderWithQuery(<PortfoliosPage />);
    expect(
      await screen.findByText(/no portfolios yet/i),
    ).toBeInTheDocument();
  });

  it("renders a portfolio card on a successful response", async () => {
    authed();
    mockEnvelope({
      data: {
        user_id: "u-1",
        email: "owner@mindmarket.test",
        portfolios: [
          {
            id: "p-1",
            user_id: "u-1",
            name: "Default",
            holdings: { SPY: { shares: 100 }, BND: { shares: 50 } },
            margin_loan: 0,
            contributed_capital: 40000,
            cash_balance: 1000,
            is_default: true,
            created_at: null,
            updated_at: null,
          },
        ],
      },
      error: null,
      meta: { request_id: "r-2" },
    });

    renderWithQuery(<PortfoliosPage />);
    // Card title: matches once (exact-case). The lowercase "default"
    // badge has its own selector below.
    expect(await screen.findByText("Default")).toBeInTheDocument();
    expect(screen.getByText(/SPY, BND/)).toBeInTheDocument();
    // Two matches expected: card title + badge. Specifically assert both.
    expect(screen.getAllByText(/default/i)).toHaveLength(2);
  });

  // ── Score flow (Phase 4) ──────────────────────────────────────────

  it("renders a Score button only on the default portfolio card", async () => {
    authed();
    mockEnvelope({
      data: {
        user_id: "u-1",
        email: "owner@mindmarket.test",
        portfolios: [
          {
            id: "p-default",
            user_id: "u-1",
            name: "Default",
            holdings: { SPY: { shares: 100 } },
            margin_loan: 0,
            contributed_capital: 40000,
            cash_balance: 0,
            is_default: true,
            created_at: null,
            updated_at: null,
          },
          {
            id: "p-spec",
            user_id: "u-1",
            name: "Speculative",
            holdings: { TQQQ: { shares: 10 } },
            margin_loan: 0,
            contributed_capital: 5000,
            cash_balance: 0,
            is_default: false,
            created_at: null,
            updated_at: null,
          },
        ],
      },
      error: null,
      meta: { request_id: "r-score-1" },
    });

    renderWithQuery(<PortfoliosPage />);
    await screen.findByText("Default");
    // Exactly one Score button — the non-default card omits it so the
    // user can't accidentally score the wrong portfolio.
    expect(screen.getAllByRole("button", { name: /^score$/i })).toHaveLength(1);
  });

  it("calls /score_from_active and renders the inline result", async () => {
    authed();
    // First fetch: portfolios list. Second fetch: score response.
    mockEnvelope({
      data: {
        user_id: "u-1",
        email: "owner@mindmarket.test",
        portfolios: [
          {
            id: "p-default",
            user_id: "u-1",
            name: "Default",
            holdings: { SPY: { shares: 100 } },
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
    });
    mockEnvelope({
      data: {
        overall_score: 612,
        risk_preference: 3,
        risk_target: {},
        metrics: {
          annual_return: 0.08,
          annual_volatility: 0.12,
          sharpe_ratio: 0.5,
          max_drawdown: -0.07,
          var_95_daily: -0.012,
          cvar_95_daily: -0.017,
          beta_to_benchmark: null,
          total_value: 52000,
          cash_weight: 0,
          data_coverage: 1,
          observations: 252,
          data_quality_notes: [],
        },
        dimensions: {
          risk_match: { name: "Risk Match", score: 700, status: "good", detail: "" },
          risk_adjusted_return: {
            name: "Risk-Adjusted Return",
            score: 540,
            status: "fair",
            detail: "",
          },
          downside_protection: {
            name: "Downside Protection",
            score: 600,
            status: "fair",
            detail: "",
          },
        },
      },
      error: null,
      meta: { request_id: "r-score" },
    });

    const user = userEvent.setup();
    renderWithQuery(<PortfoliosPage />);
    const btn = await screen.findByRole("button", { name: /^score$/i });
    await user.click(btn);

    expect(await screen.findByText("612")).toBeInTheDocument();
    expect(screen.getByText("Risk Match")).toBeInTheDocument();
    expect(screen.getByText("Downside Protection")).toBeInTheDocument();
    // After a successful score the button label becomes Re-score.
    expect(
      screen.getByRole("button", { name: /re-?score/i }),
    ).toBeInTheDocument();
  });

  it("renders the 'No active portfolio' error copy on the specific code", async () => {
    authed();
    mockEnvelope({
      data: {
        user_id: "u-1",
        email: "owner@mindmarket.test",
        portfolios: [
          {
            id: "p-default",
            user_id: "u-1",
            name: "Default",
            holdings: { SPY: { shares: 100 } },
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
      meta: { request_id: "r-list-2" },
    });
    mockEnvelope(
      {
        data: null,
        error: {
          code: "no_active_portfolio",
          message: "No active portfolio. Create one before scoring.",
        },
        meta: { request_id: "r-score-err" },
      },
      { status: 422 },
    );

    const user = userEvent.setup();
    renderWithQuery(<PortfoliosPage />);
    const btn = await screen.findByRole("button", { name: /^score$/i });
    await user.click(btn);

    // Specific copy for the structured error code, not the raw message.
    expect(
      await screen.findByText(/no active portfolio/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/no_active_portfolio/i)).toBeInTheDocument();
  });

  it("renders the error panel when the envelope returns an error", async () => {
    authed();
    mockEnvelope(
      {
        data: null,
        error: { code: "server_error", message: "Could not load portfolios." },
        meta: { request_id: "r-3" },
      },
      { status: 500 },
    );

    renderWithQuery(<PortfoliosPage />);
    // Card title "Could not load portfolios" + body "Could not load
    // portfolios." both match; assert via findAllByText so the wait
    // resolves once the panel mounts, then assert count.
    const matches = await screen.findAllByText(/could not load portfolios/i);
    expect(matches.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/server_error/i)).toBeInTheDocument();
  });
});
