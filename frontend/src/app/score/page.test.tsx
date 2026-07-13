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
      screen.getByRole("heading", { name: /score any portfolio/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/no score yet/i)).toBeInTheDocument();
  });

  it("renders the result panel on a successful response", async () => {
    mockEnvelope({
      data: {
        overall_score: 712,
        analysis_mode: "synthetic_demo",
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
    expect(screen.getByText(/illustrative portfolio health score/i)).toBeInTheDocument();
    expect(screen.getByText(/seeded synthetic returns, not live history/i)).toBeInTheDocument();
    expect(screen.queryByText(/how you compare/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/illustrative synthetic returns — not live market history/i),
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

  it("shows the Margin & cash impact callout for a leveraged book", async () => {
    mockEnvelope({
      data: {
        overall_score: 640,
        risk_preference: 3,
        risk_target: {},
        metrics: {
          annual_return: 0.04, // levered/equity-level return (dragged by borrow)
          annual_volatility: 0.3,
          sharpe_ratio: 0.9, // POSITIVE asset-mix Sharpe despite leverage
          max_drawdown: -0.2,
          var_95_daily: -0.03,
          cvar_95_daily: -0.04,
          beta_to_benchmark: 1.4,
          total_value: 200000,
          cash_weight: 0,
          data_coverage: 1,
          observations: 252,
          data_quality_notes: [],
          leverage: 2.0,
          gross_annual_return: 0.085, // unlevered asset-mix return
          margin_cost_annual: 0.045,
        },
        dimensions: {
          risk_match: { name: "Risk Match", score: 5, status: "ok", detail: "" },
          risk_adjusted_return: { name: "Risk-Adjusted Return", score: 6, status: "ok", detail: "" },
          downside_protection: { name: "Downside Protection", score: 4, status: "watch", detail: "" },
        },
      },
      error: null,
      meta: { request_id: "rid", elapsed_ms: 10 },
    });

    const user = userEvent.setup();
    renderWithQuery(<ScorePage />);
    await user.click(screen.getByRole("button", { name: /run score/i }));

    // Sharpe is labeled as asset-mix quality and stays positive.
    expect(await screen.findByText(/asset-mix quality/i)).toBeInTheDocument();
    // The leverage cost is surfaced separately, not hidden in the Sharpe.
    expect(screen.getByText(/margin & cash impact/i)).toBeInTheDocument();
    expect(screen.getByText("2.00×")).toBeInTheDocument();
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

    expect(
      await screen.findByText(/something went wrong/i),
    ).toBeInTheDocument();
    // The backend message still surfaces; the raw status/code dump was removed.
    expect(
      screen.getByText(/holdings must not be empty/i),
    ).toBeInTheDocument();
  });
});
