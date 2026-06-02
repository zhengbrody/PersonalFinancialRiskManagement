import { describe, expect, it } from "vitest";
import { parseHoldingsCsv } from "./parse-holdings-csv";

describe("parseHoldingsCsv", () => {
  it("maps a typical broker header (Symbol/Quantity/Average Cost), stripping $/commas", () => {
    const csv = [
      "Symbol,Quantity,Average Cost",
      "AAPL,10,150.25",
      'SPY,"1,200","$420.50"',
    ].join("\n");
    const { rows } = parseHoldingsCsv(csv);
    expect(rows).toEqual([
      { ticker: "AAPL", shares: "10", avg_cost: "150.25" },
      { ticker: "SPY", shares: "1200", avg_cost: "420.5" },
    ]);
  });

  it("detects columns in any order and ignores extra columns", () => {
    const csv = ["Name,Avg Cost,Ticker,Shares", "Apple,150,AAPL,10"].join("\n");
    const { rows } = parseHoldingsCsv(csv);
    expect(rows).toEqual([{ ticker: "AAPL", shares: "10", avg_cost: "150" }]);
  });

  it("falls back to positional (ticker, shares, cost) when no header is recognised", () => {
    const { rows } = parseHoldingsCsv("AAPL,10,150\nBND,50,70");
    expect(rows).toEqual([
      { ticker: "AAPL", shares: "10", avg_cost: "150" },
      { ticker: "BND", shares: "50", avg_cost: "70" },
    ]);
  });

  it("leaves avg_cost blank when absent and skips zero/blank-share rows", () => {
    const csv = ["Ticker,Shares", "AAPL,10", "CASH,0", ",5"].join("\n");
    const { rows } = parseHoldingsCsv(csv);
    expect(rows).toEqual([{ ticker: "AAPL", shares: "10", avg_cost: "" }]);
  });

  it("warns on an empty file and on a file with no usable rows", () => {
    expect(parseHoldingsCsv("").warning).toBeTruthy();
    expect(parseHoldingsCsv("Ticker,Shares\nFOO,abc").warning).toBeTruthy();
  });
});
