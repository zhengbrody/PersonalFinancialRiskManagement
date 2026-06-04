/**
 * ScorePage state-machine test.
 *
 * Covers the three observable UI states:
 *   1. empty   — pristine load shows "No score yet"
 *   2. result  — successful POST renders the score block
 *   3. error   — backend failure renders the destructive card
 *
 * `fetch` is mocked at the global level so we never hit a real backend
 * during CI.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

// Anonymous by default → the public manual sandbox (these tests cover that
// path). Signed-in auto-scoring of saved Holdings is exercised elsewhere.
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: null, configured: true, loading: false, accessToken: null }),
}));

import ScorePage from "./page";

function mockEnvelope(
  body: unknown,
  init: { status?: number } = {},
): ReturnType<typeof vi.spyOn> {
  return vi
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(
      new Response(JSON.stringify(body), {
        status: init.status ?? 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ScorePage", () => {
  it("renders the empty state by default", () => {
    renderWithQuery(<ScorePage />);
    expect(
      screen.getByRole("heading", { name: /portfolio score/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/no score yet/i)).toBeInTheDocument();
  });

  it("renders the result panel on a successful response", async () => {
    mockEnvelope({
      data: {
        overall_score: 712,
        risk_preference: 3,
        risk_target: {},
        metrics: {
          annual_return: 0.08,
          annual_volatility: 0.12,
          sharpe_ratio: 0.5,
          max_drawdown: -0.07,
          var_95_daily: -0.012,
          cvar_95_daily: -0.017,
          beta_to_benchmark: 0.78,
          total_value: 100000,
          cash_weight: 0,
          data_coverage: 1,
          observations: 252,
          data_quality_notes: ["returns matrix synthesised for testing"],
        },
        dimensions: {
          risk_match: { name: "Risk Match", score: 7.2, status: "good", detail: "beta is balanced" },
          risk_adjusted_return: {
            name: "Risk-Adjusted Return",
            score: 6.9,
            status: "good",
            detail: "",
          },
          downside_protection: {
            name: "Downside Protection",
            score: 8.2,
            status: "strong",
            detail: "",
          },
        },
      },
      error: null,
      meta: { request_id: "rid", elapsed_ms: 10 },
    });

    const user = userEvent.setup();
    renderWithQuery(<ScorePage />);

    await user.click(screen.getByRole("button", { name: /run score/i }));

    // The score hero + Overview (metrics) paint first.
    expect(await screen.findByText("712")).toBeInTheDocument();
    expect(
      screen.getByText(/returns matrix synthesised for testing/i),
    ).toBeInTheDocument();

    // Dimension driver cards live behind the Drivers tab now.
    await user.click(screen.getByRole("tab", { name: /drivers/i }));
    expect(await screen.findByText("Risk Match")).toBeInTheDocument();
    expect(screen.getByText("Risk-Adjusted Return")).toBeInTheDocument();
    expect(screen.getByText("Downside Protection")).toBeInTheDocument();

    // What Changed tab → no prior snapshot (anon) → friendly empty message.
    await user.click(screen.getByRole("tab", { name: /what changed/i }));
    expect(await screen.findByText(/no earlier snapshot yet/i)).toBeInTheDocument();
  });

  it("renders the error panel when the backend rejects", async () => {
    mockEnvelope(
      {
        data: null,
        error: {
          code: "validation_failed",
          message: "holdings must not be empty",
          details: {},
        },
        meta: { request_id: "rid-err" },
      },
      { status: 422 },
    );

    const user = userEvent.setup();
    renderWithQuery(<ScorePage />);
    await user.click(screen.getByRole("button", { name: /run score/i }));

    expect(await screen.findByText(/request failed/i)).toBeInTheDocument();
    expect(
      screen.getByText(/holdings must not be empty/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/validation_failed/i)).toBeInTheDocument();
  });
});
