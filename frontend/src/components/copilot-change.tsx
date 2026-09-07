"use client";

import { useEffect, useId, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import type { ChangeComparison, ChangeDraft, ComparisonVerification, SavedComparison } from "@/lib/copilot-compare";

export function CopilotChangeForm({ draft, disabled, onChange, onSubmit }: {
  draft: ChangeDraft; disabled: boolean; onChange: (draft: ChangeDraft) => void; onSubmit: () => void;
}) {
  const id = useId();
  return (
    <form className="space-y-3 rounded-2xl border border-border bg-card p-4" onSubmit={(e) => { e.preventDefault(); if (!disabled) onSubmit(); }}>
      <h3 className="font-semibold">Test a stock/ETF reduction</h3>
      <p className="text-sm text-muted-foreground">Choose the assumption, then compare with keeping everything unchanged. No orders or changes to holdings.</p>
      <p className="text-xs text-muted-foreground">US-listed, USD-priced stocks/ETFs, cash and standard equity options. Only the selected stock/ETF changes; option legs stay intact. Missing or ambiguous contracts stop the comparison.</p>
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
  ["net_equity", "Net equity (captured valuation basis)", money],
  ["cash", "Account cash", money], ["margin", "Margin loan", money],
  ["leverage", "Gross assets / net equity", (v: number) => `${v.toFixed(2)}×`],
  ["largest_position_weight", "Largest stock/ETF / gross assets", percent],
  ["annual_volatility", "Annualized equity volatility", percent],
  ["var_1d_95_usd", "Historical 1-day 95% VaR", money],
  ["cvar_1d_95_usd", "Historical 1-day expected shortfall (95%)", money],
  ["option_assets", "Long option value", money],
  ["option_liabilities", "Short option liability", money],
] as const;

export function CopilotChangeResult({ result, disabled, onRevise, onVerify, verification, verificationPending, verificationError, onSave, onRetrieveSaved, saved, savedNeedsCheck, savePending, saveError, receiptEvicted }: {
  result: ChangeComparison; disabled: boolean; onRevise: () => void; onVerify?: () => void;
  verification?: ComparisonVerification; verificationPending?: boolean; verificationError?: string;
  onSave?: () => void; onRetrieveSaved?: () => void; saved?: SavedComparison;
  savedNeedsCheck?: boolean; savePending?: boolean; saveError?: string; receiptEvicted?: boolean;
}) {
  const mixed = result.risk_method === "mixed_instant_stress";
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [consent, setConsent] = useState(false);
  const consentId = useId();
  // Opening the consent step replaces the button that opened it, so focus would
  // otherwise fall to <body> and keyboard users would restart from the top of
  // the page at the one point that demands a deliberate decision.
  const consentRef = useRef<HTMLInputElement | null>(null);
  const saveRef = useRef<HTMLButtonElement | null>(null);
  const restoreFocus = useRef(false);
  useEffect(() => {
    if (confirmOpen) consentRef.current?.focus();
    else if (restoreFocus.current) { restoreFocus.current = false; saveRef.current?.focus(); }
  }, [confirmOpen]);
  return (
    <section aria-label="Change comparison" className="space-y-4 rounded-2xl border border-border bg-card p-4">
      <div><h3 className="font-semibold">Keep unchanged vs your assumption</h3>
        <p className="mt-1 text-sm">Reduce {result.assumptions.ticker} by {money(result.assumptions.amount)} → {result.assumptions.proceeds === "cash" ? "account cash" : "repay margin"}.</p>
        <p className="mt-1 text-xs text-muted-foreground">Hypothetical · stock closes {result.price_as_of} · {mixed ? "option marks captured once for both sides" : `${result.observations} shared daily returns`}. Not live execution prices.</p></div>
      <p className="text-sm">Net equity is conserved before costs. This changes exposure, not investment profit. VaR and expected shortfall are not maximum losses.</p>
      {mixed && <div className="rounded-lg border border-amber-500/40 p-3 text-sm">
        <p>Mixed-account stress comparison · option positions unchanged.</p>
        <p className="mt-1">{result.option_quote_basis}. Historical account VaR and volatility are unavailable here, not zero.</p>
        {result.limitations.filter((s) => s.startsWith("This reduction removes some stock backing")).map((s) => <p className="mt-2 font-medium" key={s}>{s}</p>)}
      </div>}
      <dl className="space-y-3">
        {rows.filter(([key]) => mixed || !["option_assets", "option_liabilities"].includes(key)).map(([key, label, format]) => (
          <div key={key} className="rounded-lg bg-muted/40 p-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 grid grid-cols-2 gap-3 text-sm tabular-nums">
              <span><span className="block text-xs text-muted-foreground">Keep unchanged</span>{result.baseline[key] === null ? "Unavailable for mixed account" : format(result.baseline[key])}</span>
              <span><span className="block text-xs text-muted-foreground">Your assumption</span>{result.candidate[key] === null ? "Unavailable for mixed account" : format(result.candidate[key])}</span>
            </dd>
          </div>
        ))}
      </dl>
      {mixed && <section aria-label="Full-account stress scenarios" className="space-y-3">
        <h4 className="font-medium">Full-account instantaneous stresses</h4>
        <p className="text-xs text-muted-foreground">Chosen assumptions, not forecasts or worst-case bounds. Full option repricing is anchored to the same model&apos;s zero-shock value; no time passes.</p>
        {result.scenarios.map((s) => <article key={s.label} className="rounded-lg border border-border p-3 text-sm">
          <h5 className="font-medium">{s.label}</h5>
          <p className="mt-1 text-xs text-muted-foreground">{Object.entries(s.shocks).map(([t, v]) => `${t} ${percent(v)}`).join(" · ")} · IV {(s.iv_shift * 100).toFixed(0)} percentage points · {s.horizon_days} days forward</p>
          <div className="mt-2 grid grid-cols-2 gap-3 tabular-nums"><p>Keep unchanged<br />P&amp;L {money(s.baseline_pnl)}<br />Equity {money(s.baseline_equity)}</p><p>Your assumption<br />P&amp;L {money(s.candidate_pnl)}<br />Equity {money(s.candidate_equity)}</p></div>
        </article>)}
      </section>}
      {mixed && <details><summary className="cursor-pointer text-sm">Unchanged option groups · expiry boundaries</summary>
        <p className="mt-2 text-xs">Option-only bounds from captured marks, not entry cost or whole-account maximum loss. Stock coverage is excluded. Different expiries are separate; do not sum their bounds.</p>
        {result.option_groups.map((g) => <p key={`${g.underlying}:${g.expiry}`} className="mt-2 text-sm">{g.underlying} · {g.expiry} · {g.name} · {g.leg_count} legs<br />Max loss: {g.mark_basis_max_loss === null ? "Unbounded in option-only expiry model" : money(g.mark_basis_max_loss)} · Max gain: {g.mark_basis_max_gain === null ? "Unbounded in option-only expiry model" : money(g.mark_basis_max_gain)}</p>)}
      </details>}
      <details><summary className="cursor-pointer text-sm">Data, method and limits</summary>
        <p className="mt-2 break-words text-xs">{result.methodology_version} · history from {result.history_start} · captured {result.computed_at}</p>
        <p className="mt-2 text-xs">{Object.entries(result.sources).map(([t, s]) => `${t}: ${s}`).join(" · ")}</p>
        <ul className="mt-2 list-disc space-y-2 pl-4 text-xs text-muted-foreground">{result.limitations.map((s) => <li key={s}>{s}</li>)}</ul>
      </details>
      <Button variant="outline" disabled={disabled} onClick={onRevise}>Revise assumption</Button>
      {result.replay_receipt && onVerify && <div className="space-y-2 rounded-lg border border-border p-3">
        <Button variant="outline" disabled={disabled} onClick={onVerify}>{verificationPending ? "Verifying captured calculation…" : "Verify captured calculation"}</Button>
        <p className="text-xs text-muted-foreground">Reproduces these captured inputs without new market data. Not a save action. Only the two most recent snapshots are kept in this tab; browser storage may be unavailable.</p>
      </div>}
      {receiptEvicted && !result.replay_receipt && <p className="rounded-lg border border-border p-3 text-xs text-muted-foreground">
        This tab keeps the signed snapshot for the two most recent comparisons only, so this one can no longer be verified or saved. Run a fresh comparison to save it.
      </p>}
      {verificationError && <p role="alert" className="text-sm">{verificationError}</p>}
      {verification && <div role="status" className="space-y-1 rounded-lg border border-border p-3 text-sm">
        <p>Original calculation reproduced · checked {new Date(verification.verified_at).toLocaleString()}.</p>
        <p>{verification.inputs_match_now ? "Account inputs matched at that check." : "Account inputs have changed. Run a new comparison before deciding."}</p>
        {!verification.recent_capture && <p>This capture is older than 15 minutes. Verification does not refresh quotes.</p>}
        <p className="text-xs text-muted-foreground">{verification.notice}</p>
      </div>}
      {result.replay_receipt?.save_available && onSave && !saved && <div className="space-y-2 rounded-lg border border-border p-3">
        {!confirmOpen ? <Button ref={saveRef} disabled={disabled} onClick={() => { setConsent(false); setConfirmOpen(true); }}>Save as draft plan</Button> : <form className="space-y-3" aria-label="Confirm draft plan" onSubmit={(e) => { e.preventDefault(); if (consent && !disabled) { setConfirmOpen(false); setConsent(false); onSave(); } }}>
          <p className="text-sm">Save this assumption and the server-verified captured calculation, not a trade. The server will check the portfolio version and reject a new save after 15 minutes; this does not refresh quotes.</p>
          <label htmlFor={consentId} className="flex items-start gap-2 text-sm"><input ref={consentRef} id={consentId} type="checkbox" checked={consent} disabled={disabled} onChange={(e) => setConsent(e.target.checked)} />I confirm saving this hypothetical comparison as a draft. My holdings will not change.</label>
          <div className="flex flex-wrap gap-2"><Button type="submit" disabled={disabled || !consent}>Confirm and save draft</Button><Button type="button" variant="outline" disabled={disabled} onClick={() => { setConsent(false); restoreFocus.current = true; setConfirmOpen(false); }}>Cancel save</Button></div>
        </form>}
      </div>}
      {savePending && <p role="status" className="text-sm">Checking saved calculation…</p>}
      {saveError && <p role="alert" className="text-sm">{saveError}</p>}
      {saved && <div role="status" className="space-y-1 rounded-lg border border-border p-3 text-sm">
        <p>{savedNeedsCheck ? "This tab remembers a saved plan. Check its server record to confirm it still exists." : `Draft saved · ${new Date(saved.confirmed_at).toLocaleString()}`}</p>
        {!savedNeedsCheck && <p>{saved.notice}</p>}
        <p className="break-all text-xs text-muted-foreground">Plan {saved.plan_id}</p>
        <Link href="/analyze?view=plan" className="inline-block text-sm underline">Open saved risk plans</Link>
      </div>}
      {(saved || saveError) && onRetrieveSaved && <Button variant="outline" disabled={disabled} onClick={onRetrieveSaved}>Check saved record</Button>}
      <p className="text-xs text-muted-foreground">Recomputing captures fresh inputs for both sides. {saved && !savedNeedsCheck ? "The draft keeps the original calculation; edits to plan notes do not update its evidence." : "A comparison alone does not save a risk plan."}</p>
    </section>
  );
}
