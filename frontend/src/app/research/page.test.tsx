/**
 * `/research` Ticker Research two-stage flow.
 *
 * Branches asserted:
 *   1. empty state + search box render.
 *   2. searching a ticker paints the dossier dashboard AND the AI verdict.
 *   3. a quota_exceeded on the verdict shows the upgrade CTA while the
 *      dossier data stays visible.
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

// recharts' ResponsiveContainer renders nothing in jsdom (no layout). Stub
// the chart pieces as passthrough so the EarningsTrend card still renders.
vi.mock("recharts", () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => <div>{children}</div>;
  const Noop = () => null;
  return {
    ResponsiveContainer: Pass,
    ComposedChart: Pass,
    Bar: Noop,
    Line: Noop,
    XAxis: Noop,
    YAxis: Noop,
    CartesianGrid: Noop,
    Tooltip: Noop,
  };
});

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

const DOSSIER = {
  ticker: "AAPL",
  as_of: "2026-05-31T00:00:00+00:00",
  profile: { name: "Apple Inc.", sector: "Technology", industry: "Consumer Electronics" },
  market: { current_price: 200.5, market_cap: 3.1e12, beta: 1.2 },
  fundamentals: { pe_ttm: 30.1, roe: 1.5 },
  valuation: {},
  technicals: { rsi_14: 55 },
  ratings: {
    analyst_rating: "buy",
    analyst_count: 40,
    price_targets: { low: 180, mean: 240, high: 300, current: 200.5 },
  },
  ownership: { institutional_pct: 0.62 },
  earnings_quarterly: [
    { period: "2025-09-30", revenue: 9.0e10, net_income: 2.0e10, eps: 1.4 },
    { period: "2025-12-31", revenue: 1.0e11, net_income: 2.5e10, eps: 1.8 },
    { period: "2026-03-31", revenue: 1.1e11, net_income: 2.9e10, eps: 2.0 },
  ],
};

const ANALYSIS = {
  ticker: "AAPL",
  as_of: DOSSIER.as_of,
  verdict: {
    rating: "BUY",
    confidence: "high",
    target_weight_pct_band: "2-4%",
    thesis_one_liner: "Durable franchise at a fair multiple.",
  },
  dimensions: {
    quality: { score_0_100: 80, key_points: ["Wide moat"], evidence: [] },
    fundamentals: { score_0_100: 70, key_points: [], evidence: [] },
    growth: { score_0_100: 60, key_points: [], evidence: [] },
    technicals: { score_0_100: 55, key_points: [], evidence: [] },
    sentiment: { score_0_100: 65, key_points: [], evidence: [] },
  },
  catalysts_90d: ["Earnings beat"],
  risks: ["Valuation rich"],
  data_gaps: [],
  would_change_mind: ["A demand collapse"],
};

function routeFetch(analyze: { body: unknown; status?: number }) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/equity/dossier")) {
        return envelope({ data: { dossier: DOSSIER }, error: null, meta: { request_id: "r-d" } });
      }
      if (url.includes("/equity/analyze")) {
        return envelope(analyze.body, analyze.status ?? 200);
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

  it("paints the dossier and the AI verdict after a search", async () => {
    routeFetch({
      body: { data: { analysis: ANALYSIS, dossier: DOSSIER }, error: null, meta: { request_id: "r-a" } },
    });

    const user = userEvent.setup();
    renderWithQuery(<ResearchPage />);

    await user.type(screen.getByRole("textbox", { name: /ticker symbol/i }), "aapl");
    await user.click(screen.getByRole("button", { name: /research/i }));

    // Dossier data.
    expect((await screen.findAllByText(/the numbers/i)).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/apple inc\./i).length).toBeGreaterThanOrEqual(1);
    // AI verdict.
    expect(await screen.findByText(/durable franchise/i)).toBeInTheDocument();
    expect(screen.getByText("80/100")).toBeInTheDocument();
    // Wall Street consensus (analyst rating + targets + institutional %).
    expect(screen.getByText(/wall street consensus/i)).toBeInTheDocument();
    expect(screen.getByText(/40 analysts/i)).toBeInTheDocument();
    expect(screen.getByText(/institutions hold/i)).toBeInTheDocument();
    // Earnings trend chart card.
    expect(screen.getByText(/earnings trend/i)).toBeInTheDocument();
    expect(screen.getByTestId("earnings-chart")).toBeInTheDocument();
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

    // Dossier still painted.
    expect(await screen.findByText(/the numbers/i)).toBeInTheDocument();
    // Verdict replaced by the upgrade CTA.
    expect(await screen.findByText(/used your ai analysis quota/i)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /see plans/i });
    expect(link).toHaveAttribute("href", "/pricing");
  });
});
