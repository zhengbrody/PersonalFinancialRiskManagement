import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfidenceBadge, ReasonCodes, ScoreChangeReport } from "./score-change-report";
import type { ScoreResponse } from "@/lib/schemas";

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

const mockUse = vi.fn();
vi.mock("@/lib/queries", () => ({
  useScoreChanges: (b: unknown) => mockUse(b),
}));

function metrics(over: Record<string, unknown> = {}): ScoreResponse["metrics"] {
  return {
    annual_return: 0.1,
    annual_volatility: 0.15,
    sharpe_ratio: 0.8,
    max_drawdown: 0.12,
    var_95_daily: 0.013,
    cvar_95_daily: 0.02,
    beta_to_benchmark: 0.9,
    total_value: 100000,
    net_equity: 100000,
    cash_weight: 0,
    data_coverage: 1,
    observations: 252,
    data_quality_notes: [],
    confidence: "high",
    ...over,
  } as unknown as ScoreResponse["metrics"];
}

function score(over: Partial<ScoreResponse> = {}): ScoreResponse {
  return {
    overall_score: 500,
    base_overall: 500,
    risk_preference: 3,
    risk_target: {},
    metrics: metrics(),
    dimensions: {
      risk_match: { name: "Risk Match", score: 6, status: "Good", detail: "" },
      risk_adjusted_return: { name: "Risk-adjusted Return", score: 6, status: "Good", detail: "" },
      downside_protection: { name: "Downside Protection", score: 6, status: "Good", detail: "" },
    },
    ...over,
  } as unknown as ScoreResponse;
}

describe("ConfidenceBadge", () => {
  it("renders nothing when confidence is high", () => {
    const { container } = render(<ConfidenceBadge metrics={metrics({ confidence: "high" })} />);
    expect(container.firstChild).toBeNull();
  });

  it("warns and shows the stabilized-from score when confidence is low", () => {
    render(
      <ConfidenceBadge
        metrics={metrics({ confidence: "low", data_quality: 0.4, dropped_tickers: ["CCC"] })}
        baseOverall={70}
        overall={291}
      />,
    );
    expect(screen.getByText(/low data confidence/i)).toBeInTheDocument();
    expect(screen.getByText(/stabilized toward neutral \(raw 70\)/i)).toBeInTheDocument();
    expect(screen.getByText(/missing price data for CCC/i)).toBeInTheDocument();
  });
});

describe("ReasonCodes", () => {
  it("renders deterministic reasons but hides low_data_confidence (shown by the badge)", () => {
    render(
      <ReasonCodes
        score={score({
          reason_codes: [
            { code: "low_data_confidence", severity: "high", detail: "hidden here" },
            { code: "weak_risk_adjusted_return", severity: "watch", detail: "Sharpe is low" },
          ],
        })}
      />,
    );
    expect(screen.getByText(/Sharpe is low/)).toBeInTheDocument();
    expect(screen.queryByText(/hidden here/)).not.toBeInTheDocument();
  });

  it("renders nothing without material reasons", () => {
    const { container } = render(<ReasonCodes score={score({ reason_codes: [] })} />);
    expect(container.firstChild).toBeNull();
  });
});

describe("ScoreChangeReport", () => {
  it("renders the deterministic summary, score delta, and top driver", () => {
    mockUse.mockReturnValue({
      isLoading: false,
      data: {
        window: "previous",
        available: true,
        as_of_previous: "2026-06-13T00:00:00Z",
        current_score: 306,
        previous_score: 500,
        score_delta: -194,
        component_deltas: [],
        input_changes: [],
        top_drivers: [
          { key: "risk_adjusted_return", label: "Risk-adjusted Return", points: -194, detail: "Risk-adjusted Return 6.0 → 1.0/10" },
        ],
        data_quality_changes: [],
        holdings_changes: { added: [], removed: [], reweighted: [] },
        summary: "Health score fell 194 pts since 2026-06-13, mostly Risk-adjusted Return (-194 pts).",
      },
    });
    render(<ScoreChangeReport score={score()} />);
    expect(screen.getByText(/Health score fell 194 pts/)).toBeInTheDocument();
    expect(screen.getByText("-194")).toBeInTheDocument();
    expect(screen.getByText("-194 pts")).toBeInTheDocument();
    expect(screen.getByText(/Risk-adjusted Return 6.0 → 1.0\/10/)).toBeInTheDocument();
  });

  it("shows a graceful message when no snapshot exists in the window", () => {
    mockUse.mockReturnValue({
      isLoading: false,
      data: { window: "30d", available: false, current_score: 500, summary: "", component_deltas: [], input_changes: [], top_drivers: [], data_quality_changes: [], holdings_changes: { added: [], removed: [], reweighted: [] } },
    });
    render(<ScoreChangeReport score={score()} />);
    expect(screen.getByText(/No earlier snapshot yet/i)).toBeInTheDocument();
  });

  it("blocks a cross-version comparison: shows the methodology notice, hides the delta", () => {
    mockUse.mockReturnValue({
      isLoading: false,
      data: {
        window: "previous",
        available: true,
        as_of_previous: "2026-06-13T00:00:00Z",
        current_score: 500,
        previous_score: 560,
        score_delta: null, // backend refuses a comparable delta
        component_deltas: [],
        input_changes: [],
        top_drivers: [],
        data_quality_changes: [],
        holdings_changes: { added: [], removed: [], reweighted: [] },
        summary: "Methodology changed since your earlier score …",
        comparable: false,
        previous_score_version: "mindmarket-score-v0.9.0",
        current_score_version: "mindmarket-score-v1.0.0",
      },
    });
    render(<ScoreChangeReport score={score()} />);
    // The required notice is present…
    expect(
      screen.getByText(/Methodology changed; score delta is not directly comparable/i),
    ).toBeInTheDocument();
    // …the two raw scores still show (current 500, previous 560)…
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText(/560/)).toBeInTheDocument();
    // …with the version transition, but NO delta chip.
    expect(screen.getByText(/v0\.9\.0/)).toBeInTheDocument();
    expect(screen.queryByText("-60")).not.toBeInTheDocument();
    expect(screen.queryByText("+60")).not.toBeInTheDocument();
  });
});
