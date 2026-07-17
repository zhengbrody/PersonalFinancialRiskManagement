import { describe, expect, it } from "vitest";
import {
  applyTestOp,
  equityTickersFromHoldings,
  nonEquitySummary,
  rowsFromHoldingsAndPrices,
  scaleValue,
} from "./whatif";
import type { MarketPrices } from "@/lib/queries";

const HOLDINGS = {
  AAPL: { shares: 10, asset_type: "public_security" },
  bnd: { shares: 50 }, // asset_type omitted → equity by default; case normalized
  AAPL260116C00150000: {
    shares: 2,
    asset_type: "option",
    underlying: "AAPL",
    strike: 150,
  },
  CASH: { shares: 1, asset_type: "cash" },
  ZERO: { shares: 0 },
};

const PRICES: MarketPrices = {
  prices: [
    { ticker: "AAPL", price: 300.4, as_of: "2026-07-03" },
    { ticker: "BND", price: 72.2, as_of: "2026-07-03" },
  ],
  requested: ["AAPL", "BND"],
} as MarketPrices;

describe("equityTickersFromHoldings", () => {
  it("keeps priceable equity rows, drops options/cash/zero-share", () => {
    expect(equityTickersFromHoldings(HOLDINGS)).toEqual(["AAPL", "BND"]);
    expect(equityTickersFromHoldings(undefined)).toEqual([]);
  });
});

describe("rowsFromHoldingsAndPrices", () => {
  it("maps shares × latest close, rounded, sorted by value desc", () => {
    const rows = rowsFromHoldingsAndPrices(HOLDINGS, PRICES);
    expect(rows).toEqual([
      { ticker: "BND", market_value: "3610" }, // 50 × 72.2
      { ticker: "AAPL", market_value: "3004" }, // 10 × 300.4
    ]);
  });

  it("skips holdings without a resolvable price instead of inventing one", () => {
    const rows = rowsFromHoldingsAndPrices(
      { AAPL: { shares: 10 }, MYSTERY: { shares: 5 } },
      PRICES,
    );
    expect(rows.map((r) => r.ticker)).toEqual(["AAPL"]);
  });

  it("empty inputs → empty rows", () => {
    expect(rowsFromHoldingsAndPrices(undefined, undefined)).toEqual([]);
  });
});

describe("scaleValue", () => {
  it("applies ±10% with integer rounding", () => {
    expect(scaleValue("10000", 0.9)).toBe("9000");
    expect(scaleValue("10000", 1.1)).toBe("11000");
    expect(scaleValue("15", 0.9)).toBe("14"); // round(13.5) → banker's-free JS round
  });

  it("leaves junk input untouched", () => {
    expect(scaleValue("", 0.9)).toBe("");
    expect(scaleValue("abc", 1.1)).toBe("abc");
  });
});

describe("nonEquitySummary", () => {
  it("counts option and cash legs by kind", () => {
    const s = nonEquitySummary({
      AAPL: { shares: 10 },
      CASH: { asset_type: "cash", shares: 1 },
      AAPL260116C00150000: { asset_type: "option", shares: 2 },
      SPY260116P00400000: { asset_type: "option", shares: 1 },
    });
    expect(s).toEqual({ optionCount: 2, cashCount: 1, hasNonEquity: true });
  });

  it("equity-only book → nothing excluded", () => {
    expect(nonEquitySummary({ AAPL: { shares: 10 } })).toEqual({
      optionCount: 0,
      cashCount: 0,
      hasNonEquity: false,
    });
    expect(nonEquitySummary(undefined).hasNonEquity).toBe(false);
  });
});

describe("applyTestOp", () => {
  const BASE = [
    { ticker: "AAPL", market_value: 5000 },
    { ticker: "MSFT", market_value: 100 },
  ];

  it("replace with a SUFFICIENT funding leg moves the full requested amount", () => {
    const r = applyTestOp(BASE, "replace", "NVDA", 2000, "AAPL");
    if (!r.ok) throw new Error(r.error);
    expect(r.execution).toEqual({ requested: 2000, applied: 2000, residual: 0 });
    expect(r.rows).toEqual([
      { ticker: "AAPL", market_value: 3000 },
      { ticker: "MSFT", market_value: 100 },
      { ticker: "NVDA", market_value: 2000 },
    ]);
    // Book value conserved.
    const total = r.rows.reduce((s, x) => s + x.market_value, 0);
    expect(total).toBe(5100);
  });

  it("replace with an INSUFFICIENT funding leg moves only what's freed and reports the residual", () => {
    const r = applyTestOp(BASE, "replace", "NVDA", 5000, "MSFT");
    if (!r.ok) throw new Error(r.error);
    expect(r.execution).toEqual({ requested: 5000, applied: 100, residual: 4900 });
    // MSFT fully consumed → dropped; NVDA gets ONLY the freed $100.
    expect(r.rows).toEqual([
      { ticker: "AAPL", market_value: 5000 },
      { ticker: "NVDA", market_value: 100 },
    ]);
    const total = r.rows.reduce((s, x) => s + x.market_value, 0);
    expect(total).toBe(5100); // never fabricates unfunded exposure
  });

  it("replace with self is rejected with a reason", () => {
    const r = applyTestOp(BASE, "replace", "AAPL", 1000, "AAPL");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/itself/i);
  });

  it("replace from a position you don't hold is rejected", () => {
    const r = applyTestOp(BASE, "replace", "NVDA", 1000, "TSLA");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/don't hold TSLA/i);
  });

  it("zero / negative / non-finite amounts are rejected, never clamped", () => {
    for (const bad of [0, -100, NaN, Infinity]) {
      const r = applyTestOp(BASE, "add", "NVDA", bad);
      expect(r.ok).toBe(false);
    }
  });

  it("reduce is capped at the existing position (honest applied/residual)", () => {
    const r = applyTestOp(BASE, "reduce", "MSFT", 5000);
    if (!r.ok) throw new Error(r.error);
    expect(r.execution).toEqual({ requested: 5000, applied: 100, residual: 4900 });
    expect(r.rows).toEqual([{ ticker: "AAPL", market_value: 5000 }]);
  });

  it("reduce of an unheld ticker is rejected", () => {
    const r = applyTestOp(BASE, "reduce", "NVDA", 100);
    expect(r.ok).toBe(false);
  });

  it("add/increase applies the full amount (existing or new position)", () => {
    const add = applyTestOp(BASE, "add", "NVDA", 1000);
    if (!add.ok) throw new Error(add.error);
    expect(add.rows.find((x) => x.ticker === "NVDA")?.market_value).toBe(1000);
    expect(add.execution.residual).toBe(0);

    const inc = applyTestOp(BASE, "increase", "AAPL", 1000);
    if (!inc.ok) throw new Error(inc.error);
    expect(inc.rows.find((x) => x.ticker === "AAPL")?.market_value).toBe(6000);
  });

  it("an empty equity base (cash/options-only book) can still reject replace/reduce", () => {
    expect(applyTestOp([], "replace", "NVDA", 1000, "AAPL").ok).toBe(false);
    expect(applyTestOp([], "reduce", "NVDA", 1000).ok).toBe(false);
  });
});
