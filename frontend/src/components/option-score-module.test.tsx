/**
 * OptionScoreModule: shows the deterministic option penalty + top-2 drivers on
 * the score page; renders nothing without options or with zero penalty.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { OptionScoreModule } from "./option-score-module";
import type { OptionScoreImpact } from "@/lib/schemas";

const IMPACT: OptionScoreImpact = {
  contracts: 2,
  net_delta: 50,
  net_gamma: -1,
  net_theta: -20,
  net_vega: 10,
  option_notional: 12000,
  short_collateral_estimate: 10000,
  base_score: 720,
  penalty: 55,
  flags: [],
  penalty_breakdown: [
    { code: "uncovered_short_call", severity: "high", points: 40 },
    { code: "short_gamma", severity: "watch", points: 10 },
    { code: "missing_option_data", severity: "info", points: 5 },
  ],
};

describe("OptionScoreModule", () => {
  it("shows the penalty, adjusted score, and top-2 drivers", () => {
    render(<OptionScoreModule impact={IMPACT} />);
    expect(screen.getByText("−55 pts")).toBeInTheDocument();
    expect(screen.getByText("665", { exact: false })).toBeInTheDocument(); // 720 − 55
    expect(screen.getByText("Uncovered short call")).toBeInTheDocument();
    expect(screen.getByText("Net short gamma")).toBeInTheDocument();
    // only top 2 — the info driver is not shown
    expect(screen.queryByText("Missing option price/IV")).not.toBeInTheDocument();
  });

  it("renders nothing when there is no penalty", () => {
    const { container } = render(
      <OptionScoreModule impact={{ ...IMPACT, penalty: 0 }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing without options", () => {
    const { container } = render(<OptionScoreModule impact={null} />);
    expect(container.firstChild).toBeNull();
  });
});
