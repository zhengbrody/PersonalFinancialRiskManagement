/**
 * Client-side portfolio export (the Privacy Policy's "export your data").
 *
 * Everything happens IN THE BROWSER on data the user's session has already
 * fetched — no export request is sent to the backend or any third party.
 *
 * CSV cells are hardened against spreadsheet formula injection: a cell
 * beginning with = + - @ (or a tab/CR remnant) is prefixed with a single
 * quote so Excel/Sheets render it as text instead of executing it — the
 * OWASP-recommended mitigation. Tickers are user input, so this is not
 * hypothetical ("=HYPERLINK(...)" as a "ticker" must never execute).
 */

import type { PortfolioRow } from "@/lib/queries";

const CSV_COLUMNS = [
  "ticker",
  "shares",
  "avg_cost",
  "asset_type",
  "option_type",
  "option_side",
  "underlying",
  "strike",
  "expiry",
  "contract_multiplier",
] as const;

const FORMULA_TRIGGERS = ["=", "+", "-", "@", "\t", "\r"];

/** Escape one CSV cell: neutralize formula triggers, then RFC-4180 quote. */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  let text = String(value);
  if (text.length > 0 && FORMULA_TRIGGERS.includes(text[0])) {
    text = `'${text}`;
  }
  if (/[",\n\r]/.test(text)) {
    text = `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function portfolioToCsv(portfolio: PortfolioRow): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const [ticker, h] of Object.entries(portfolio.holdings ?? {})) {
    const row: Record<string, unknown> = { ticker, ...h };
    lines.push(CSV_COLUMNS.map((col) => csvCell(row[col])).join(","));
  }
  return lines.join("\n") + "\n";
}

export function portfolioToJson(portfolio: PortfolioRow): string {
  return JSON.stringify(
    {
      name: portfolio.name,
      exported_at: new Date().toISOString(),
      margin_loan: portfolio.margin_loan,
      contributed_capital: portfolio.contributed_capital,
      cash_balance: portfolio.cash_balance,
      holdings: portfolio.holdings ?? {},
    },
    null,
    2,
  );
}

/** Safe download filename from the portfolio name. */
export function exportFilename(name: string, ext: "csv" | "json"): string {
  const slug =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "portfolio";
  return `mindmarket-${slug}.${ext}`;
}

/** Browser-only Blob download; no network involved. */
export function downloadTextFile(filename: string, mime: string, text: string): void {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function exportPortfolio(portfolio: PortfolioRow, format: "csv" | "json"): void {
  if (format === "csv") {
    downloadTextFile(
      exportFilename(portfolio.name, "csv"),
      "text/csv;charset=utf-8",
      portfolioToCsv(portfolio),
    );
  } else {
    downloadTextFile(
      exportFilename(portfolio.name, "json"),
      "application/json;charset=utf-8",
      portfolioToJson(portfolio),
    );
  }
}
