/** SaveAsPlan — builds a valid create payload (metric snapshots as baseline +
 * expected_impact), guards a null portfolio, saves an ANALYSIS not an order. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const createMutate = vi.fn();
vi.mock("@/lib/queries", () => ({ useCreateRiskPlan: () => ({ mutate: createMutate, isPending: false, isError: false }) }));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

import { SaveAsPlan } from "./save-as-plan";
import type { ScoreResponse } from "@/lib/schemas";

const baseline = { overall_score: 700, metrics: { annual_volatility: 0.3 } } as unknown as ScoreResponse;
const sandbox = { overall_score: 750, metrics: { annual_volatility: 0.2 } } as unknown as ScoreResponse;

afterEach(() => vi.clearAllMocks());

describe("SaveAsPlan", () => {
  it("prompts to select a portfolio when none is active", () => {
    render(<SaveAsPlan portfolioId={null} source="scenario" baseline={baseline} sandbox={sandbox} />);
    expect(screen.getByText(/Select a portfolio/)).toBeInTheDocument();
  });

  it("saves a plan with baseline + expected_impact metric snapshots", async () => {
    render(
      <SaveAsPlan
        portfolioId="pf1"
        source="scenario"
        baseline={baseline}
        sandbox={sandbox}
        proposedChanges={{ rows: [{ ticker: "SPY", market_value: "1000" }] }}
      />,
    );
    await userEvent.type(screen.getByLabelText("Plan title"), "Trim risk");
    await userEvent.click(screen.getByRole("button", { name: "Save plan" }));
    const [body] = createMutate.mock.calls[0];
    expect(body.portfolio_id).toBe("pf1");
    expect(body.title).toBe("Trim risk");
    expect(body.source).toBe("scenario");
    expect(body.baseline).toEqual({ overall_score: 700, annual_volatility: 0.3 });
    expect(body.expected_impact).toEqual({ overall_score: 750, annual_volatility: 0.2 });
    expect(body.proposed_changes).toEqual({ rows: [{ ticker: "SPY", market_value: "1000" }] });
  });
});
