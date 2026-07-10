import { describe, expect, it } from "vitest";

import { csvCell, exportFilename, portfolioToCsv, portfolioToJson } from "./portfolio-export";
import type { PortfolioRow } from "./queries";

function row(holdings: PortfolioRow["holdings"]): PortfolioRow {
  return {
    id: "p1",
    user_id: "u1",
    name: "My Book",
    holdings,
    margin_loan: 1000,
    contributed_capital: 20000,
    cash_balance: 500,
    is_default: true,
    created_at: null,
    updated_at: null,
  } as PortfolioRow;
}

describe("csvCell — spreadsheet formula-injection hardening", () => {
  it("neutralizes every formula trigger character", () => {
    expect(csvCell("=HYPERLINK(\"http://evil\")")).toBe("\"'=HYPERLINK(\"\"http://evil\"\")\"");
    expect(csvCell("+SUM(A1)")).toBe("'+SUM(A1)");
    expect(csvCell("-2+3")).toBe("'-2+3");
    expect(csvCell("@cmd")).toBe("'@cmd");
  });

  it("quotes commas/quotes/newlines per RFC 4180 and passes plain values", () => {
    expect(csvCell("AAPL")).toBe("AAPL");
    expect(csvCell(12.5)).toBe("12.5");
    expect(csvCell('a,"b"')).toBe('"a,""b"""');
    expect(csvCell(null)).toBe("");
  });
});

describe("portfolioToCsv", () => {
  it("exports holdings incl. option fields, injection-safe", () => {
    const csv = portfolioToCsv(
      row({
        AAPL: { shares: 10, avg_cost: 150, asset_type: "public_security" },
        "=EVIL()": { shares: 1, avg_cost: 1 },
        AAPL260116C00150000: {
          shares: 2,
          avg_cost: 5.5,
          asset_type: "option",
          option_type: "call",
          option_side: "short",
          underlying: "AAPL",
          strike: 150,
          expiry: "2026-01-16",
          contract_multiplier: 100,
        },
      }),
    );
    const lines = csv.trim().split("\n");
    expect(lines[0]).toBe(
      "ticker,shares,avg_cost,asset_type,option_type,option_side,underlying,strike,expiry,contract_multiplier",
    );
    expect(lines[1]).toBe("AAPL,10,150,public_security,,,,,,");
    expect(lines[2].startsWith("'=EVIL()")).toBe(true); // formula neutralized
    expect(lines[3]).toContain("call,short,AAPL,150,2026-01-16,100");
  });
});

describe("portfolioToJson", () => {
  it("round-trips holdings and capital fields, no extra network data", () => {
    const parsed = JSON.parse(
      portfolioToJson(row({ SPY: { shares: 3, avg_cost: 400 } })),
    );
    expect(parsed.name).toBe("My Book");
    expect(parsed.holdings.SPY).toEqual({ shares: 3, avg_cost: 400 });
    expect(parsed.margin_loan).toBe(1000);
    expect(typeof parsed.exported_at).toBe("string");
  });
});

describe("exportFilename", () => {
  it("slugs unsafe names and falls back", () => {
    expect(exportFilename("My Book!", "csv")).toBe("mindmarket-my-book.csv");
    expect(exportFilename("///", "json")).toBe("mindmarket-portfolio.json");
  });
});
