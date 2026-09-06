"use client";

import { useId } from "react";
import { Button } from "@/components/ui/button";
import type { ChangeComparison, ChangeDraft } from "@/lib/copilot-compare";

export function CopilotChangeForm({ draft, disabled, onChange, onSubmit }: {
  draft: ChangeDraft; disabled: boolean; onChange: (draft: ChangeDraft) => void; onSubmit: () => void;
}) {
  const id = useId();
  return (
    <form className="space-y-3 rounded-2xl border border-border bg-card p-4" onSubmit={(e) => { e.preventDefault(); if (!disabled) onSubmit(); }}>
      <h3 className="font-semibold">Test a stock/ETF reduction</h3>
      <p className="text-sm text-muted-foreground">Choose the assumption, then compare with keeping everything unchanged. No orders or changes to holdings.</p>
      <p className="text-xs text-muted-foreground">First version: US-listed, USD-priced long stocks/ETFs and account cash. Books containing options or other unsupported assets are stopped, not partially analyzed.</p>
      <label className="block text-sm" htmlFor={`${id}-ticker`}>Held ticker</label>
      <input id={`${id}-ticker`} required maxLength={12} pattern="[A-Z][A-Z0-9.\-]{0,11}" value={draft.ticker} disabled={disabled}
        className="w-full rounded-lg border border-border bg-background p-2" autoComplete="off"
        onChange={(e) => onChange({ ...draft, ticker: e.target.value.toUpperCase().trim() })} />
      <label className="block text-sm" htmlFor={`${id}-amount`}>Amount to reduce (USD)</label>
      <input id={`${id}-amount`} required type="number" min="0.01" max="100000000" step="0.01" inputMode="decimal" value={draft.amount} disabled={disabled}
        className="w-full rounded-lg border border-border bg-background p-2"
        onChange={(e) => onChange({ ...draft, amount: e.target.value })} />
      <label className="block text-sm" htmlFor={`${id}-proceeds`}>Use hypothetical proceeds to</label>
      <select id={`${id}-proceeds`} value={draft.proceeds} disabled={disabled} className="w-full rounded-lg border border-border bg-background p-2"
        onChange={(e) => onChange({ ...draft, proceeds: e.target.value as ChangeDraft["proceeds"] })}>
        <option value="cash">Keep as account cash</option><option value="repay_margin">Repay margin</option>
      </select>
      <Button type="submit" disabled={disabled}>Compare assumptions</Button>
    </form>
  );
}

const money = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const percent = (v: number) => `${(v * 100).toFixed(1)}%`;
const rows = [
  ["net_equity", "Net equity (closing-price basis)", money],
  ["cash", "Account cash", money], ["margin", "Margin loan", money],
  ["leverage", "Gross assets / net equity", (v: number) => `${v.toFixed(2)}×`],
  ["largest_position_weight", "Largest stock/ETF / gross assets", percent],
  ["annual_volatility", "Annualized equity volatility", percent],
  ["var_1d_95_usd", "Historical 1-day 95% VaR", money],
  ["cvar_1d_95_usd", "Historical 1-day expected shortfall (95%)", money],
] as const;

export function CopilotChangeResult({ result, disabled, onRevise }: { result: ChangeComparison; disabled: boolean; onRevise: () => void }) {
  return (
    <section aria-label="Change comparison" className="space-y-4 rounded-2xl border border-border bg-card p-4">
      <div><h3 className="font-semibold">Keep unchanged vs your assumption</h3>
        <p className="mt-1 text-sm">Reduce {result.assumptions.ticker} by {money(result.assumptions.amount)} → {result.assumptions.proceeds === "cash" ? "account cash" : "repay margin"}.</p>
        <p className="mt-1 text-xs text-muted-foreground">Hypothetical · closing prices {result.price_as_of} · {result.observations} shared daily returns. Not live execution prices.</p></div>
      <p className="text-sm">Net equity is conserved before costs. This changes exposure, not investment profit. VaR and expected shortfall are not maximum losses.</p>
      <dl className="space-y-3">
        {rows.map(([key, label, format]) => (
          <div key={key} className="rounded-lg bg-muted/40 p-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 grid grid-cols-2 gap-3 text-sm tabular-nums">
              <span><span className="block text-xs text-muted-foreground">Keep unchanged</span>{format(result.baseline[key])}</span>
              <span><span className="block text-xs text-muted-foreground">Your assumption</span>{format(result.candidate[key])}</span>
            </dd>
          </div>
        ))}
      </dl>
      <details><summary className="cursor-pointer text-sm">Data, method and limits</summary>
        <p className="mt-2 break-words text-xs">{result.methodology_version} · history from {result.history_start} · captured {result.computed_at}</p>
        <p className="mt-2 text-xs">{Object.entries(result.sources).map(([t, s]) => `${t}: ${s}`).join(" · ")}</p>
        <ul className="mt-2 list-disc space-y-2 pl-4 text-xs text-muted-foreground">{result.limitations.map((s) => <li key={s}>{s}</li>)}</ul>
      </details>
      <Button variant="outline" disabled={disabled} onClick={onRevise}>Revise assumption</Button>
      <p className="text-xs text-muted-foreground">Recomputing captures fresh inputs for both sides. This result is not a saved risk plan.</p>
    </section>
  );
}
