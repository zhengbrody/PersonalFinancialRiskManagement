import { describe, expect, it } from "vitest";
import {
  equityTickersFromHoldings,
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
