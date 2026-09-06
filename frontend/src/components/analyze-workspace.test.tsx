/** AnalyzeWorkspace — URL-driven tabs, lazy stage mounting, and the visited
 * panels staying rendered. Heavy children + data hooks are stubbed so this
 * isolates the workspace SHELL logic. */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const pushMock = vi.fn();
const searchState = { view: "overview" as string | null };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(searchState.view ? `view=${searchState.view}` : ""),
}));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: { id: "u1" }, loading: false, configured: true }),
}));
vi.mock("@/lib/portfolio-context", () => ({
  usePortfolioContext: () => ({ current: { id: "pf1", name: "Book A" }, activePortfolioId: "pf1" }),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/lib/risk-explain-input", () => ({ explainInputFromScore: () => ({}) }));
vi.mock("@/lib/use-run-once-per-user", () => ({
  useRunOncePerUser: (_key: string, run: () => void) => {
    runOnceCallback = run;
  },
  runKeyForActivePortfolio: () => "u1:pf1",
}));

const recordMutate = vi.fn();
const historicalMutate = vi.fn();
let runOnceCallback: (() => void) | null = null;
let whatIfSuccess: (() => void) | undefined;
vi.mock("@/lib/queries", () => ({
  useActiveScore: () => ({ data: { overall_score: 720, metrics: {}, data_confidence: null }, isLoading: false, isError: false }),
  useLastSnapshot: () => ({ data: undefined }),
  useRiskExplain: () => ({ data: undefined, isLoading: false }),
  useRiskReport: () => ({ data: undefined, isPending: false, isError: false, reset: vi.fn(), mutate: vi.fn() }),
  useHistoricalScenarios: () => ({ data: undefined, isPending: false, isError: false, reset: vi.fn(), mutate: historicalMutate }),
  useRecordMilestone: () => ({ mutate: recordMutate }),
}));

// Stub heavy children so the shell renders without their data plumbing.
// Only the presentational gauge is stubbed — `scoreBand` stays real so the
// band label the Overview renders is actually exercised.
vi.mock("@/components/score-gauge", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/score-gauge")>()),
  ScoreGauge: () => <div>score-gauge</div>,
}));
vi.mock("@/components/risk-diagnosis", () => ({ RiskDiagnosis: () => <div>diagnosis</div> }));
vi.mock("@/components/data-confidence", () => ({ DataConfidence: () => <div>confidence</div> }));
vi.mock("@/components/risk-report", () => ({
  ReportSections: () => <div>report-sections</div>,
  ResultSkeleton: () => <div>skeleton</div>,
  RiskErrorPanel: () => <div>error</div>,
}));
vi.mock("@/components/historical-scenarios", () => ({ HistoricalScenarios: () => <div>historical</div> }));
vi.mock("@/components/metric-trend", () => ({ MetricTrend: () => <div>metric-trend</div> }));
vi.mock("@/components/score-change-report", () => ({ ScoreChangeReport: () => <div>score-change</div> }));
vi.mock("@/components/action-simulate", () => ({ ActionSimulate: () => <div>action-simulate</div> }));
vi.mock("@/components/whatif-lab", () => ({
  WhatIfLab: ({ onRunSuccess }: { onRunSuccess?: () => void }) => {
    whatIfSuccess = onRunSuccess;
    return <div>whatif-lab</div>;
  },
}));
vi.mock("@/components/save-as-plan", () => ({ SaveAsPlan: () => <div>save-as-plan</div> }));
vi.mock("@/components/risk-plans-panel", () => ({ RiskPlansPanel: () => <div>risk-plans-panel</div> }));

import { AnalyzeWorkspace, weakestDimension } from "./analyze-workspace";

beforeEach(() => {
  searchState.view = "overview";
  pushMock.mockClear();
  recordMutate.mockClear();
  historicalMutate.mockClear();
  runOnceCallback = null;
  whatIfSuccess = undefined;
});
afterEach(() => vi.clearAllMocks());

describe("AnalyzeWorkspace", () => {
  it("reads the weakest dimension from the current API contract", () => {
    expect(weakestDimension({ dimensions: {
      risk_match: { name: "Risk match", score: 7, status: "ok", detail: "" },
      concentration: { name: "Concentration", score: 2, status: "poor", detail: "" },
    } })).toBe("Concentration");
    expect(weakestDimension({ dimensions: {} })).toBeNull();
  });
  it("offers the next stage without claiming an analysis was completed", async () => {
    render(<AnalyzeWorkspace />);
    await userEvent.click(screen.getByRole("button", { name: "Explore risk drivers" }));
    expect(pushMock).toHaveBeenCalledWith("/analyze?view=drivers");
    expect(recordMutate).not.toHaveBeenCalledWith("first_stress_test_at");
  });
  it("renders the 5 stage tabs and shows the active book name", () => {
    render(<AnalyzeWorkspace />);
    for (const label of ["Overview", "Drivers", "Stress Test", "Action Plan", "History"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("heading", { name: "Book A" })).toBeInTheDocument();
  });

  it("shows the Overview stage by default and drives the tab from ?view=", () => {
    render(<AnalyzeWorkspace />);
    // Overview stage content (score gauge) is visible.
    expect(screen.getByText("score-gauge")).toBeInTheDocument();
    // The gauge only draws the band — the headline number must be rendered too.
    expect(screen.getByTestId("analyze-overall-score")).toHaveTextContent("720");
    expect(screen.getByText("Healthy")).toBeInTheDocument();
    // Unvisited stages have NOT mounted yet (lazy).
    expect(screen.queryByText("report-sections")).not.toBeInTheDocument();
    expect(recordMutate).toHaveBeenCalledWith("first_score_at");
  });

  it("switching a tab pushes the new view to the URL", async () => {
    render(<AnalyzeWorkspace />);
    await userEvent.click(screen.getByRole("tab", { name: "Drivers" }));
    expect(pushMock).toHaveBeenCalledWith(expect.stringContaining("view=drivers"));
  });

  it("renders the correct stage when ?view targets it", () => {
    searchState.view = "plan";
    render(<AnalyzeWorkspace />);
    expect(screen.getByText("action-simulate")).toBeInTheDocument();
    expect(screen.getByText("risk-plans-panel")).toBeInTheDocument();
  });

  it("records stress only after an explicit what-if succeeds", () => {
    searchState.view = "stress";
    render(<AnalyzeWorkspace />);

    act(() => runOnceCallback?.());
    const options = historicalMutate.mock.calls[0]?.[1] as
      | { onSuccess?: () => void }
      | undefined;
    act(() => options?.onSuccess?.());
    expect(recordMutate).not.toHaveBeenCalledWith("first_stress_test_at");

    act(() => whatIfSuccess?.());
    expect(recordMutate).toHaveBeenCalledWith("first_stress_test_at");
  });
});
