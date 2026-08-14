/** Today — the deterministic action center: primary action from state, the
 * onboarding journey (next-step highlight, hidden when done), since-last-visit,
 * and the score testid the e2e relies on. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const ctx = {
  hasPortfolios: true,
  current: { id: "pf1", name: "Book A", holdings: { SPY: { shares: 1 } } },
  activePortfolioId: "pf1" as string | null,
  isLoading: false,
};
const state = {
  score: { data: { overall_score: 782, metrics: { confidence: "high" }, data_confidence: null }, isLoading: false, isError: false, refetch: vi.fn() },
  journey: { data: { first_score_at: "x", first_stress_test_at: "x", first_plan_at: "x", first_driver_viewed_at: "x", first_plan_reviewed_at: "x" }, isLoading: false, isError: false, refetch: vi.fn() },
  plans: { data: { plans: [] }, isLoading: false, isError: false, refetch: vi.fn() },
  insights: { data: { portfolio_available: true, insights: [] }, isLoading: false, isError: false, refetch: vi.fn() },
  riskFit: { data: { confirmed: true, risk_tolerance: 3 }, isLoading: false, isError: false, refetch: vi.fn() },
  scoreChanges: { data: { available: false }, isLoading: false, isError: false, refetch: vi.fn() },
};

type TestUser = { id: string; email: string; user_metadata?: { username?: string } };
const auth: { user: TestUser } = { user: { id: "u1", email: "risk.owner@example.com" } };

vi.mock("@/lib/auth-context", () => ({ useAuth: () => auth }));
vi.mock("@/lib/portfolio-context", () => ({ usePortfolioContext: () => ctx }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/components/market-regime", () => ({ MarketRegime: () => <div>market-regime</div> }));
vi.mock("@/components/score-gauge", () => ({ ScoreGauge: () => <div>gauge</div> }));
vi.mock("@/lib/queries", () => ({
  useActiveScore: () => state.score,
  useJourney: () => state.journey,
  useRiskPlans: () => state.plans,
  useCopilotInsights: () => state.insights,
  useCopilotPreferences: () => state.riskFit,
  useScoreChanges: () => state.scoreChanges,
}));

import { Today } from "./today";

beforeEach(() => {
  auth.user = { id: "u1", email: "risk.owner@example.com" };
  ctx.hasPortfolios = true;
  ctx.current = { id: "pf1", name: "Book A", holdings: { SPY: { shares: 1 } } };
  ctx.activePortfolioId = "pf1";
  state.score = { data: { overall_score: 782, metrics: { confidence: "high" }, data_confidence: null }, isLoading: false, isError: false, refetch: vi.fn() };
  state.journey = { data: { first_score_at: "x", first_stress_test_at: "x", first_plan_at: "x", first_driver_viewed_at: "x", first_plan_reviewed_at: "x" }, isLoading: false, isError: false, refetch: vi.fn() };
  state.plans = { data: { plans: [] }, isLoading: false, isError: false, refetch: vi.fn() };
  state.insights = { data: { portfolio_available: true, insights: [] }, isLoading: false, isError: false, refetch: vi.fn() };
  state.riskFit = { data: { confirmed: true, risk_tolerance: 3 }, isLoading: false, isError: false, refetch: vi.fn() };
  state.scoreChanges = { data: { available: false }, isLoading: false, isError: false, refetch: vi.fn() };
});
afterEach(() => vi.clearAllMocks());

describe("Today", () => {
  it("a new user (no portfolio) is told to create one, and the journey shows", () => {
    ctx.hasPortfolios = false;
    ctx.current = null as never;
    ctx.activePortfolioId = null;
    state.score = { data: null, isLoading: false, isError: true, refetch: vi.fn() } as never;
    render(<Today />);
    expect(screen.getByText("Add your first portfolio")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a portfolio" })).toHaveAttribute("href", "/portfolios/new");
    // Journey is visible (not all done).
    expect(screen.getByText("Getting started")).toBeInTheDocument();
  });

  it("a fully-set-up user gets 'review changes' and NO journey checklist", () => {
    render(<Today />);
    expect(screen.getByText("Review what changed")).toBeInTheDocument();
    expect(screen.queryByText("Getting started")).not.toBeInTheDocument();
    // Score testid is preserved for the e2e.
    expect(screen.getByTestId("dashboard-active-score")).toHaveTextContent("782");
  });

  it("a due risk plan becomes the primary action", () => {
    state.plans = {
      data: { plans: [{ id: "p1", status: "active", review_at: "2020-01-01T00:00:00Z", title: "T" }] },
    } as never;
    render(<Today />);
    expect(screen.getByText(/Review 1 risk plan/)).toBeInTheDocument();
  });

  it("a score drop becomes the primary 'explain the change' action (strip suppressed)", () => {
    state.scoreChanges = {
      data: { available: true, comparable: true, score_delta: -68, summary: "Concentration weakened the score.", top_negative_contributor: { label: "Concentration", points: -68 } },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never;
    render(<Today />);
    // The primary explains the drop; the redundant since-last-visit strip is hidden.
    expect(screen.getByText("Your health score dropped")).toBeInTheDocument();
    expect(screen.queryByText(/health score is down/)).not.toBeInTheDocument();
  });

  it("a small non-drop change shows the since-last-visit strip (no primary drop)", () => {
    state.scoreChanges = {
      data: { available: true, comparable: true, score_delta: 12, summary: "Diversification improved the score.", top_positive_contributor: { label: "Diversification", points: 12 } },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never;
    render(<Today />);
    expect(screen.getByText(/Diversification improved/)).toBeInTheDocument();
    expect(screen.getByText(/Top driver: Diversification/)).toBeInTheDocument();
    expect(screen.getByText(/12 pts/)).toBeInTheDocument();
  });

  it("blocks invented guidance when the active score fails", () => {
    state.score = { data: null, isLoading: false, isError: true, refetch: vi.fn() } as never;
    render(<Today />);
    expect(screen.getByRole("alert")).toHaveTextContent(/could not load your current score/i);
    expect(screen.queryByText("Review what changed")).not.toBeInTheDocument();
  });

  it("blocks query failures instead of treating unknown state as empty", () => {
    state.plans = { data: undefined, isLoading: false, isError: true, refetch: vi.fn() } as never;
    render(<Today />);
    expect(screen.getByRole("alert")).toHaveTextContent(/saved plans/i);
    expect(screen.getByRole("button", { name: /reload today context/i })).toBeInTheDocument();
    expect(screen.queryByText("Review what changed")).not.toBeInTheDocument();
  });

  it("waits for every priority input before rendering a recommendation", () => {
    state.insights = { ...state.insights, isLoading: true };
    render(<Today />);
    expect(screen.queryByText("Review what changed")).not.toBeInTheDocument();
  });

  it("never greets with the email address (no display name set)", () => {
    render(<Today />);
    const header = screen.getByRole("heading", { level: 1 });
    expect(header).toHaveTextContent("Hi, there");
    // The local part of the email must not leak into the chrome.
    expect(document.body.textContent).not.toContain("risk.owner");
  });

  it("greets with the display name the user chose on /settings", () => {
    auth.user = { ...auth.user, user_metadata: { username: "Brody" } };
    render(<Today />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Hi, Brody");
    expect(document.body.textContent).not.toContain("risk.owner");
  });

  it("does not accept an empty confirmed preference as completed Risk Fit", () => {
    state.riskFit = { data: { confirmed: true, risk_tolerance: null }, isLoading: false, isError: false, refetch: vi.fn() } as never;
    state.journey = { data: { ...state.journey.data, first_score_at: null }, isLoading: false, isError: false, refetch: vi.fn() } as never;
    render(<Today />);
    expect(screen.getByText("Set your Risk Fit")).toBeInTheDocument();
  });
});
