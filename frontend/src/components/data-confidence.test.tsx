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
    expect(screen.getByText(/fundamentals \(no API key/)).toBeInTheDocument();
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
