/**
 * `/research` — consolidated single-page cockpit.
 *
 * One bundle fetch (`GET /research/{ticker}/bundle`) feeds the whole page; the
 * AI verdict (`POST /research/verdict`) auto-fires from the bundle's FactPack.
 * The heavy data sections (financials / DCF / peers / earnings / news / charts)
 * are reused components with their own tests — stubbed here so the page test
 * stays focused on composition + the verdict branch.
 *
 * Branches asserted:
 *   1. empty state + search box render.
 *   2. searching a ticker paints the whole cockpit (identity, trust strip,
 *      driver, valuation band, ownership, momentum) AND the auto-fired verdict.
 *   3. a quota_exceeded on the verdict shows the upgrade CTA while data stays.
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

// Reused data sections have their own tests — stub them so they don't self-fetch.
vi.mock("@/components/research-charts", () => ({ ResearchCharts: () => <div>chart</div> }));
vi.mock("@/components/research-financials", () => ({ ResearchFinancials: () => <div>financials</div> }));
vi.mock("@/components/valuation-dcf", () => ({ ValuationDcf: () => <div>dcf</div> }));
vi.mock("@/components/peers-comparison", () => ({ PeersComparison: () => <div>peers-chart</div> }));
vi.mock("@/components/earnings-comparison", () => ({ EarningsComparison: () => <div>earnings</div> }));
vi.mock("@/components/ticker-news", () => ({ TickerNews: () => <div>news</div> }));
vi.mock("@/components/analyst-report", () => ({ AnalystReportView: () => <div>report</div> }));

import ResearchPage from "./page";

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

const billingEnvelope = {
  data: { user_id: "u-1", email: "owner@mindmarket.test", plan: "free", subscription: null, plans: [] },
  error: null,
  meta: { request_id: "r-billing" },
};

const FACT_PACK = {
  ticker: "AAPL",
  name: "Apple Inc.",
  sector: "Technology",
  industry: "Consumer Electronics",
  currency: "USD",
  as_of: "2026-05-31T00:00:00+00:00",
  price: 200.5,
  market_cap: 3.1e12,
  beta: 1.2,
  valuation: {
    pe: 30.1,
    forward_pe: 25.0,
    ps: 8.2,
    pb: 45.0,
    ev_ebitda: 22.0,
    fcf_yield: 0.031,
    dividend_yield: 0.025, // ratio → 2.5%
    band: "rich",
    peer_median_pe: 24.0,
  },
  quality: {
    gross_margin: 0.45,
    operating_margin: 0.3,
    net_margin: 0.25,
    roe: 1.5,
    roa: 0.28,
    roic: 0.55,
    current_ratio: 1.28,
    debt_to_equity: 0.32,
    interest_coverage: 40.0,
  },
  growth: {
    revenue_cagr: 0.08,
    eps_cagr: 0.12,
    fcf_cagr: 0.15,
    revenue_growth_yoy: 0.06,
    earnings_growth_yoy: 0.1,
    periods: 5,
  },
  analyst: {
    rating: "buy",
    num_analysts: 40,
    target_low: 180,
    target_consensus: 240,
    target_high: 300,
    implied_upside_pct: 0.197,
  },
  momentum: {
    rsi_14: 58.0,
    sma_50: 190.0,
    sma_200: 175.0,
    price_vs_sma50_pct: 0.0553,
    price_vs_sma200_pct: 0.1457,
    fifty_two_week_high: 215.0,
    fifty_two_week_low: 150.0,
    pct_from_52w_high: -0.0674,
    pct_off_52w_low: 0.3367,
    realized_vol_20d: 0.27,
    realized_vol_60d: 0.31,
    trend: "uptrend",
  },
  ownership: { institutional_pct: 0.61 },
  insider: { buys_90d: 3, sells_90d: 1, net_shares_90d: 5000, signal: "net buying" },
  peers: [
    { ticker: "MSFT", name: "Microsoft", market_cap: 3.0e12, pe: 33.0, ps: 12.0, net_margin: 0.36, roe: 0.42 },
  ],
  news: [],
  drivers: ["High gross margins and durable franchise"],
  risk_flags: ["Trades at a rich multiple vs peers"],
  data_quality: {
    coverage: 0.85,
    sources: [
      { field: "pe", source: "yfinance", as_of: null, coverage: 1 },
      { field: "quality", source: "yfinance", as_of: null, coverage: 1 },
    ],
    warnings: ["fmp_key_missing"],
  },
};

const BUNDLE = {
  ticker: "AAPL",
  generated_at: "2026-05-31T00:00:00+00:00",
  as_of: "2026-05-31",
  data_confidence: 0.82,
  confidence_label: "high",
  fact_pack: FACT_PACK,
  financials: null,
  dcf: null,
  peers: null,
  earnings: null,
  thesis: null,
  news: null,
};

const VERDICT = {
  rating: "Buy",
  conviction: "high",
  summary: "Durable franchise at a fair multiple.",
  dimensions: [
    { name: "valuation", score: 55, note: "Slightly rich" },
    { name: "growth", score: 60, note: null },
    { name: "quality", score: 88, note: "Wide moat" },
    { name: "momentum", score: 65, note: null },
    { name: "risk", score: 70, note: null },
  ],
  catalysts: ["Earnings beat"],
  risks: ["Valuation rich"],
  what_would_change_my_mind: ["A demand collapse"],
  data_only: false,
};

function routeFetch(verdict: { body: unknown; status?: number }) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.includes("/research/AAPL/bundle")) {
      return envelope({ data: { bundle: BUNDLE }, error: null, meta: { request_id: "r-b" } });
    }
    if (url.includes("/research/verdict")) {
      return envelope(verdict.body, verdict.status ?? 200);
    }
    return envelope(billingEnvelope);
  });
}

beforeEach(() => {
  authed();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("ResearchPage", () => {
  it("renders the search box and the empty state", () => {
    routeFetch({ body: {} });
    renderWithQuery(<ResearchPage />);

    expect(screen.getByRole("heading", { name: /research/i })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /ticker symbol/i })).toBeInTheDocument();
    expect(screen.getByText(/search a ticker above/i)).toBeInTheDocument();
  });

  it("paints the whole cockpit and the auto-fired AI verdict after a search", async () => {
    routeFetch({
      body: { data: { verdict: VERDICT, fact_pack: FACT_PACK }, error: null, meta: { request_id: "r-v" } },
    });

    const user = userEvent.setup();
    renderWithQuery(<ResearchPage />);

    await user.type(screen.getByRole("textbox", { name: /ticker symbol/i }), "aapl");
    await user.click(screen.getByRole("button", { name: /research/i }));

    // Identity + trust strip + driver — all on one page, no tabs.
    expect((await screen.findAllByText(/apple inc\./i)).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Confidence: High \(82%\)/)).toBeInTheDocument();
    expect(screen.getByText(/high gross margins and durable franchise/i)).toBeInTheDocument();
    // Valuation band + dividend yield (always visible now).
    expect(screen.getByText(/^rich$/i)).toBeInTheDocument();
    expect(screen.getByText("2.5%")).toBeInTheDocument();
    // Ownership + momentum cards.
    expect(screen.getByText(/^net buying$/i)).toBeInTheDocument();
    expect(screen.getByText(/^uptrend$/i)).toBeInTheDocument();
    // The auto-fired AI verdict.
    expect(await screen.findByText(/durable franchise at a fair multiple/i)).toBeInTheDocument();
    expect(screen.getByText("88/100")).toBeInTheDocument(); // quality dimension bar
  });

  it("shows the upgrade CTA on a quota_exceeded verdict, keeping the data", async () => {
    routeFetch({
      body: {
        data: null,
        error: { code: "quota_exceeded", message: "Monthly analysis quota exhausted." },
        meta: { request_id: "r-q" },
      },
      status: 429,
    });

    const user = userEvent.setup();
    renderWithQuery(<ResearchPage />);

    await user.type(screen.getByRole("textbox", { name: /ticker symbol/i }), "aapl");
    await user.click(screen.getByRole("button", { name: /research/i }));

    // Fact pack still painted.
    expect((await screen.findAllByText(/apple inc\./i)).length).toBeGreaterThanOrEqual(1);
    // Verdict replaced by the upgrade CTA.
    expect(await screen.findByText(/used your ai analysis quota/i)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /see plans/i });
    expect(link).toHaveAttribute("href", "/pricing");
  });
});
