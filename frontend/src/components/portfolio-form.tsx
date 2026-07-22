"use client";

/**
 * Shared form for portfolio create + edit. Single source of truth
 * for "what fields does a portfolio carry" and how they validate —
 * both /portfolios/new and /portfolios/[id]/edit consume this.
 *
 * Holdings are edited as a row-per-ticker table. Empty rows are
 * dropped on submit. Numbers come in as strings so the input field
 * never reports `NaN` during typing.
 */

import { useId, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { track } from "@/lib/analytics";
import { holdingsBand } from "@/lib/analytics-events";
import { parseHoldingsCsv } from "@/lib/parse-holdings-csv";
import { useMarketPrices } from "@/lib/queries";
import type {
  PortfolioCreateInput,
  PortfolioHoldingInput,
} from "@/lib/queries";

type Row = {
  ticker: string;
  shares: string;
  avg_cost: string;
  // Optional so callers (and tests) can build a plain equity row with just
  // {ticker, shares, avg_cost}; an absent `kind` is treated as "equity".
  kind?: "equity" | "option";
  option_type?: "call" | "put";
  option_side?: "long" | "short"; // bought vs sold/written
  strike?: string;
  expiry?: string; // YYYY-MM-DD
};

const rowKind = (r: Row): "equity" | "option" => r.kind ?? "equity";

/**
 * Build an OCC-style option contract symbol — the synthetic key an option
 * holding is stored under (e.g. AAPL 2026-01-16 call 150 → "AAPL260116C00150000").
 * Matches yfinance's `contractSymbol`, so the Greeks/pricing layer (PR2) can
 * look the contract up directly in the option chain.
 */
export function occSymbol(
  underlying: string,
  expiry: string,
  optionType: "call" | "put",
  strike: number,
): string {
  const u = underlying.trim().toUpperCase();
  const [y, m, d] = expiry.split("-");
  const yymmdd = `${y.slice(2)}${m}${d}`;
  const cp = optionType === "call" ? "C" : "P";
  const strike8 = String(Math.round(strike * 1000)).padStart(8, "0");
  return `${u}${yymmdd}${cp}${strike8}`;
}

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Calendar days from today to an ISO date, or null if unparseable / past. */
function daysUntil(iso?: string): number | null {
  if (!iso || !ISO_DATE_RE.test(iso)) return null;
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return null;
  const days = Math.ceil((d.getTime() - Date.now()) / 86_400_000);
  return days >= 0 ? days : null;
}

function optionRowComplete(r: Row): boolean {
  const strike = Number(r.strike);
  return (
    rowKind(r) === "option" &&
    r.ticker.trim() !== "" &&
    Number(r.shares) > 0 &&
    Number.isFinite(strike) &&
    strike > 0 &&
    !!r.expiry &&
    ISO_DATE_RE.test(r.expiry)
  );
}

export type PortfolioFormValues = {
  name: string;
  rows: Row[];
  margin_loan: string;
  contributed_capital: string;
  cash_balance: string;
  is_default: boolean;
};

export function rowsFromHoldings(
  holdings: Record<string, { shares: number; avg_cost?: number } & Record<string, unknown>>,
): Row[] {
  const entries = Object.entries(holdings ?? {});
  if (entries.length === 0) {
    return [{ ticker: "", shares: "", avg_cost: "", kind: "equity" }];
  }
  return entries.map(([key, h]) => {
    const base = {
      shares: String(h.shares ?? ""),
      avg_cost: h.avg_cost == null ? "" : String(h.avg_cost),
    };
    if (String(h.asset_type ?? "").toLowerCase() === "option") {
      // Show the UNDERLYING in the ticker field; the contract key (`key`) is
      // re-derived on submit from underlying + expiry + type + strike.
      return {
        ...base,
        kind: "option" as const,
        ticker: String(h.underlying ?? "").toUpperCase(),
        option_type: (h.option_type === "put" ? "put" : "call") as "call" | "put",
        option_side: (h.option_side === "short" ? "short" : "long") as "long" | "short",
        strike: h.strike == null ? "" : String(h.strike),
        expiry: h.expiry == null ? "" : String(h.expiry),
      };
    }
    return { ...base, kind: "equity" as const, ticker: key.toUpperCase() };
  });
}

export function valuesToCreateInput(
  values: PortfolioFormValues,
): PortfolioCreateInput {
  const holdings: Record<string, PortfolioHoldingInput> = {};
  for (const r of values.rows) {
    const shares = Number(r.shares);
    if (!Number.isFinite(shares) || shares <= 0) continue;
    const avg = Number(r.avg_cost);

    if (rowKind(r) === "option") {
      if (!optionRowComplete(r)) continue; // drop half-specified contracts
      const underlying = r.ticker.trim().toUpperCase();
      const strike = Number(r.strike);
      const optionType = r.option_type === "put" ? "put" : "call";
      const key = occSymbol(underlying, r.expiry!, optionType, strike);
      const out: PortfolioHoldingInput = {
        shares, // number of contracts (positive magnitude)
        asset_type: "option",
        option_type: optionType,
        option_side: r.option_side === "short" ? "short" : "long",
        underlying,
        strike,
        expiry: r.expiry,
        contract_multiplier: 100,
      };
      if (Number.isFinite(avg) && avg > 0) out.avg_cost = avg; // premium / share
      holdings[key] = out;
      continue;
    }

    const tk = r.ticker.trim().toUpperCase();
    if (!tk) continue;
    const out: PortfolioHoldingInput = { shares };
    if (Number.isFinite(avg) && avg > 0) out.avg_cost = avg;
    holdings[tk] = out;
  }
  return {
    name: values.name.trim(),
    holdings,
    margin_loan: numOrZero(values.margin_loan),
    contributed_capital: numOrZero(values.contributed_capital),
    cash_balance: numOrZero(values.cash_balance),
    is_default: values.is_default,
  };
}

function numOrZero(s: string): number {
  const n = Number(s);
  return Number.isFinite(n) ? n : 0;
}

export function PortfolioForm({
  initial,
  submitLabel,
  busy,
  errorMessage,
  onSubmit,
  onCancel,
  emphasizeCsv = false,
}: {
  initial: PortfolioFormValues;
  submitLabel: string;
  busy: boolean;
  errorMessage?: string | null;
  onSubmit: (values: PortfolioFormValues) => void;
  onCancel?: () => void;
  /** New-user creation: lead with a prominent broker-CSV import card. */
  emphasizeCsv?: boolean;
}) {
  const [values, setValues] = useState<PortfolioFormValues>(initial);
  const [csvNote, setCsvNote] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Live prices for the entered tickers → show implied market value / P&L per
  // row, so a wrong avg cost (e.g. a current price imported as cost) is obvious
  // at entry time. Public endpoint, keyed only on the ticker set.
  const prices = useMarketPrices(values.rows.map((r) => r.ticker));
  const priceMap = useMemo(() => {
    const m: Record<string, number> = {};
    for (const p of prices.data?.prices ?? []) m[p.ticker.toUpperCase()] = p.price;
    return m;
  }, [prices.data]);
  const priceOf = (ticker: string): number | undefined =>
    priceMap[ticker.trim().toUpperCase()];

  async function onCsvFile(file: File | undefined) {
    if (!file) return;
    try {
      const { rows, warning } = parseHoldingsCsv(await file.text());
      if (rows.length === 0) {
        setCsvNote({ ok: false, text: warning ?? "No holdings found in that file." });
        return;
      }
      setValues((prev) => ({ ...prev, rows }));
      setCsvNote({ ok: true, text: `Imported ${rows.length} holdings — review, then save.` });
      track("csv_imported", { holdings_band: holdingsBand(rows.length) });
    } catch {
      setCsvNote({ ok: false, text: "Could not read that file. Is it a .csv?" });
    } finally {
      if (fileRef.current) fileRef.current.value = ""; // allow re-importing the same file
    }
  }

  function updateRow(i: number, patch: Partial<Row>) {
    setValues((prev) => ({
      ...prev,
      rows: prev.rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)),
    }));
  }
  function addRow() {
    setValues((prev) => ({
      ...prev,
      rows: [...prev.rows, { ticker: "", shares: "", avg_cost: "", kind: "equity" }],
    }));
  }
  function addOptionRow() {
    setValues((prev) => ({
      ...prev,
      rows: [
        ...prev.rows,
        { ticker: "", shares: "", avg_cost: "", kind: "option", option_type: "call", option_side: "long", strike: "", expiry: "" },
      ],
    }));
  }
  function removeRow(i: number) {
    setValues((prev) => ({
      ...prev,
      rows: prev.rows.filter((_, idx) => idx !== i),
    }));
  }

  // Disable submit until the form has enough to send: a name and at
  // least one well-formed row. Avoids a 422 round-trip on obvious-
  // empty submissions.
  const canSubmit =
    !busy &&
    values.name.trim().length > 0 &&
    values.rows.some((r) =>
      rowKind(r) === "option"
        ? optionRowComplete(r)
        : r.ticker.trim() !== "" && Number(r.shares) > 0,
    );

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!canSubmit) return;
        onSubmit(values);
      }}
      className="space-y-6"
    >
      {/* ── name ───────────────────────────────────────────── */}
      <div className="space-y-2">
        <label htmlFor="name" className="text-sm text-muted-foreground">
          Portfolio name
        </label>
        <Input
          id="name"
          required
          maxLength={80}
          value={values.name}
          onChange={(e) =>
            setValues((prev) => ({ ...prev, name: e.target.value }))
          }
          placeholder="My core portfolio"
        />
      </div>

      {/* ── holdings ───────────────────────────────────────── */}
      <div className="space-y-2">
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          aria-label="Import holdings CSV"
          onChange={(e) => onCsvFile(e.target.files?.[0])}
        />
        {emphasizeCsv && (
          <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
            <p className="text-sm font-medium">Fastest way to start</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Import a broker CSV — export Holdings from your broker (Robinhood,
              Schwab, Fidelity…) and we&apos;ll map Symbol / Quantity / Avg Cost for
              you. Or add tickers by hand below.
            </p>
            <Button
              type="button"
              className="mt-3 w-full sm:w-auto"
              onClick={() => fileRef.current?.click()}
            >
              Import a broker CSV
            </Button>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="text-sm text-muted-foreground">Holdings</label>
          <div className="flex flex-wrap items-center gap-2">
            {!emphasizeCsv && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => fileRef.current?.click()}
              >
                Import CSV
              </Button>
            )}
            <Button type="button" variant="outline" size="sm" onClick={addRow}>
              + add ticker
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={addOptionRow}>
              + add option
            </Button>
          </div>
        </div>
        {csvNote && (
          <p
            role="status"
            aria-live="polite"
            className={`text-xs ${
              csvNote.ok ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"
            }`}
          >
            {csvNote.text}
          </p>
        )}
        {!emphasizeCsv && (
          <p className="text-xs text-muted-foreground">
            Tip: export from your broker (Robinhood, Schwab, Fidelity…) and import
            the CSV — we&apos;ll map Symbol / Quantity / Avg Cost automatically.
          </p>
        )}
        <div className="space-y-2">
          {values.rows.map((row, i) => (
            <HoldingRow
              key={i}
              index={i}
              row={row}
              price={priceOf(row.ticker)}
              onChange={(patch) => updateRow(i, patch)}
              onRemove={() => removeRow(i)}
            />
          ))}
        </div>
      </div>

      {/* ── capital + flags ────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <CapitalInput
          label="Contributed"
          value={values.contributed_capital}
          onChange={(v) =>
            setValues((prev) => ({ ...prev, contributed_capital: v }))
          }
        />
        <CapitalInput
          label="Cash"
          value={values.cash_balance}
          onChange={(v) =>
            setValues((prev) => ({ ...prev, cash_balance: v }))
          }
        />
        <CapitalInput
          label="Margin loan"
          value={values.margin_loan}
          onChange={(v) => setValues((prev) => ({ ...prev, margin_loan: v }))}
        />
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.is_default}
          onChange={(e) =>
            setValues((prev) => ({ ...prev, is_default: e.target.checked }))
          }
        />
        Set as default (used by inline Score)
      </label>

      {/* ── error + actions ────────────────────────────────── */}
      {errorMessage && (
        <p className="text-sm text-destructive" role="alert">
          {errorMessage}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!canSubmit} className="w-full sm:w-auto">
          {busy ? "Saving…" : submitLabel}
        </Button>
        {onCancel && (
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            className="w-full sm:w-auto"
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

/**
 * One holdings row — an equity (ticker · shares · avg cost) or an option
 * contract (underlying · contracts · premium + a detail line for
 * call/put · strike · expiry). The kind is toggled per row; an option row
 * suppresses the equity implied-P&L hint (the underlying spot isn't the
 * contract's value) and instead shows a one-line contract summary.
 */
function HoldingRow({
  index,
  row,
  price,
  onChange,
  onRemove,
}: {
  index: number;
  row: Row;
  price: number | undefined;
  onChange: (patch: Partial<Row>) => void;
  onRemove: () => void;
}) {
  const isOption = rowKind(row) === "option";
  const i = index;
  return (
    <div className="space-y-0.5 rounded-md border border-transparent">
      <div className="flex flex-wrap items-center gap-2 sm:grid sm:grid-cols-[auto_1fr_1fr_1fr_auto]">
        <select
          aria-label={`Kind ${i + 1}`}
          className="h-9 rounded-md border border-input bg-background px-2 text-xs font-medium uppercase tracking-wide"
          value={rowKind(row)}
          onChange={(e) =>
            onChange(
              e.target.value === "option"
                ? {
                    kind: "option",
                    option_type: row.option_type ?? "call",
                    option_side: row.option_side ?? "long",
                    strike: row.strike ?? "",
                    expiry: row.expiry ?? "",
                  }
                : { kind: "equity" },
            )
          }
        >
          <option value="equity">Stock</option>
          <option value="option">Option</option>
        </select>
        <Input
          aria-label={isOption ? `Underlying ${i + 1}` : `Ticker ${i + 1}`}
          placeholder={isOption ? "AAPL" : "SPY"}
          className="min-w-[5rem] flex-1 font-mono"
          value={row.ticker}
          onChange={(e) => onChange({ ticker: e.target.value })}
        />
        <Input
          aria-label={isOption ? `Contracts ${i + 1}` : `Shares ${i + 1}`}
          type="number"
          step="any"
          placeholder={isOption ? "contracts" : "shares"}
          className="min-w-[5rem] flex-1 font-mono"
          value={row.shares}
          onChange={(e) => onChange({ shares: e.target.value })}
        />
        <Input
          aria-label={isOption ? `Premium ${i + 1}` : `Avg cost ${i + 1}`}
          type="number"
          step="any"
          placeholder={isOption ? "premium" : "avg cost"}
          className="min-w-[5rem] flex-1 font-mono"
          value={row.avg_cost}
          onChange={(e) => onChange({ avg_cost: e.target.value })}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Remove row ${i + 1}`}
          onClick={onRemove}
        >
          ×
        </Button>
      </div>

      {isOption ? (
        <div className="flex flex-wrap items-center gap-2 pl-1 sm:grid sm:grid-cols-[auto_auto_1fr_1fr_auto]">
          <select
            aria-label={`Side ${i + 1}`}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs font-medium uppercase tracking-wide"
            value={row.option_side ?? "long"}
            onChange={(e) => onChange({ option_side: e.target.value === "short" ? "short" : "long" })}
          >
            <option value="long">Buy</option>
            <option value="short">Sell</option>
          </select>
          <select
            aria-label={`Option type ${i + 1}`}
            className="h-9 rounded-md border border-input bg-background px-2 text-xs font-medium uppercase tracking-wide"
            value={row.option_type ?? "call"}
            onChange={(e) => onChange({ option_type: e.target.value === "put" ? "put" : "call" })}
          >
            <option value="call">Call</option>
            <option value="put">Put</option>
          </select>
          <Input
            aria-label={`Strike ${i + 1}`}
            type="number"
            step="any"
            placeholder="strike"
            className="min-w-[5rem] flex-1 font-mono"
            value={row.strike ?? ""}
            onChange={(e) => onChange({ strike: e.target.value })}
          />
          <Input
            aria-label={`Expiry ${i + 1}`}
            type="date"
            className="min-w-[8rem] flex-1 font-mono"
            value={row.expiry ?? ""}
            onChange={(e) => onChange({ expiry: e.target.value })}
          />
          <span className="text-[11px] text-muted-foreground">
            {price ? `underlying $${price.toFixed(2)}` : "premium per share × 100"}
            {(() => {
              const d = daysUntil(row.expiry);
              return d != null && d <= 30 ? (
                <span className="ml-2 font-medium text-amber-600 dark:text-amber-400">
                  ⚠ expires in {d}d
                </span>
              ) : null;
            })()}
          </span>
        </div>
      ) : (
        <ImpliedPnl row={row} price={price} />
      )}
    </div>
  );
}

function CapitalInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const inputId = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={inputId} className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      <Input
        id={inputId}
        type="number"
        step="any"
        min="0"
        className="font-mono"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/**
 * Implied market value + unrealized P&L for one row, from the live price. Shown
 * the moment a ticker+shares (and optional avg cost) are entered, so a wrong
 * cost basis is visible immediately. Amber when the implied P&L is large
 * (|≥40%|) — a gentle "double-check the avg cost" nudge — but the figure is
 * always shown so even a small-but-wrong loss (the SGOV case) is caught.
 */
function ImpliedPnl({ row, price }: { row: Row; price: number | undefined }) {
  const shares = Number(row.shares);
  if (!price || !Number.isFinite(shares) || shares <= 0) return null;

  const mv = shares * price;
  const avg = Number(row.avg_cost);
  const hasAvg = Number.isFinite(avg) && avg > 0;
  const pnl = hasAvg ? shares * (price - avg) : null;
  const pct = hasAvg && avg > 0 ? (price - avg) / avg : null;
  const big = pct != null && Math.abs(pct) >= 0.4;

  return (
    <p
      className={`pl-1 text-[11px] ${
        big ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
      }`}
    >
      ≈ {usd(mv)} at ${price.toFixed(2)}
      {pnl != null && (
        <>
          {" · "}
          P&amp;L {pnl >= 0 ? "+" : "−"}
          {usd(Math.abs(pnl))}
          {pct != null && ` (${(pct * 100).toFixed(1)}%)`}
        </>
      )}
      {big && " — double-check the avg cost"}
    </p>
  );
}

function usd(v: number): string {
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
