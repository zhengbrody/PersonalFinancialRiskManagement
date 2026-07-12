/**
 * ActionSimulate: renders deterministic risk-lever cards with expected impact +
 * trade-offs; a "Simulate" toggle reveals the proposed book; NEVER executes a
 * trade; falls back to the educational cards when there are no levers.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ActionSimulate as ActionSimulateT } from "@/lib/queries";

const hookState: { data: ActionSimulateT | undefined; isLoading: boolean; isError: boolean } = {
  data: undefined,
  isLoading: false,
  isError: false,
};

vi.mock("@/lib/queries", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/queries")>()),
  useSimulateActions: () => hookState,
}));

import { ActionSimulate } from "./action-simulate";

const CARDS: ActionSimulateT = {
  baseline_score: 560,
  baseline_var_95_daily: 0.03,
  baseline_cvar_95_daily: 0.045,
  actions: [
    {
      key: "reduce_concentration",
      title: "Trim your largest position",
      rationale: "NVDA is 60% of your portfolio.",
      proposed_change: "Simulate trimming NVDA to 25% of your portfolio and holding cash.",
      expected_score_delta: 40,
      expected_score_after: 600,
      expected_var_delta: -0.008,
      expected_cvar_delta: -0.01,
      trade_offs: ["Lowers single-name risk but trims upside."],
      assumptions: ["The trimmed amount moves to cash."],
      simulate_holdings: [
        { ticker: "NVDA", market_value: 25000, asset_type: "public_security" },
        { ticker: "CASH", market_value: 35000, asset_type: "cash" },
      ],
      disclaimer: "Educational, not financial advice. Simulation only — nothing is traded.",
    },
  ],
};

afterEach(() => {
  hookState.data = undefined;
  hookState.isLoading = false;
  hookState.isError = false;
  vi.restoreAllMocks();
});

describe("ActionSimulate", () => {
  it("renders a lever with its expected impact + trade-offs", () => {
    hookState.data = CARDS;
    render(<ActionSimulate />);
    expect(screen.getByText("Trim your largest position")).toBeInTheDocument();
    expect(screen.getByText(/\+40 → 600/)).toBeInTheDocument(); // score delta → after
    expect(screen.getByText("Trade-offs")).toBeInTheDocument();
    expect(screen.getByText(/Lowers single-name risk/)).toBeInTheDocument();
    // never-executes messaging present (intro + card disclaimer)
    expect(screen.getAllByText(/nothing is traded/).length).toBeGreaterThan(0);
  });

  it("reveals the proposed book on Simulate (no trade executed)", () => {
    hookState.data = CARDS;
    render(<ActionSimulate />);
    expect(screen.queryByText(/Simulated portfolio/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Simulate this change/ }));
    expect(screen.getByText(/Simulated portfolio \(nothing is traded\)/)).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("$25,000")).toBeInTheDocument();
  });

  it("falls back to the educational cards when there are no levers", () => {
    hookState.data = { ...CARDS, actions: [] };
    render(<ActionSimulate fallback={<div>educational fallback</div>} />);
    expect(screen.getByText("educational fallback")).toBeInTheDocument();
    expect(screen.queryByText("Trim your largest position")).not.toBeInTheDocument();
  });
});
