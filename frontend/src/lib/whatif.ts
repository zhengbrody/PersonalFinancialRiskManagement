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

/** What the equity sandbox leaves untouched — counts by kind so the boundary
 * caption can NAME what is excluded instead of a vague "some assets". */
export function nonEquitySummary(holdings: Record<string, HoldingEntry> | undefined): {
  optionCount: number;
  cashCount: number;
  hasNonEquity: boolean;
} {
  let optionCount = 0;
  let cashCount = 0;
  for (const h of Object.values(holdings ?? {})) {
    const kind = String(h?.asset_type ?? "public_security").toLowerCase();
    if (kind === "option") optionCount += 1;
    else if (kind === "cash") cashCount += 1;
  }
  return { optionCount, cashCount, hasNonEquity: optionCount + cashCount > 0 };
}

export type TestOp = "add" | "increase" | "reduce" | "replace";
export type TestOpRow = { ticker: string; market_value: number };

/** The honest execution record of a modeled change. `applied` is the dollar
 * amount the simulation ACTUALLY moved; `residual` is the requested amount that
 * could not be funded/applied (never fabricated into exposure). */
export type TestOpExecution = {
  requested: number;
  applied: number;
  residual: number;
};

export type TestOpResult =
  | { ok: true; rows: TestOpRow[]; execution: TestOpExecution }
  | { ok: false; error: string };

/**
 * Apply a hypothetical add/increase/reduce/replace to a copy of the equity
 * rows. Pure — the drawer's single source for both the re-score payload AND
 * the requested/applied/residual breakdown shown (and persisted) to the user.
 *
 * Invariants:
 *  - replace conserves book value: only what is actually freed from the
 *    funding leg moves into the target (never exposure larger than the source);
 *  - reduce never takes a position below zero;
 *  - a zero/negative/non-finite amount is rejected, not silently clamped.
 */
export function applyTestOp(
  baseRows: TestOpRow[],
  op: TestOp,
  targetTicker: string,
  dollars: number,
  fromTicker?: string,
): TestOpResult {
  const T = targetTicker.trim().toUpperCase();
  if (!T) return { ok: false, error: "Missing ticker." };
  if (!Number.isFinite(dollars) || dollars <= 0) {
    return { ok: false, error: "Enter an amount greater than zero." };
  }
  const rows = baseRows.map((r) => ({ ...r }));
  const idx = rows.findIndex((r) => r.ticker === T);
  let applied = dollars;

  if (op === "add" || op === "increase") {
    if (idx >= 0) rows[idx].market_value += dollars;
    else rows.push({ ticker: T, market_value: dollars });
  } else if (op === "reduce") {
    if (idx < 0) return { ok: false, error: `You don't hold ${T}, so there is nothing to reduce.` };
    // Never take a position below zero — the reduction is capped at what exists.
    applied = Math.min(dollars, rows[idx].market_value);
    rows[idx].market_value -= applied;
  } else if (op === "replace") {
    const from = (fromTicker ?? "").trim().toUpperCase();
    if (!from) return { ok: false, error: "Pick which position funds the replacement." };
    if (from === T) {
      return { ok: false, error: `Replacing ${T} with itself wouldn't change anything.` };
    }
    const fi = rows.findIndex((r) => r.ticker === from);
    if (fi < 0) return { ok: false, error: `You don't hold ${from}, so it can't fund this.` };
    // Conserve book value: only what's actually freed from the funding leg
    // moves into the target — never fabricate exposure larger than the source.
    applied = Math.min(dollars, rows[fi].market_value);
    rows[fi].market_value -= applied;
    if (idx >= 0) rows[idx].market_value += applied;
    else rows.push({ ticker: T, market_value: applied });
  }

  return {
    ok: true,
    rows: rows.filter((r) => r.market_value > 0),
    execution: { requested: dollars, applied, residual: Math.max(0, dollars - applied) },
  };
}
