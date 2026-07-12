/**
 * RiskDimensionsGrid: renders a card per dimension with value/status/percentile/
 * attention-share/explanation; a non-measurable dimension shows "Not measurable"
 * and no fake value. Pure component — no hooks.
 */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskDimensionsGrid } from "./risk-dimensions";
import type { RiskDimension } from "@/lib/queries";

const DIMS: RiskDimension[] = [
  {
    key: "concentration",
    name: "Concentration",
    display: "42%",
    unit: "pct",
    status: "high",
    percentile: 0.9,
    percentile_n: 12,
    contribution: 0.3,
    confidence: "high",
    explanation: "Your largest position (NVDA) is 42% of the book.",
    action: "How concentrated am I?",
    measurable: true,
  },
  {
    key: "options",
    name: "Options exposure",
    status: "n/a",
    explanation: "No option positions in this portfolio.",
    measurable: false,
  },
];

describe("RiskDimensionsGrid", () => {
  it("renders a measurable dimension with value, status, percentile and share", () => {
    render(<RiskDimensionsGrid dimensions={DIMS} />);
    expect(screen.getByText("Concentration")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
    // percentile text
    expect(screen.getByText(/90%/)).toBeInTheDocument();
    expect(screen.getByText(/of your history/)).toBeInTheDocument();
    // attention share label
    expect(screen.getByText(/Share of current risk attention/)).toBeInTheDocument();
    // ask-copilot deep link carries the action prompt
    const link = screen.getByRole("link", { name: /Ask Copilot/ });
    expect(link.getAttribute("href")).toContain("/copilot?q=");
  });

  it("shows a non-measurable dimension as Not measurable with no value", () => {
    render(<RiskDimensionsGrid dimensions={DIMS} />);
    expect(screen.getByText("Options exposure")).toBeInTheDocument();
    expect(screen.getByText("Not measurable")).toBeInTheDocument();
    expect(screen.getByText(/No option positions/)).toBeInTheDocument();
  });

  it("renders nothing when there are no dimensions", () => {
    const { container } = render(<RiskDimensionsGrid dimensions={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
