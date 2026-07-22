/**
 * Research → "Test in my portfolio" drawer. Closed → nothing. Open with an
 * active book → a Sheet dialog with the op selector + the "simulation only"
 * guarantee; without an active portfolio → a select-a-portfolio hint. The
 * "replace" op must CONSERVE book value (only what's freed from the funding leg
 * moves into the target — never fabricate exposure). Heavy children
 * (WhatIfCompare / SaveAsPlan) and the shared whatif mappers are mocked.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const ctxMock = vi.fn();
const apiFetchMock = vi.fn();
const { rowsMock, holdingsHolder, saveAsPlanSpy } = vi.hoisted(() => ({
  rowsMock: vi.fn(),
  holdingsHolder: { value: {} as Record<string, unknown> },
  saveAsPlanSpy: vi.fn(),
}));
vi.mock("@/lib/portfolio-context", () => ({ usePortfolioContext: () => ctxMock() }));
vi.mock("@/lib/api", () => ({
  apiFetch: (...a: unknown[]) => apiFetchMock(...a),
  ApiError: class ApiError extends Error {},
}));
vi.mock("@/lib/queries", () => ({
  useActiveScore: () => ({ data: { overall_score: 700, risk_preference: 4 } }),
  useCopilotPreferences: () => ({
    data: { confirmed: true, risk_tolerance: 4 },
  }),
  useMarketPrices: () => ({ data: {} }),
  useMyPortfolios: () => ({
    data: { portfolios: [{ id: "p1", name: "Main", holdings: holdingsHolder.value }] },
  }),
}));
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
// The row/ticker MAPPERS are mocked (no price plumbing in this test); the
// op math (applyTestOp) and the boundary summary (nonEquitySummary) run REAL —
// they're exactly what these tests assert.
vi.mock("@/lib/whatif", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/whatif")>();
  return {
    ...actual,
    equityTickersFromHoldings: () => ["SPY", "MSFT"],
    rowsFromHoldingsAndPrices: (...a: unknown[]) => rowsMock(...a),
  };
});
vi.mock("@/components/whatif-compare", () => ({ WhatIfCompare: () => null }));
vi.mock("@/components/save-as-plan", () => ({
  SaveAsPlan: (props: Record<string, unknown>) => {
    saveAsPlanSpy(props);
    return null;
  },
}));

import { ResearchTestDrawer } from "./research-test-drawer";

beforeEach(() => {
  apiFetchMock.mockReset();
  saveAsPlanSpy.mockReset();
  holdingsHolder.value = {};
  rowsMock.mockReset().mockReturnValue([
    { ticker: "SPY", market_value: 10000 },
    { ticker: "MSFT", market_value: 100 },
  ]);
});

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
      risk_preference: number;
    };
    expect(body.risk_preference).toBe(4);
    const total = body.holdings.reduce((s, h) => s + h.market_value, 0);
    // Book was SPY $10,000 + MSFT $100 = $10,100; conservation keeps it there
    // (MSFT's $100 moves to NVDA), NOT $15,000 with $4,900 fabricated.
    expect(total).toBeCloseTo(10100);
    const nvda = body.holdings.find((h) => h.ticker === "NVDA");
    expect(nvda?.market_value).toBeCloseTo(100); // only the freed $100, NOT $5,000
    expect(body.holdings.find((h) => h.ticker === "MSFT")).toBeUndefined(); // fully freed → dropped
  });

  it("explains WHY only the freed amount was deployed and persists the ACTUAL amount to the plan", async () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    apiFetchMock.mockResolvedValue({ overall_score: 690, data_confidence: { label: "medium" } });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);

    fireEvent.change(screen.getByRole("combobox", { name: /what to model/i }), {
      target: { value: "replace" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /replace which position/i }), {
      target: { value: "MSFT" },
    });
    fireEvent.change(screen.getByPlaceholderText(/\$ value/i), { target: { value: "5000" } });
    fireEvent.click(screen.getByRole("button", { name: /see before . after/i }));

    // The honest ledger: requested vs freed vs deployed vs residual + a reason.
    const summary = await screen.findByTestId("replace-execution-summary");
    expect(summary).toHaveTextContent("Requested");
    expect(summary).toHaveTextContent("$5,000");
    expect(summary).toHaveTextContent("Freed from MSFT");
    expect(summary).toHaveTextContent("Deployed into NVDA");
    expect(summary).toHaveTextContent("Not deployed");
    expect(summary).toHaveTextContent("$4,900");
    expect(summary).toHaveTextContent(/moved \$100 instead of the requested \$5,000/i);
    expect(summary).toHaveTextContent(/never\s+creates exposure that isn't funded/i);

    // Saving the plan records the ACTUAL $100 move (plus the requested amount),
    // never a fabricated $5,000.
    fireEvent.click(screen.getByRole("button", { name: /save as risk plan/i }));
    await waitFor(() => expect(saveAsPlanSpy).toHaveBeenCalled());
    const props = saveAsPlanSpy.mock.calls.at(-1)?.[0] as {
      proposedChanges: { amount_usd: number; requested_usd?: number };
    };
    expect(props.proposedChanges.amount_usd).toBeCloseTo(100);
    expect(props.proposedChanges.requested_usd).toBeCloseTo(5000);
  });

  it("replace with a SUFFICIENT funding leg shows zero residual and persists the full amount", async () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    apiFetchMock.mockResolvedValue({ overall_score: 690, data_confidence: { label: "high" } });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);

    fireEvent.change(screen.getByRole("combobox", { name: /what to model/i }), {
      target: { value: "replace" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /replace which position/i }), {
      target: { value: "SPY" },
    });
    fireEvent.change(screen.getByPlaceholderText(/\$ value/i), { target: { value: "2000" } });
    fireEvent.click(screen.getByRole("button", { name: /see before . after/i }));

    const summary = await screen.findByTestId("replace-execution-summary");
    expect(summary).toHaveTextContent("$0"); // Not deployed = $0
    expect(summary).not.toHaveTextContent(/instead of the requested/i);

    fireEvent.click(screen.getByRole("button", { name: /save as risk plan/i }));
    await waitFor(() => expect(saveAsPlanSpy).toHaveBeenCalled());
    const props = saveAsPlanSpy.mock.calls.at(-1)?.[0] as {
      proposedChanges: { amount_usd: number; requested_usd?: number };
    };
    expect(props.proposedChanges.amount_usd).toBeCloseTo(2000);
    expect(props.proposedChanges.requested_usd).toBeUndefined();
  });

  it("the executed funding leg is FROZEN — changing the select after a run never relabels the summary or the saved plan", async () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    apiFetchMock.mockResolvedValue({ overall_score: 690, data_confidence: { label: "high" } });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);

    fireEvent.change(screen.getByRole("combobox", { name: /what to model/i }), {
      target: { value: "replace" },
    });
    fireEvent.change(screen.getByRole("combobox", { name: /replace which position/i }), {
      target: { value: "MSFT" },
    });
    fireEvent.change(screen.getByPlaceholderText(/\$ value/i), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: /see before . after/i }));
    const summary = await screen.findByTestId("replace-execution-summary");
    expect(summary).toHaveTextContent("Freed from MSFT");

    // Drift the live select AFTER the run — the executed record must not move.
    fireEvent.change(screen.getByRole("combobox", { name: /replace which position/i }), {
      target: { value: "SPY" },
    });
    expect(screen.getByTestId("replace-execution-summary")).toHaveTextContent("Freed from MSFT");

    fireEvent.click(screen.getByRole("button", { name: /save as risk plan/i }));
    await waitFor(() => expect(saveAsPlanSpy).toHaveBeenCalled());
    const props = saveAsPlanSpy.mock.calls.at(-1)?.[0] as {
      proposedChanges: { from: string | null };
    };
    expect(props.proposedChanges.from).toBe("MSFT");
  });

  it("zero / invalid amounts are rejected with a message, no request fired", async () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: /see before . after/i }));
    expect(await screen.findByText(/amount greater than zero/i)).toBeInTheDocument();
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("names what a mixed book excludes (options + cash) instead of a vague caption", () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    holdingsHolder.value = {
      SPY: { shares: 10 },
      CASH: { asset_type: "cash", shares: 1 },
      AAPL260116C00150000: { asset_type: "option", shares: 2 },
    };
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);
    expect(screen.getByText(/1 option position and your cash balance/i)).toBeInTheDocument();
    expect(screen.getByText(/option Greeks and cash deployment are not modeled/i)).toBeInTheDocument();
    // Equity rows exist → the form is NOT blocked.
    expect(screen.getByText("What to model")).toBeInTheDocument();
  });

  it("BLOCKS the sandbox for a cash/options-only book with a reason (never a misleading empty baseline)", () => {
    ctxMock.mockReturnValue({ current: { id: "p1" }, activePortfolioId: "p1" });
    holdingsHolder.value = {
      CASH: { asset_type: "cash", shares: 1 },
      AAPL260116C00150000: { asset_type: "option", shares: 2 },
    };
    rowsMock.mockReturnValue([]); // no priced equity rows
    render(<ResearchTestDrawer ticker="NVDA" open onClose={() => {}} />);
    expect(screen.getByText(/no priced equity positions/i)).toBeInTheDocument();
    expect(screen.getByText(/would be misleading/i)).toBeInTheDocument();
    expect(screen.queryByText("What to model")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /see before . after/i })).not.toBeInTheDocument();
  });
});
