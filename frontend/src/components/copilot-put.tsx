"use client";

import { useEffect, useRef, useState } from "react";
import { initialPutFields, putFieldLabels } from "@/lib/put-fields";
import { CopilotPutPlans } from "./copilot-put-plans";
import { Button } from "./ui/button";
import { apiFetch } from "@/lib/api";
import { putRequestSchema, putResultSchema, type PutResult } from "@/lib/copilot-put";

const money = (value: number) => value.toLocaleString("en-US", { style: "currency", currency: "USD" });
const perShare = (value: number) => value.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 });
const initial = initialPutFields;
const labels = putFieldLabels;

export function CopilotPut({ token, portfolioId, plansEnabled = false }: { token: string | null; portfolioId: string; plansEnabled?: boolean }) {
  const [fields, setFields] = useState(initial);
  const [confirmed, setConfirmed] = useState(false);
  const [cashConfirmed, setCashConfirmed] = useState(false);
  const [standard, setStandard] = useState(false);
  const [result, setResult] = useState<PutResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  async function calculate() {
    const abort = new AbortController();
    active.current?.abort(); active.current = abort;
    setBusy(true); setError(""); setResult(null);
    try {
      const body = putRequestSchema.parse({
        expected_portfolio_id: portfolioId, underlying: fields.underlying.trim().toUpperCase(),
        expiry: fields.expiry, strike: Number(fields.strike), premium_per_share: Number(fields.premium_per_share),
        assumed_spot: Number(fields.assumed_spot), contracts: Number(fields.contracts),
        fees_total: Number(fields.fees_total), other_reserved_cash: Number(fields.other_reserved_cash),
        cash_buffer: Number(fields.cash_buffer), confirmed, gross_settled_usd_cash_confirmed: cashConfirmed,
        standard_contract_confirmed: standard,
      });
      const value = await apiFetch("/api/v1/copilot/cash-secured-put", {
        method: "POST", authToken: token ?? undefined, body, signal: abort.signal, schema: putResultSchema,
      });
      const parsed = putResultSchema.parse(value);
      if (parsed.portfolio_id !== portfolioId ||
          Object.entries(body).some(([key, value]) => parsed.assumptions[key as keyof typeof body] !== value)) {
        throw new Error("The result does not match this portfolio and these assumptions.");
      }
      if (!abort.signal.aborted) setResult(parsed);
    } catch (e) {
      if (!abort.signal.aborted) setError(e instanceof Error ? e.message : "Could not calculate the put scenario.");
    } finally { if (active.current === abort) setBusy(false); }
  }
  return <details className="rounded-xl border border-border p-3">
    <summary className="cursor-pointer text-sm font-medium">Test a cash-secured Put</summary>
    <form className="mt-3 space-y-3" onSubmit={event => { event.preventDefault(); void calculate(); }}>
      <p className="text-xs text-muted-foreground">Hypothetical USD equity put, not a live quote or order. This first model requires zero margin debt. Full strike cash is reserved before new premium; other holdings remain unchanged.</p>
      <fieldset disabled={busy} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">{Object.entries(labels).map(([name, label]) =>
          <label key={name} className="min-w-0 text-xs">{label}
            <input aria-label={label} required type={name === "underlying" ? "text" : name === "expiry" ? "date" : "number"}
              step={name === "contracts" ? "1" : "0.01"} min={name === "contracts" ? "1" : "0"}
              value={fields[name as keyof typeof fields]}
              onChange={event => { setFields(previous => ({ ...previous, [name]: event.target.value })); setConfirmed(false); setCashConfirmed(false); setStandard(false); setResult(null); }}
              className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm" />
          </label>)}</div>
        <label className="flex gap-2 text-xs"><input type="checkbox" checked={cashConfirmed} onChange={e => setCashConfirmed(e.target.checked)} />
          I confirm the recorded portfolio cash is gross settled USD cash before holds, and I entered all other reserved cash separately.</label>
        <label className="flex gap-2 text-xs"><input type="checkbox" checked={standard} onChange={e => setStandard(e.target.checked)} />
          I confirm this is an unadjusted, physically settled USD equity put delivering 100 shares per contract.</label>
        <label className="flex gap-2 text-xs"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
          I confirm these hypothetical inputs and understand assignment can require the full strike amount.</label>
      </fieldset>
      <Button type="submit" size="sm" disabled={busy || !token || !confirmed || !cashConfirmed || !standard}>Calculate put scenario</Button>
      {error && <p role="alert" className="text-sm">{error}</p>}
    </form>
    {result && <section aria-label="Cash-secured put result" className="mt-4 space-y-3 text-sm">
      <p className="font-medium">{result.funding_status === "insufficient_cash" ? "Insufficient cash under these assumptions" : "Cash covered under your confirmed assumptions"}</p>
      <p className="text-xs text-muted-foreground">Calculated {result.computed_at} · Hypothetical inputs, not a broker approval</p>
      <dl className="grid gap-2 sm:grid-cols-2">
        {[["Recorded cash", result.recorded_cash], ["Existing put cash reserve", result.existing_put_reserve],
          ["No-action cash after reserves and buffer", result.no_action_free_cash], ["Full assignment payment", result.assignment_notional],
          ["Net premium after fees", result.net_premium], ["Initial equity change (fees only)", result.initial_incremental_equity],
          ["Cash shortfall before new premium", result.pre_trade_funding_gap], ["Best expiry P&L", result.best_expiry_pnl],
          ["Maximum loss at zero underlying price", result.maximum_loss], ["Break-even per share (approx.)", result.breakeven]
        ].map(([label, value]) => <div key={String(label)}><dt className="text-xs text-muted-foreground">{label}</dt><dd>{String(label).startsWith("Break-even") ? perShare(Number(value)) : money(Number(value))}</dd></div>)}
      </dl>
      <p className="text-xs">Incremental expiry P&amp;L versus no new trade (zero). Existing holdings&apos; P&amp;L is excluded. Below-strike rows assume assignment; actual exercise may differ.</p>
      <div className="overflow-x-auto"><table className="w-full text-xs">
        <thead><tr>{["Underlying (approx.)", "No trade P&L", "New put P&L", "Shares received", "Cash after settlement", "Cash after reserves", "Funding gap"].map(label => <th key={label} className="p-2 text-left">{label}</th>)}</tr></thead>
        <tbody>{result.scenarios.map((row, i) => <tr key={i} className="border-t border-border">
          {[perShare(row.underlying_price), money(row.no_action_incremental_pnl), money(row.candidate_incremental_pnl),
            row.shares_acquired, money(row.cash_after_settlement), money(row.free_cash_after_reserves), money(row.funding_gap_after_reserves)
          ].map((value, index) => <td key={index} className="whitespace-nowrap p-2">{value}</td>)}
        </tr>)}</tbody>
      </table></div>
      <details><summary className="cursor-pointer text-xs">Assumptions & limitations</summary><ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted-foreground">
        {result.limitations.map(item => <li key={item}>{item}</li>)}
      </ul></details>
      <a href={result.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary underline">OIC: cash-secured put mechanics</a>
    </section>}
    {plansEnabled && <CopilotPutPlans key={result?.result_id ?? "retrieve"} token={token} portfolioId={portfolioId} result={result} />}
  </details>;
}
