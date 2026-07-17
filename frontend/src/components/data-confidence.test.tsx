import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataConfidence } from "./data-confidence";
import type { DataConfidence as DC } from "@/lib/schemas";

const base: DC = {
  label: "high",
  confidence: 0.9,
  overall_coverage: 0.95,
  critical_coverage: 0.92,
  conviction_cap: "high",
  directional_allowed: true,
  sources: [
    { field: "price", source: "massive", source_type: "primary", coverage: 0.95, as_of: "2026-07-10" },
  ],
  missing: [],
  reason_codes: [],
};

describe("<DataConfidence>", () => {
  it("renders nothing when confidence is null", () => {
    const { container } = render(<DataConfidence confidence={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the High/Medium/Low label + coverage", () => {
    render(<DataConfidence confidence={base} />);
    expect(screen.getByText(/High confidence/)).toBeInTheDocument();
    expect(screen.getByText(/critical coverage 92%/)).toBeInTheDocument();
  });

  it("blocks the directional read + explains why when critical coverage is too low", () => {
    render(
      <DataConfidence
        confidence={{
          ...base,
          label: "low",
          confidence: 0.2,
          critical_coverage: 0.25,
          conviction_cap: "none",
          directional_allowed: false,
          missing: [{ field: "fundamentals", source: "unavailable", missing_reason: "no_key", coverage: 0 }],
          reason_codes: [
            { code: "critical_coverage_below_40", severity: "high", detail: "Only 25% of critical inputs." },
          ],
        }}
      />,
    );
    expect(screen.getByText(/Low confidence/)).toBeInTheDocument();
    expect(screen.getByText(/Not enough data for a directional read/)).toBeInTheDocument();
    // the missing dataset + its typed reason are surfaced in plain English
    expect(
      screen.getByText(/fundamentals \(source credential unavailable/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Only 25% of critical inputs/)).toBeInTheDocument();
  });

  it("caps conviction (not blocked) in the 40–70% band", () => {
    render(
      <DataConfidence
        confidence={{ ...base, label: "medium", critical_coverage: 0.55, conviction_cap: "low", directional_allowed: true }}
      />,
    );
    expect(screen.getByText(/Conviction capped at/)).toBeInTheDocument();
  });
});

describe("cross-source agreement rendering", () => {
  const base = {
    label: "high" as const,
    confidence: 0.85,
    overall_coverage: 0.9,
    critical_coverage: 1.0,
  };

  it("renders per-field verdicts with BOTH raw values; only_one_source rows stay hidden", () => {
    render(
      <DataConfidence
        confidence={{
          ...base,
          agreement_checks: [
            {
              field: "last_price",
              status: "disagreement",
              observed_rel_diff: 0.07,
              observations: [
                { source: "fmp", source_type: "primary", value: 233.1, unit: "usd" },
                { source: "yfinance", source_type: "secondary", value: 250.0, unit: "usd" },
              ],
            },
            { field: "market_cap", status: "only_one_source", observations: [] },
          ],
        }}
      />,
    );
    const checks = screen.getByTestId("agreement-checks");
    expect(checks).toHaveTextContent("Last price");
    expect(checks).toHaveTextContent("sources disagree");
    // Both raw values shown unchanged — a conflict never rewrites either side.
    expect(checks).toHaveTextContent("FMP $233.1 vs Yahoo $250");
    expect(checks).toHaveTextContent("Δ 7.0%");
    // A field with only one source is NOT rendered as a verdict.
    expect(checks).not.toHaveTextContent("Market cap");
  });

  it("renders nothing when no field has two independent sources", () => {
    render(
      <DataConfidence
        confidence={{
          ...base,
          agreement_checks: [{ field: "last_price", status: "only_one_source", observations: [] }],
        }}
      />,
    );
    expect(screen.queryByTestId("agreement-checks")).not.toBeInTheDocument();
  });

  it("explains WHY a pair was incomparable", () => {
    render(
      <DataConfidence
        confidence={{
          ...base,
          agreement_checks: [
            {
              field: "revenue",
              status: "incomparable",
              note: "different fiscal periods (2026-03-31 vs 2025-12-31)",
              observations: [
                { source: "fmp", source_type: "primary", value: 1.19e11, unit: "usd_total" },
                { source: "yfinance", source_type: "secondary", value: 1.24e11, unit: "usd_total" },
              ],
            },
          ],
        }}
      />,
    );
    const checks = screen.getByTestId("agreement-checks");
    expect(checks).toHaveTextContent("not comparable");
    expect(checks).toHaveTextContent(/different fiscal periods/);
  });
});
