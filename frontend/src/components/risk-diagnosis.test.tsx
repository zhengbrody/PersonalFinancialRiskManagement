/**
 * RiskDiagnosis / ActionCards renderer tests.
 *
 * Presentational component — fed the explain query state directly (no network,
 * no auth). Covers: skeleton while loading, the fallback "Auto summary" badge,
 * the AI badge, severity + headline + bullets, and that action cards always
 * carry the educational disclaimer.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActionCards, RiskDiagnosis } from "./risk-diagnosis";
import type { RiskExplain } from "@/lib/queries";

// analytics is a prod-only no-op; stub so the effect never touches PostHog.
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

const BASE: RiskExplain = {
  severity: "elevated",
  headline: "Concentration is your main risk right now.",
  summary_bullets: ["NVDA drives 41% of portfolio VaR.", "Returns lag the risk taken."],
  primary_driver: "Concentration in NVDA (41% of portfolio VaR)",
  watch_items: ["Daily VaR 95: -2.1%"],
  suggested_actions: [
    {
      reason: "Single-name concentration in NVDA",
      evidence: "NVDA contributes 41% of total portfolio VaR.",
      next_step: "Compare downside in the What-if lab with your largest position scaled down.",
      disclaimer: "Educational, not financial advice.",
    },
  ],
  caveats: ["Educational, not financial advice."],
  ai_generated: false,
};

describe("RiskDiagnosis", () => {
  it("shows a skeleton while loading with no data", () => {
    const { container } = render(
      <RiskDiagnosis explain={undefined} loading source="score" />,
    );
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("renders severity, headline, bullets and the Auto badge on the fallback", () => {
    render(<RiskDiagnosis explain={BASE} loading={false} source="score" />);
    expect(screen.getByText(/elevated risk/i)).toBeInTheDocument();
    expect(screen.getByText(/concentration is your main risk/i)).toBeInTheDocument();
    expect(screen.getByText(/NVDA drives 41% of portfolio VaR/i)).toBeInTheDocument();
    expect(screen.getByText(/auto summary/i)).toBeInTheDocument();
  });

  it("shows the AI badge when the LLM narrated it", () => {
    render(
      <RiskDiagnosis explain={{ ...BASE, ai_generated: true }} loading={false} source="risk" />,
    );
    expect(screen.getByText(/ai summary/i)).toBeInTheDocument();
  });
});

describe("ActionCards", () => {
  it("renders each action with its disclaimer", () => {
    render(<ActionCards explain={BASE} loading={false} />);
    expect(screen.getByText(/single-name concentration in NVDA/i)).toBeInTheDocument();
    expect(screen.getByText(/educational, not financial advice/i)).toBeInTheDocument();
  });

  it("shows a calm message when there are no actions", () => {
    render(<ActionCards explain={{ ...BASE, suggested_actions: [] }} loading={false} />);
    expect(screen.getByText(/no pressing actions/i)).toBeInTheDocument();
  });
});
