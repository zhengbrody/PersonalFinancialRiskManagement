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
  score: { data: { overall_score: 782, metrics: { confidence: "high" }, data_confidence: null }, isLoading: false, isError: false },
  journey: { data: { first_score_at: "x", first_stress_test_at: "x", first_plan_at: "x", first_driver_viewed_at: "x", first_plan_reviewed_at: "x" } },
  plans: { data: { plans: [] } },
  insights: { data: { portfolio_available: true, insights: [] } },
  lastSnapshot: { data: { snapshot: { overall_score: 782 } } },
};

vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { id: "u1", email: "a@b.c" } }) }));
vi.mock("@/lib/portfolio-context", () => ({ usePortfolioContext: () => ctx }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/components/market-regime", () => ({ MarketRegime: () => <div>market-regime</div> }));
vi.mock("@/components/score-gauge", () => ({ ScoreGauge: () => <div>gauge</div> }));
vi.mock("@/lib/queries", () => ({
  useActiveScore: () => state.score,
  useJourney: () => state.journey,
  useRiskPlans: () => state.plans,
  useCopilotInsights: () => state.insights,
  useLastSnapshot: () => state.lastSnapshot,
}));

import { Today } from "./today";

beforeEach(() => {
  ctx.hasPortfolios = true;
  ctx.current = { id: "pf1", name: "Book A", holdings: { SPY: { shares: 1 } } };
  ctx.activePortfolioId = "pf1";
  state.score = { data: { overall_score: 782, metrics: { confidence: "high" }, data_confidence: null }, isLoading: false, isError: false };
  state.journey = { data: { first_score_at: "x", first_stress_test_at: "x", first_plan_at: "x", first_driver_viewed_at: "x", first_plan_reviewed_at: "x" } };
  state.plans = { data: { plans: [] } };
  state.insights = { data: { portfolio_available: true, insights: [] } };
  state.lastSnapshot = { data: { snapshot: { overall_score: 782 } } };
});
afterEach(() => vi.clearAllMocks());

describe("Today", () => {
  it("a new user (no portfolio) is told to create one, and the journey shows", () => {
    ctx.hasPortfolios = false;
    ctx.current = null as never;
    ctx.activePortfolioId = null;
    state.score = { data: null, isLoading: false, isError: true } as never;
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
    state.lastSnapshot = { data: { snapshot: { overall_score: 850 } } }; // was 850, now 782 → down 68
    render(<Today />);
    // The primary explains the drop; the redundant since-last-visit strip is hidden.
    expect(screen.getByText("Your health score dropped")).toBeInTheDocument();
    expect(screen.queryByText(/health score is down/)).not.toBeInTheDocument();
  });

  it("a small non-drop change shows the since-last-visit strip (no primary drop)", () => {
    state.lastSnapshot = { data: { snapshot: { overall_score: 770 } } }; // was 770, now 782 → up 12
    render(<Today />);
    expect(screen.getByText(/health score is up/)).toBeInTheDocument();
    expect(screen.getByText(/12 pts/)).toBeInTheDocument();
  });
});
