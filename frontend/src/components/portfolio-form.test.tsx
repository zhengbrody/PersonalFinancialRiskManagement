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

import { occSymbol, rowsFromHoldings, valuesToCreateInput } from "./portfolio-form";

describe("PortfolioForm option entry", () => {
  it("builds an OCC contract symbol", () => {
    expect(occSymbol("aapl", "2026-01-16", "call", 150)).toBe("AAPL260116C00150000");
    expect(occSymbol("SPY", "2026-03-20", "put", 400.5)).toBe("SPY260320P00400500");
  });

  it("valuesToCreateInput keys an option by its OCC symbol with contract fields", () => {
    const input = valuesToCreateInput({
      name: "Opt book",
      rows: [
        { ticker: "AAPL", shares: "10", avg_cost: "180", kind: "equity" },
        { ticker: "AAPL", shares: "2", avg_cost: "5.20", kind: "option", option_type: "call", strike: "150", expiry: "2026-01-16" },
      ],
      margin_loan: "0",
      contributed_capital: "0",
      cash_balance: "0",
      is_default: false,
    });
    expect(input.holdings.AAPL.shares).toBe(10);
    const opt = input.holdings.AAPL260116C00150000;
    expect(opt.asset_type).toBe("option");
    expect(opt.option_type).toBe("call");
    expect(opt.underlying).toBe("AAPL");
    expect(opt.strike).toBe(150);
    expect(opt.expiry).toBe("2026-01-16");
    expect(opt.contract_multiplier).toBe(100);
    expect(opt.avg_cost).toBe(5.2);
  });

  it("drops a half-specified option (missing expiry)", () => {
    const input = valuesToCreateInput({
      name: "x",
      rows: [{ ticker: "AAPL", shares: "1", avg_cost: "", kind: "option", option_type: "put", strike: "150", expiry: "" }],
      margin_loan: "0",
      contributed_capital: "0",
      cash_balance: "0",
      is_default: false,
    });
    expect(Object.keys(input.holdings)).toHaveLength(0);
  });

  it("round-trips a stored option holding back into an option row", () => {
    const rows = rowsFromHoldings({
      AAPL260116C00150000: {
        shares: 2,
        avg_cost: 5.2,
        asset_type: "option",
        option_type: "call",
        underlying: "AAPL",
        strike: 150,
        expiry: "2026-01-16",
      },
    });
    expect(rows[0].kind).toBe("option");
    expect(rows[0].ticker).toBe("AAPL"); // underlying shown in the ticker field
    expect(rows[0].option_type).toBe("call");
    expect(rows[0].strike).toBe("150");
    expect(rows[0].expiry).toBe("2026-01-16");
  });
});
