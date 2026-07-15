/**
 * Copilot PR5 — six-section renderer, preferences card, proactive insights.
 *
 * Sections: fixed six-title order, simulation visually distinct (what-if
 * badge), expandable evidence rows with source + tool, low-confidence banner,
 * disclaimer. Preferences: hidden on 503, confirm sends the /100-converted
 * payload, clear is two-step. Insights: cards render, dismissal persists by
 * STABLE id via localStorage, nothing renders without a portfolio.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

const askMock = vi.fn();
const prefsMock = vi.fn();
const saveMock = vi.fn();
const clearMock = vi.fn();
const insightsMock = vi.fn();

vi.mock("@/lib/queries", () => ({
  useCopilotAsk: () => askMock(),
  useMyPortfolios: () => ({ data: undefined, isLoading: false, isError: false }),
  useCopilotPreferences: () => prefsMock(),
  useSaveCopilotPreferences: () => saveMock(),
  useClearCopilotPreferences: () => clearMock(),
  useCopilotInsights: () => insightsMock(),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => "/copilot" }));

import { CopilotAsk } from "./copilot-ask";
import { CopilotInsightsStrip } from "./copilot-insights";
import { CopilotPreferencesCard } from "./copilot-preferences";

const SECTIONED_ANSWER = {
  intent: "portfolio_diagnosis",
  tickers: [],
  answer_markdown: "**Direct answer**\nYour health score is 720/1000.",
  evidence: [
    {
      label: "Health score",
      value: "720/1000",
      source: "engine",
      source_type: "derived",
      id: "E1",
      tool: "portfolio_score",
    },
  ],
  data_only: false,
  conviction: "low",
  language: "en",
  disclaimer: "Educational analysis, not financial advice.",
  data_confidence: {
    label: "medium",
    confidence: 0.6,
    overall_coverage: 0.8,
    critical_coverage: 0.65,
    conviction_cap: "low",
    directional_allowed: true,
    stale: false,
    fallback_used: false,
    sources: [],
    missing: [],
    reason_codes: [],
  },
  sections: [
    { key: "direct_answer", title: "Direct answer", markdown: "Your health score is 720/1000.", ai_generated: true },
    { key: "portfolio_relevance", title: "Why this matters for your portfolio", markdown: "These are your own numbers.", ai_generated: false },
    { key: "evidence", title: "Evidence", markdown: "- [E1] Health score: 720/1000", ai_generated: false },
    { key: "data_confidence", title: "Data confidence & missing data", markdown: "Data confidence: **medium**.", ai_generated: false },
    { key: "what_would_change", title: "What would change this conclusion", markdown: "Fresher data.", ai_generated: false },
    { key: "simulation", title: "Simulation", markdown: "- [E2] Simulated market shock (default what-if assumption): -10%", ai_generated: false },
  ],
};

function idleAsk(data: unknown = undefined) {
  return { mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false, data, error: null };
}

beforeEach(() => {
  askMock.mockReturnValue(idleAsk(SECTIONED_ANSWER));
  prefsMock.mockReturnValue({ data: undefined, isLoading: false, isError: false });
  saveMock.mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false });
  clearMock.mockReturnValue({ mutate: vi.fn(), isPending: false });
  insightsMock.mockReturnValue({ data: undefined, isLoading: false, isError: false });
  window.sessionStorage?.clear?.();
});

describe("six-section renderer", () => {
  it("renders all six titles in order with the simulation visually distinct", () => {
    render(<CopilotAsk />);
    const titles = [
      "Direct answer",
      "Why this matters for your portfolio",
      "Evidence",
      "Data confidence & missing data",
      "What would change this conclusion",
      "Simulation",
    ];
    const found = titles.map((t) => screen.getByText(t));
    // DOM order matches the contract order
    for (let i = 1; i < found.length; i++) {
      expect(
        found[i - 1].compareDocumentPosition(found[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
    expect(screen.getByText(/what-if · not a market fact/i)).toBeInTheDocument();
    expect(screen.getByText("Educational analysis, not financial advice.")).toBeInTheDocument();
    expect(screen.getByText(/AI-phrased · numbers verified/i)).toBeInTheDocument();
  });

  it("evidence rows expand to show the computing tool and source tier", () => {
    render(<CopilotAsk />);
    expect(screen.getByText("720/1000")).toBeInTheDocument();
    expect(screen.getByText("E1")).toBeInTheDocument();
    expect(screen.getByText(/Portfolio health engine/)).toBeInTheDocument();
  });

  it("shows the low-confidence banner when a directional answer is blocked", () => {
    askMock.mockReturnValue(
      idleAsk({
        ...SECTIONED_ANSWER,
        data_confidence: {
          ...SECTIONED_ANSWER.data_confidence,
          directional_allowed: false,
          conviction_cap: "none",
        },
      }),
    );
    render(<CopilotAsk />);
    expect(screen.getByText(/Not enough verified data for a directional answer/)).toBeInTheDocument();
  });
});

describe("preferences card", () => {
  it("hides entirely while the feature is unavailable (503)", () => {
    prefsMock.mockReturnValue({ data: undefined, isLoading: false, isError: true });
    const { container } = render(<CopilotPreferencesCard />);
    expect(container.innerHTML).toBe("");
  });

  it("confirms with the percent field converted to a 0-1 ratio", () => {
    const mutate = vi.fn();
    prefsMock.mockReturnValue({
      data: { confirmed: false },
      isLoading: false,
      isError: false,
    });
    saveMock.mockReturnValue({ mutate, isPending: false, isError: false });
    render(<CopilotPreferencesCard />);
    fireEvent.change(screen.getByLabelText("Risk tolerance"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Single-name concentration limit percent"), {
      target: { value: "25" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm preferences" }));
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ risk_tolerance: 3, concentration_limit: 0.25 }),
      expect.anything(),
    );
  });

  it("clearing requires a second explicit confirmation", () => {
    const clearMutate = vi.fn();
    prefsMock.mockReturnValue({
      data: { confirmed: true, risk_tolerance: 3, confirmed_at: "2026-07-14T00:00:00Z" },
      isLoading: false,
      isError: false,
    });
    clearMock.mockReturnValue({ mutate: clearMutate, isPending: false });
    render(<CopilotPreferencesCard />);
    fireEvent.click(screen.getByRole("button", { name: "Clear all preferences" }));
    expect(clearMutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, erase completely" }));
    expect(clearMutate).toHaveBeenCalled();
  });
});

describe("insights strip", () => {
  const INSIGHT = {
    id: "concentration:NVDA",
    kind: "concentration",
    severity: "high",
    what_changed: "A single position is 42.0% of your book.",
    why_it_matters: "One name's bad day moves your whole portfolio.",
    evidence: [
      { label: "Largest position weight", value: "42.0%", source: "engine", id: "E1", tool: "concentration" },
    ],
    confidence: "high",
    as_of: "2026-07-14T00:00:00Z",
    missing_data: [],
    suggested_next_analysis: { label: "Review concentration in the Risk Report", href: "/risk" },
  };

  function stubStorage() {
    const store = new Map<string, string>();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    });
    return store;
  }

  it("renders nothing without a portfolio", () => {
    insightsMock.mockReturnValue({
      data: { insights: [INSIGHT], portfolio_available: false },
      isLoading: false,
      isError: false,
    });
    const { container } = render(<CopilotInsightsStrip />);
    expect(container.innerHTML).toBe("");
  });

  it("renders the card with evidence and a non-transactional next step", () => {
    stubStorage();
    insightsMock.mockReturnValue({
      data: { insights: [INSIGHT], portfolio_available: true },
      isLoading: false,
      isError: false,
    });
    render(<CopilotInsightsStrip />);
    expect(screen.getByText(/42\.0% of your book/)).toBeInTheDocument();
    expect(screen.getByText(/Review concentration in the Risk Report/)).toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link.getAttribute("href")).toBe("/risk");
  });

  it("dismissal persists the STABLE id to localStorage", () => {
    const store = stubStorage();
    insightsMock.mockReturnValue({
      data: { insights: [INSIGHT], portfolio_available: true },
      isLoading: false,
      isError: false,
    });
    render(<CopilotInsightsStrip />);
    fireEvent.click(screen.getByRole("button", { name: /Dismiss insight/ }));
    expect(screen.queryByText(/42\.0% of your book/)).not.toBeInTheDocument();
    // Dismissals are now PER-PORTFOLIO; with no provider mounted the active id
    // is null → the ":none" partition.
    expect(store.get("mm:copilot:insights:dismissed:none")).toContain("concentration:NVDA");
  });
});
