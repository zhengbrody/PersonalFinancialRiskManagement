/**
 * `/research` Ticker Research 2.0 FactPack cockpit.
 *
 * Branches asserted:
 *   1. empty state + search box render.
 *   2. searching a ticker paints the FactPack cockpit (numbers, valuation
 *      band, a source badge, a driver) AND the AI verdict.
 *   3. a quota_exceeded on the verdict shows the upgrade CTA while the fact
 *      pack stays visible.
 *
 * Auth + navigation are mocked the same way as /copilot.
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
  data: {
    user_id: "u-1",
    email: "owner@mindmarket.test",
    plan: "free",
    subscription: null,
    plans: [],
  },
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
    debt_to_equity: 0.32, // ratio (×), not 32
    interest_coverage: 40.0,
  },
  growth: {
    revenue_cagr: 0.08,
    eps_cagr: 0.12,
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
  peers: [
    {
      ticker: "MSFT",
      name: "Microsoft",
      market_cap: 3.0e12,
      pe: 33.0,
      ps: 12.0,
      net_margin: 0.36,
      roe: 0.42,
    },
  ],
  news: [
    {
      title: "Apple unveils new chips",
      site: "Reuters",
      published: "2026-05-30T12:00:00+00:00",
      url: "https://example.com/news",
    },
  ],
  drivers: ["High gross margins and durable franchise"],
  risk_flags: ["Trades at a rich multiple vs peers"],
  data_quality: {
    coverage: 0.85,
    sources: [
      { field: "pe", source: "yfinance", as_of: null, coverage: 1 },
      { field: "quality", source: "yfinance", as_of: null, coverage: 1 },
      { field: "analyst", source: "yfinance", as_of: null, coverage: 1 },
    ],
    warnings: ["fmp_key_missing"],
  },
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
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/research/fact_pack/")) {
        return envelope({
          data: { fact_pack: FACT_PACK },
          error: null,
          meta: { request_id: "r-fp" },
        });
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
    expect(
      screen.getByRole("textbox", { name: /ticker symbol/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/search a ticker above/i)).toBeInTheDocument();
  });

  it("paints the fact pack cockpit and the AI verdict after a search", async () => {
    routeFetch({
      body: {
        data: { verdict: VERDICT, fact_pack: FACT_PACK },
        error: null,
        meta: { request_id: "r-v" },
      },
    });

    const user = userEvent.setup();
    renderWithQuery(<ResearchPage />);

    await user.type(
      screen.getByRole("textbox", { name: /ticker symbol/i }),
      "aapl",
    );
    await user.click(screen.getByRole("button", { name: /research/i }));

    // Header + identity.
    expect(
      (await screen.findAllByText(/apple inc\./i)).length,
    ).toBeGreaterThanOrEqual(1);
    // Valuation band pill.
    expect(screen.getByText(/^rich$/i)).toBeInTheDocument();
    // A source badge (free data → "Yahoo (free)").
    expect(screen.getAllByText(/yahoo \(free\)/i).length).toBeGreaterThanOrEqual(1);
    // A pre-written driver string, rendered verbatim.
    expect(
      screen.getByText(/high gross margins and durable franchise/i),
    ).toBeInTheDocument();
    // Unit-correctness of a couple of ratio fields.
    expect(screen.getByText("2.5%")).toBeInTheDocument(); // dividend yield
    expect(screen.getByText("0.32")).toBeInTheDocument(); // debt/equity ratio
    // AI verdict.
    expect(
      await screen.findByText(/durable franchise at a fair multiple/i),
    ).toBeInTheDocument();
    expect(screen.getByText("88/100")).toBeInTheDocument(); // quality dimension
    // Peer comparison + news.
    expect(screen.getByText(/peer comparison/i)).toBeInTheDocument();
    expect(screen.getByText(/apple unveils new chips/i)).toBeInTheDocument();
  });

  it("shows the upgrade CTA on a quota_exceeded verdict, keeping the data", async () => {
    routeFetch({
      body: {
        data: null,
        error: {
          code: "quota_exceeded",
          message: "Monthly analysis quota exhausted.",
        },
        meta: { request_id: "r-q" },
      },
      status: 429,
    });

    const user = userEvent.setup();
    renderWithQuery(<ResearchPage />);

    await user.type(
      screen.getByRole("textbox", { name: /ticker symbol/i }),
      "aapl",
    );
    await user.click(screen.getByRole("button", { name: /research/i }));

    // Fact pack still painted.
    expect(
      (await screen.findAllByText(/apple inc\./i)).length,
    ).toBeGreaterThanOrEqual(1);
    // Verdict replaced by the upgrade CTA.
    expect(
      await screen.findByText(/used your ai analysis quota/i),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /see plans/i });
    expect(link).toHaveAttribute("href", "/pricing");
  });
});
