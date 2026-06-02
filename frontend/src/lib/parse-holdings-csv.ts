/**
 * Parse a broker-exported CSV into portfolio holding rows. Onboarding's biggest
 * friction is hand-typing positions; most brokers (Robinhood, Schwab, Fidelity,
 * IBKR…) export a CSV with Symbol/Quantity/Cost columns under varying names, so
 * we detect columns flexibly and fall back to positional (ticker, shares, cost).
 *
 * Pure + dependency-free (a tiny RFC-4180-ish line splitter handles quoted
 * fields). Returns rows shaped for PortfolioForm + an optional warning.
 */

export type ParsedHolding = { ticker: string; shares: string; avg_cost: string };

const TICKER_HEADERS = ["ticker", "symbol"];
const SHARES_HEADERS = ["shares", "quantity", "qty", "share", "units"];
const COST_HEADERS = [
  "avg cost",
  "average cost",
  "average cost basis",
  "cost basis",
  "cost/share",
  "cost per share",
  "purchase price",
  "avg price",
  "price",
  "cost",
];

/** Split one CSV line, honouring double-quoted fields with embedded commas. */
function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out.map((s) => s.trim());
}

function findCol(headers: string[], candidates: string[]): number {
  for (const c of candidates) {
    const i = headers.indexOf(c);
    if (i >= 0) return i;
  }
  for (let i = 0; i < headers.length; i++) {
    if (candidates.some((c) => headers[i].includes(c))) return i;
  }
  return -1;
}

/** Strip $, commas, parens, whitespace from a numeric cell. */
function cleanNumber(s: string): number {
  const cleaned = (s || "").replace(/[$,()\s]/g, "");
  return Number(cleaned);
}

export function parseHoldingsCsv(text: string): {
  rows: ParsedHolding[];
  warning?: string;
} {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);
  if (lines.length === 0) return { rows: [], warning: "That file looks empty." };

  const header = splitCsvLine(lines[0]).map((h) => h.toLowerCase());
  let tickerCol = findCol(header, TICKER_HEADERS);
  let sharesCol = findCol(header, SHARES_HEADERS);
  let costCol = findCol(header, COST_HEADERS);

  let dataLines = lines;
  if (tickerCol >= 0 || sharesCol >= 0) {
    // Recognisable header row → skip it.
    dataLines = lines.slice(1);
    if (tickerCol < 0) tickerCol = 0;
    if (sharesCol < 0) sharesCol = 1;
  } else {
    // No header detected → assume positional: ticker, shares, [cost].
    tickerCol = 0;
    sharesCol = 1;
    costCol = 2;
  }

  const rows: ParsedHolding[] = [];
  for (const line of dataLines) {
    const cells = splitCsvLine(line);
    const ticker = (cells[tickerCol] ?? "")
      .toUpperCase()
      .replace(/[^A-Z0-9.\-]/g, "");
    const shares = cleanNumber(cells[sharesCol] ?? "");
    if (!ticker || !Number.isFinite(shares) || shares <= 0) continue;
    const cost = costCol >= 0 ? cleanNumber(cells[costCol] ?? "") : NaN;
    rows.push({
      ticker,
      shares: String(shares),
      avg_cost: Number.isFinite(cost) && cost > 0 ? String(cost) : "",
    });
  }

  if (rows.length === 0) {
    return {
      rows: [],
      warning:
        "Couldn't find any holdings — expected columns like Ticker/Symbol, Shares/Quantity, and (optionally) Avg Cost.",
    };
  }
  return { rows };
}
