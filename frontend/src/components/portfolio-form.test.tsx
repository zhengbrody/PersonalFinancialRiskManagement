/**
 * PortfolioForm implied-P&L hint: shows market value + unrealized P&L per row
 * from the live price, so a wrong avg cost is visible at entry (the SGOV case),
 * with an amber nudge on a large deviation.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
import { PortfolioForm, type PortfolioFormValues } from "./portfolio-form";

function priceJson(prices: { ticker: string; price: number }[]) {
  return new Response(
    JSON.stringify({
      data: { prices: prices.map((p) => ({ ...p, as_of: "2026-06-03" })), requested: prices.map((p) => p.ticker) },
      error: null,
      meta: { request_id: "p" },
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function values(row: { ticker: string; shares: string; avg_cost: string }): PortfolioFormValues {
  return {
    name: "Test",
    rows: [row],
    margin_loan: "0",
    contributed_capital: "0",
    cash_balance: "0",
    is_default: false,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("PortfolioForm implied P&L", () => {
  it("surfaces the implied loss for a wrong cost basis (SGOV)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(priceJson([{ ticker: "SGOV", price: 100.41 }]));
    renderWithQuery(
      <PortfolioForm
        initial={values({ ticker: "SGOV", shares: "110", avg_cost: "110.40" })}
        submitLabel="Save"
        busy={false}
        onSubmit={vi.fn()}
      />,
    );
    // 110 × (100.41 − 110.40) = −$1,099 → shown so the user catches the bad cost.
    expect(await screen.findByText(/P&L −\$1,099/)).toBeInTheDocument();
  });

  it("nudges 'double-check the avg cost' on a large deviation", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(priceJson([{ ticker: "AAPL", price: 100 }]));
    renderWithQuery(
      <PortfolioForm
        initial={values({ ticker: "AAPL", shares: "10", avg_cost: "300" })} // −67%
        submitLabel="Save"
        busy={false}
        onSubmit={vi.fn()}
      />,
    );
    expect(await screen.findByText(/double-check the avg cost/i)).toBeInTheDocument();
  });
});
