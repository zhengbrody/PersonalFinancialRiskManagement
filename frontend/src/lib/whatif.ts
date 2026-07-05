/**
 * What-if lab helpers — pure mapping from the user's SAVED holdings + latest
 * prices into editable sandbox rows. No computation beyond shares × price;
 * the scoring itself stays on the backend (the same /risk/score endpoint the
 * public sandbox uses).
 */

import type { MarketPrices } from "@/lib/queries";

type HoldingEntry = Record<string, unknown>;

/** Equity tickers of a holdings dict — options (OCC-keyed, not priceable
 * here) and cash-ish entries are excluded; the what-if lab is an equity
 * sandbox, matching what POST /risk/score accepts. */
export function equityTickersFromHoldings(
  holdings: Record<string, HoldingEntry> | undefined,
): string[] {
  const out: string[] = [];
  for (const [ticker, h] of Object.entries(holdings ?? {})) {
    const kind = String(h?.asset_type ?? "public_security").toLowerCase();
    if (kind === "option" || kind === "cash") continue;
    const shares = Number(h?.shares);
    if (!Number.isFinite(shares) || shares <= 0) continue;
    out.push(ticker.toUpperCase());
  }
  return out;
}

/** Sandbox rows (ticker + market value string) from saved holdings and the
 * latest close per ticker. Holdings without a resolvable price are skipped —
 * better an honest omission than a fabricated value. */
export function rowsFromHoldingsAndPrices(
  holdings: Record<string, HoldingEntry> | undefined,
  prices: MarketPrices | undefined,
): { ticker: string; market_value: string }[] {
  const byTicker = new Map<string, number>();
  for (const p of prices?.prices ?? []) {
    if (Number.isFinite(p.price) && p.price > 0) byTicker.set(p.ticker.toUpperCase(), p.price);
  }
  const rows: { ticker: string; market_value: string }[] = [];
  for (const [ticker, h] of Object.entries(holdings ?? {})) {
    const kind = String(h?.asset_type ?? "public_security").toLowerCase();
    if (kind === "option" || kind === "cash") continue;
    const shares = Number(h?.shares);
    const price = byTicker.get(ticker.toUpperCase());
    if (!Number.isFinite(shares) || shares <= 0 || price == null) continue;
    rows.push({
      ticker: ticker.toUpperCase(),
      market_value: String(Math.round(shares * price)),
    });
  }
  rows.sort((a, b) => Number(b.market_value) - Number(a.market_value));
  return rows;
}

/** ×0.9 / ×1.1 quick adjust, kept as a helper so the rounding rule is tested. */
export function scaleValue(value: string, factor: number): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return value;
  return String(Math.max(1, Math.round(n * factor)));
}
