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

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type {
  PortfolioCreateInput,
  PortfolioHoldingInput,
} from "@/lib/queries";

type Row = {
  ticker: string;
  shares: string;
  avg_cost: string;
};

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
    return [{ ticker: "", shares: "", avg_cost: "" }];
  }
  return entries.map(([ticker, h]) => ({
    ticker: ticker.toUpperCase(),
    shares: String(h.shares ?? ""),
    avg_cost: h.avg_cost == null ? "" : String(h.avg_cost),
  }));
}

export function valuesToCreateInput(
  values: PortfolioFormValues,
): PortfolioCreateInput {
  const holdings: Record<string, PortfolioHoldingInput> = {};
  for (const r of values.rows) {
    const tk = r.ticker.trim().toUpperCase();
    const shares = Number(r.shares);
    if (!tk || !Number.isFinite(shares) || shares <= 0) continue;
    const out: PortfolioHoldingInput = { shares };
    const avg = Number(r.avg_cost);
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
}: {
  initial: PortfolioFormValues;
  submitLabel: string;
  busy: boolean;
  errorMessage?: string | null;
  onSubmit: (values: PortfolioFormValues) => void;
  onCancel?: () => void;
}) {
  const [values, setValues] = useState<PortfolioFormValues>(initial);

  function updateRow(i: number, patch: Partial<Row>) {
    setValues((prev) => ({
      ...prev,
      rows: prev.rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)),
    }));
  }
  function addRow() {
    setValues((prev) => ({
      ...prev,
      rows: [...prev.rows, { ticker: "", shares: "", avg_cost: "" }],
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
    values.rows.some(
      (r) => r.ticker.trim() !== "" && Number(r.shares) > 0,
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
        <div className="flex items-center justify-between">
          <label className="text-sm text-muted-foreground">Holdings</label>
          <Button type="button" variant="outline" size="sm" onClick={addRow}>
            + add ticker
          </Button>
        </div>
        <div className="space-y-2">
          {values.rows.map((row, i) => (
            <div
              key={i}
              className="flex flex-wrap items-center gap-2 sm:grid sm:grid-cols-[1fr_1fr_1fr_auto]"
            >
              <Input
                aria-label={`Ticker ${i + 1}`}
                placeholder="SPY"
                className="min-w-[5rem] flex-1 font-mono"
                value={row.ticker}
                onChange={(e) => updateRow(i, { ticker: e.target.value })}
              />
              <Input
                aria-label={`Shares ${i + 1}`}
                type="number"
                step="any"
                placeholder="shares"
                className="min-w-[5rem] flex-1 font-mono"
                value={row.shares}
                onChange={(e) => updateRow(i, { shares: e.target.value })}
              />
              <Input
                aria-label={`Avg cost ${i + 1}`}
                type="number"
                step="any"
                placeholder="avg cost"
                className="min-w-[5rem] flex-1 font-mono"
                value={row.avg_cost}
                onChange={(e) => updateRow(i, { avg_cost: e.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`Remove row ${i + 1}`}
                onClick={() => removeRow(i)}
              >
                ×
              </Button>
            </div>
          ))}
        </div>
      </div>

      {/* ── capital + flags ────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
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
      <div className="flex gap-2">
        <Button type="submit" disabled={!canSubmit}>
          {busy ? "Saving…" : submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
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
  return (
    <div className="space-y-1">
      <label className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </label>
      <Input
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
