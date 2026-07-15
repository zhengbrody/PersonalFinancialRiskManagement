/**
 * Copilot 2.0 structured-answer card.
 *
 * Asserts: the intent pill + conclusion render, an evidence chip carries its
 * source badge, and a quota_exceeded error shows the "See plans" CTA.
 * The /ask hook is mocked so the card renders deterministically.
 */

import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { ApiError } from "@/lib/api";

const askMock = vi.fn();
vi.mock("@/lib/queries", () => ({
  useCopilotAsk: () => askMock(),
  useMyPortfolios: () => ({ data: undefined, isLoading: false, isError: false }),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

import { CopilotAsk } from "./copilot-ask";

const SAMPLE = {
  intent: "ticker_research",
  tickers: ["NVDA"],
  answer_markdown:
    "**Conclusion**\nNVDA looks richly valued.\n\n**Evidence**\n- P/E: 45\n\n**Disclaimer**\nNot advice.",
  evidence: [
    { label: "Price", value: "$120", source: "fmp" },
    { label: "Valuation band", value: "rich", source: "derived" },
  ],
  data_only: false,
  model: "claude-sonnet-4-6",
};

function mockAsk(overrides: Record<string, unknown>) {
  askMock.mockReturnValue({
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    data: undefined,
    ...overrides,
  });
}

describe("CopilotAsk", () => {
  it("renders the structured answer card with intent, conclusion and source-badged evidence", () => {
    mockAsk({ data: SAMPLE });
    renderWithQuery(<CopilotAsk />);

    expect(screen.getByText(/ticker research/i)).toBeInTheDocument();
    expect(screen.getByText(/NVDA looks richly valued/i)).toBeInTheDocument();
    // an evidence chip + its source badge
    expect(screen.getByText("$120")).toBeInTheDocument();
    expect(screen.getByText("fmp")).toBeInTheDocument();
    expect(screen.getByText("derived")).toBeInTheDocument();
  });

  it("shows the upgrade CTA on quota_exceeded", () => {
    mockAsk({
      isError: true,
      error: new ApiError(429, "quota_exceeded", "out of credits"),
    });
    renderWithQuery(<CopilotAsk />);
    expect(screen.getByText(/used your AI credits/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toBeInTheDocument();
  });
});
