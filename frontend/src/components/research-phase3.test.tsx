import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const useEarnings = vi.fn();
const useThesis = vi.fn();
const useAnalystReport = vi.fn();
vi.mock("@/lib/queries", () => ({
  useEarnings: () => useEarnings(),
  useThesis: () => useThesis(),
  useAnalystReport: () => useAnalystReport(),
}));

import { EarningsComparison } from "./earnings-comparison";
import { ResearchThesis } from "./research-thesis";
import { AnalystReportView } from "./analyst-report";

const EARNINGS = {
  earnings: {
    ticker: "AAPL",
    as_of: "2024-12-28",
    periods: [
      {
        period: "2024-Q4",
        revenue: 120e9,
        revenue_yoy: 0.06,
        revenue_qoq: 0.02,
        eps: 2.4,
        eps_yoy: 0.1,
        revenue_beat: true,
        eps_beat: false,
      },
    ],
    transcript: { available: false, excerpt_length: 0 },
    summary: { headline: "Revenue +6% YoY", points: [], ai_generated: false },
    missing_data: [{ dataset: "earnings_estimates", reason: "actuals_only" }],
    disclaimer: "Educational only — not investment advice.",
  },
};

beforeEach(() => {
  useEarnings.mockReturnValue({ isLoading: false, isError: false, data: EARNINGS });
  useThesis.mockReturnValue({ data: undefined, mutate: vi.fn(), isPending: false, isError: false });
  useAnalystReport.mockReturnValue({ isLoading: false, isError: false, data: undefined });
});

describe("EarningsComparison", () => {
  it("renders the quarter comparison + beat/miss + missing data", () => {
    render(<EarningsComparison ticker="AAPL" />);
    expect(screen.getByText("Quarter comparison")).toBeInTheDocument();
    expect(screen.getByText("Beat")).toBeInTheDocument(); // revenue beat
    expect(screen.getByText("Miss")).toBeInTheDocument(); // eps miss
    expect(screen.getByText(/missing data/i)).toBeInTheDocument();
  });

  it("shows a loading skeleton", () => {
    useEarnings.mockReturnValue({ isLoading: true, isError: false, data: undefined });
    render(<EarningsComparison ticker="AAPL" />);
    expect(screen.queryByText("Quarter comparison")).not.toBeInTheDocument();
  });
});

describe("ResearchThesis", () => {
  it("shows the build CTA before generation", () => {
    render(<ResearchThesis ticker="AAPL" />);
    expect(screen.getByRole("button", { name: /build the bull \/ bear debate/i })).toBeInTheDocument();
  });

  it("renders the grounded bull/bear debate when present", () => {
    useThesis.mockReturnValue({
      data: {
        thesis: {
          ticker: "AAPL",
          bull_case: ["Durable franchise"],
          bear_case: ["Rich multiple"],
          key_debate: "DCF base vs price",
          what_would_change_view: [],
          monitor_next_quarter: ["Next print"],
          questions_for_management: [],
          red_flags: [],
          ai_generated: true,
          flagged_numbers: [],
          warnings: [],
          disclaimer: "Not investment advice.",
        },
      },
      mutate: vi.fn(),
      isPending: false,
      isError: false,
    });
    render(<ResearchThesis ticker="AAPL" />);
    expect(screen.getByText("Bull case")).toBeInTheDocument();
    expect(screen.getByText("Durable franchise")).toBeInTheDocument();
    expect(screen.getByText("AI-generated")).toBeInTheDocument();
  });
});

describe("AnalystReportView", () => {
  it("renders the report preview + section chips", () => {
    useAnalystReport.mockReturnValue({
      isLoading: false,
      isError: false,
      data: {
        report: {
          ticker: "AAPL",
          title: "Apple Inc. (AAPL) — Research report",
          as_of: "2024-12-28",
          html: "<html><body>report</body></html>",
          sections: [{ key: "snapshot", title: "Company snapshot", included: true }],
          disclaimer: "Not advice.",
        },
      },
    });
    render(<AnalystReportView ticker="AAPL" />);
    expect(screen.getByText(/Apple Inc\. \(AAPL\)/)).toBeInTheDocument();
    expect(screen.getByText("Company snapshot")).toBeInTheDocument();
    expect(screen.getByTitle(/research report/i)).toBeInTheDocument(); // the iframe
    expect(screen.getByRole("button", { name: /download html/i })).toBeInTheDocument();
  });

  it("shows a loading skeleton", () => {
    useAnalystReport.mockReturnValue({ isLoading: true, isError: false, data: undefined });
    render(<AnalystReportView ticker="AAPL" />);
    expect(screen.queryByText(/research report/i)).not.toBeInTheDocument();
  });
});
