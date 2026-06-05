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

  it("does NOT use a current/last price column as avg cost (the SGOV phantom-loss bug)", () => {
    // A broker export with a Last Price column but no real cost column → avg
    // cost must stay blank (unknown), never the market price.
    const csv = ["Symbol,Quantity,Last Price", "SGOV,110,100.41"].join("\n");
    const { rows } = parseHoldingsCsv(csv);
    expect(rows).toEqual([{ ticker: "SGOV", shares: "110", avg_cost: "" }]);
  });

  it("derives per-share avg cost from a TOTAL cost-basis column ÷ shares", () => {
    const csv = ["Symbol,Quantity,Cost Basis", "SGOV,110,11045.50"].join("\n");
    const { rows } = parseHoldingsCsv(csv);
    expect(rows[0].ticker).toBe("SGOV");
    expect(Number(rows[0].avg_cost)).toBeCloseTo(100.41, 1); // 11045.50 / 110
  });

  it("prefers a per-share cost column over a total cost-basis column", () => {
    const csv = ["Symbol,Quantity,Cost Basis,Avg Cost", "SGOV,110,11045,100.41"].join("\n");
    const { rows } = parseHoldingsCsv(csv);
    expect(rows[0].avg_cost).toBe("100.41"); // the per-share, not total/shares
  });
});
