/** RiskPlansPanel — list, review verdict, empty state, hidden on 503. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const plansMock = vi.fn();
const reviewMutate = vi.fn();
vi.mock("@/lib/queries", () => ({
  useRiskPlans: () => plansMock(),
  useReviewPlan: () => ({ mutate: reviewMutate, isPending: false }),
  useUpdateRiskPlan: () => ({ mutate: vi.fn() }),
  useDeleteRiskPlan: () => ({ mutate: vi.fn() }),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

import { RiskPlansPanel } from "./risk-plans-panel";

const PLAN = {
  id: "p1",
  portfolio_id: "pf1",
  title: "Trim NVDA",
  status: "draft",
  source: "scenario",
  hypothesis: "Cutting NVDA lowers vol",
  baseline: { annual_volatility: 0.3 },
  proposed_changes: {},
  expected_impact: {},
  data_confidence: {},
  created_at: "2026-07-01T00:00:00Z",
};

afterEach(() => vi.clearAllMocks());

describe("RiskPlansPanel", () => {
  it("does not compare a captured calculation against unrelated current-score metrics", () => {
    plansMock.mockReturnValue({ data: { plans: [{ ...PLAN, source: "copilot", data_confidence: { calculation_id: PLAN.id } }] }, isLoading: false, isError: false });
    render(<RiskPlansPanel portfolioId="pf1" currentScore={null} />);
    expect(screen.queryByRole("button", { name: "Review" })).not.toBeInTheDocument();
    expect(screen.getByText(/outcome review is not available yet/)).toBeVisible();
    expect(reviewMutate).not.toHaveBeenCalled();
  });
  it("shows an empty state when there are no plans", () => {
    plansMock.mockReturnValue({ data: { plans: [] }, isLoading: false, isError: false });
    render(<RiskPlansPanel portfolioId="pf1" currentScore={null} />);
    expect(screen.getByText(/No saved plans yet/)).toBeInTheDocument();
  });

  it("renders a plan and runs a review showing the verdict", async () => {
    plansMock.mockReturnValue({ data: { plans: [PLAN] }, isLoading: false, isError: false });
    reviewMutate.mockImplementation((_body, opts) =>
      opts.onSuccess({
        verdict: "improved",
        confidence: "high",
        metrics: [{ metric: "annual_volatility", baseline: 0.3, current: 0.2, delta: -0.1, improved: true }],
        missing_data: [],
        disclaimer: "Educational only.",
      }),
    );
    render(<RiskPlansPanel portfolioId="pf1" currentScore={{ overall_score: 700, metrics: {} } as never} />);
    expect(screen.getByText("Trim NVDA")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Review/ }));
    expect(screen.getByText("improved")).toBeInTheDocument();
    expect(screen.getByText(/annual volatility/)).toBeInTheDocument();
    expect(screen.getByText(/↓ better/)).toBeInTheDocument();
  });

  it("hides entirely when the feature is not provisioned (isError)", () => {
    plansMock.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    const { container } = render(<RiskPlansPanel portfolioId="pf1" currentScore={null} />);
    expect(container.innerHTML).toBe("");
  });
});
