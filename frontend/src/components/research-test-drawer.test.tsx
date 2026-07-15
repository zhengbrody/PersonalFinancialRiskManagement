/**
 * Research → "Test in my portfolio" drawer. Closed → nothing. Open with an
 * active book → a Sheet dialog with the op selector + the "simulation only"
 * guarantee; without an active portfolio → a select-a-portfolio hint. The
 * "replace" op must CONSERVE book value (only what's freed from the funding leg
 * moves into the target — never fabricate exposure). Heavy children
 * (WhatIfCompare / SaveAsPlan) and the shared whatif mappers are mocked.
 */

import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const ctxMock = vi.fn();
const apiFetchMock = vi.fn();
vi.mock("@/lib/portfolio-context", () => ({ usePortfolioContext: () => ctxMock() }));
vi.mock("@/lib/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetchMock(...a),
  ApiError: class ApiError extends Error {},
}));
vi.mock("@/lib/queries", () => ({
  useActiveScore: () => ({ data: { overall_score: 700 } }),
  useMarketPrices: () => ({ data: {} }),
  useMyPortfolios: () => ({
    data: { portfolios: [{ id: "p1", name: "Main", holdings: {} }] },
  }),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/lib/whatif", () => ({
  equityTickersFromHoldings: () => ["SPY", "MSFT"],
  rowsFromHoldingsAndPrices: () => [
    { ticker: "SPY", market_value: 10000 },
    { ticker: "MSFT", market_value: 100 },
  ],
}));
vi.mock("@/components/whatif-compare", () => ({ WhatIfCompare: () => null }));
vi.mock("@/components/save-as-plan", () => ({ SaveAsPlan: () => null }));

import { ResearchTestDrawer } from "./research-test-drawer";

describe("ResearchTestDrawer", () => {
  it("renders nothing when closed", () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    const { container } = render(
      <ResearchTestDrawer ticker="NVDA" open={false} onClose={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("opens an accessible dialog with the op selector + simulation-only guarantee", () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText(/Test NVDA in your portfolio/i)).toBeInTheDocument();
    expect(screen.getByText(/your holdings are never changed/i)).toBeInTheDocument();
    expect(screen.getByText("What to model")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /see before . after/i })).toBeInTheDocument();
  });

  it("prompts to pick a portfolio when none is active", () => {
    ctxMock.mockReturnValue({ current: null, activePortfolioId: null });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);
    expect(screen.getByText(/Select a portfolio to model a change/i)).toBeInTheDocument();
    expect(screen.queryByText("What to model")).not.toBeInTheDocument();
  });

  it("replace conserves book value — only the freed amount moves into the target", async () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    apiFetchMock.mockResolvedValue({ overall_score: 690, data_confidence: { label: "medium" } });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);

    fireEvent.change(screen.getByRole("combobox", { name: /what to model/i }), {
      target: { value: "replace" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /replace which position/i }), {
      target: { value: "MSFT" },
    });
    // Ask for $5,000 — far more than MSFT's $100 funding leg.
    fireEvent.change(screen.getByPlaceholderText(/\$ value/i), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: /see before . after/i }));

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    const body = apiFetchMock.mock.calls[0][1].body as {
      holdings: { ticker: string; market_value: number }[];
    };
    const total = body.holdings.reduce((s, h) => s + h.market_value, 0);
    // Book was SPY $10,000 + MSFT $100 = $10,100; conservation keeps it there
    // (MSFT's $100 moves to NVDA), NOT $15,000 with $4,900 fabricated.
    expect(total).toBeCloseTo(10100);
    const nvda = body.holdings.find((h) => h.ticker === "NVDA");
    expect(nvda?.market_value).toBeCloseTo(100); // only the freed $100, NOT $5,000
    expect(body.holdings.find((h) => h.ticker === "MSFT")).toBeUndefined(); // fully freed → dropped
  });
});
