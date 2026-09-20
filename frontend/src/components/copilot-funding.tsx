"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { ChangeComparison } from "@/lib/copilot-compare";
import { fundingResultSchema, sameFundingRisk, type FundingResult } from "@/lib/copilot-funding";
import { putRequestSchema } from "@/lib/copilot-put";
import { initialPutFields, putFieldLabels } from "@/lib/put-fields";
import { CopilotFundingPlans } from "./copilot-funding-plans";
import { FundingRiskInputs } from "./funding-risk-inputs";
import { FundingAccountRisk } from "./funding-account-risk";
import type { FundingRiskInputs as RiskInputs } from "@/lib/funding-risk-inputs";
import { Button } from "./ui/button";

const money = (value: number) => value.toLocaleString("en-US", { style: "currency", currency: "USD" });
const titles = { no_action: "Keep unchanged", sale_keep_cash_and_put: "Reduce holding, retain cash, add Put", sale_repay_margin_and_put: "Reduce holding, repay debt, add Put" };

export function CopilotFunding({ source, token, protectedHoldings }: {
  source: ChangeComparison; token: string | null; protectedHoldings: string[];
}) {
  const [fields, setFields] = useState(initialPutFields);
  const [risk, setRisk] = useState<RiskInputs | null>(null);
  const [riskValid, setRiskValid] = useState(true);
  const [saleFees, setSaleFees] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [cashConfirmed, setCashConfirmed] = useState(false);
  const [standard, setStandard] = useState(false);
  const [result, setResult] = useState<FundingResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  const protectedKey = JSON.stringify(protectedHoldings);
  useEffect(() => {
    setResult(null); setConfirmed(false); setCashConfirmed(false); setStandard(false); setError(""); setBusy(false);
    return () => active.current?.abort();
  }, [token, source.result_id, source.portfolio_id, protectedKey]);
  function invalidate() { setResult(null); setConfirmed(false); setCashConfirmed(false); setStandard(false); }
  async function calculate() {
    const abort = new AbortController(); active.current?.abort(); active.current = abort;
    setBusy(true); setError(""); setResult(null);
    try {
      if (!riskValid) throw new Error("Complete or disable account-wide expiry scenarios.");
      if (Object.values(fields).some(value => value.trim() === "") || !saleFees.trim()) throw new Error("Complete all assumptions, including fees and cash reserves.");
      const put = putRequestSchema.parse({
        expected_portfolio_id: source.portfolio_id,
        underlying: fields.underlying.trim().toUpperCase(), expiry: fields.expiry,
        ...Object.fromEntries(Object.entries(fields).filter(([key]) => !["underlying", "expiry"].includes(key)).map(([key, value]) => [key, Number(value)])),
        confirmed, gross_settled_usd_cash_confirmed: cashConfirmed, standard_contract_confirmed: standard,
      });
      const value = await apiFetch("/api/v1/copilot/funding-scenarios", {
        method: "POST", authToken: token ?? undefined, signal: abort.signal, schema: fundingResultSchema,
        body: { expected_portfolio_id: source.portfolio_id, source_result_id: source.result_id,
          receipt: source.replay_receipt, put, protected_holdings: protectedHoldings, sale_fees: Number(saleFees), risk, confirmed },
      });
      const checked = fundingResultSchema.parse(value);
      if (checked.portfolio_id !== source.portfolio_id || checked.source_result_id !== source.result_id || checked.sale_ticker !== source.assumptions.ticker || checked.snapshot_digest !== source.snapshot_digest ||
          !sameFundingRisk(checked.assumptions.risk, risk) || checked.assumptions.sale_fees !== Number(saleFees) || JSON.stringify(checked.assumptions.protected_holdings) !== protectedKey ||
          checked.assumptions.expected_portfolio_id !== source.portfolio_id || checked.assumptions.source_result_id !== source.result_id ||
          Object.entries(put).some(([key, value]) => checked.assumptions.put[key as keyof typeof put] !== value) ||
          checked.alternatives.some(row => row.put && Object.entries(put).some(([key, value]) => row.put!.assumptions[key as keyof typeof put] !== value))) {
        throw new Error("Funding result does not match the selected comparison and confirmed assumptions.");
      }
      if (!abort.signal.aborted) setResult(checked);
    } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : "Could not compare funding."); }
    finally { if (active.current === abort) setBusy(false); }
  }
  return <details className="rounded-xl border border-border p-3">
    <summary className="cursor-pointer text-sm font-medium">Compare this reduction with Put funding</summary>
    <p className="mt-3 text-sm">Use the captured {source.assumptions.ticker} reduction of {money(source.assumptions.amount)} to compare keeping cash and repaying debt. Nothing changes in your account.</p>
    <p className="mt-2 text-xs text-muted-foreground">Confirm manual option assumptions. Broker buying power and order eligibility are unknown. Existing option protection is preserved; unsupported combinations require another analysis.</p>
    <form className="mt-3 space-y-3" onSubmit={event => { event.preventDefault(); void calculate(); }}>
      <fieldset disabled={busy} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">{Object.entries(putFieldLabels).map(([key, label]) =>
          <label key={key} className="min-w-0 text-xs">{label}<input aria-label={`Funding ${label}`} required
            type={key === "underlying" ? "text" : key === "expiry" ? "date" : "number"}
            min={key === "contracts" ? "1" : "0"} step={key === "contracts" ? "1" : "0.01"}
            value={fields[key as keyof typeof fields]} onChange={e => { setFields(old => ({ ...old, [key]: e.target.value })); invalidate(); }}
            className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm" /></label>)}</div>
        <label className="block text-xs">Reduction fees (USD)<input aria-label="Reduction fees (USD)" required type="number" min="0" step="0.01" value={saleFees}
          onChange={e => { setSaleFees(e.target.value); invalidate(); }} className="mt-1 w-full rounded-md border border-input bg-background p-2 text-sm" /></label>
        <FundingRiskInputs key={`${source.portfolio_id}:${source.result_id}:${token}:${protectedKey}:${fields.underlying}`} expiry={fields.expiry} disabled={busy} requiredSymbols={[source.assumptions.ticker, fields.underlying]} onChange={(value, valid) => {
          if (!sameFundingRisk(value, risk) || valid !== riskValid) { setRisk(value); setRiskValid(valid); invalidate(); }
        }} />
        <label className="flex items-start gap-2 text-xs"><input className="mt-0.5 h-4 w-4 shrink-0 scroll-my-24" type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />I confirm this reduction, protected holdings and option assumptions.</label>
        <label className="flex items-start gap-2 text-xs"><input className="mt-0.5 h-4 w-4 shrink-0 scroll-my-24" type="checkbox" checked={cashConfirmed} onChange={e => setCashConfirmed(e.target.checked)} />Recorded cash is gross settled USD cash; listed put collateral and other cash holds must still be reserved.</label>
        <label className="flex items-start gap-2 text-xs"><input className="mt-0.5 h-4 w-4 shrink-0 scroll-my-24" type="checkbox" checked={standard} onChange={e => setStandard(e.target.checked)} />This is a standard, unadjusted 100-share physically settled USD equity put.</label>
      </fieldset>
      <Button type="submit" size="sm" disabled={busy || !riskValid || !token || !source.replay_receipt || !confirmed || !cashConfirmed || !standard}>{busy ? "Comparing funding…" : "Compare funding alternatives"}</Button>
    </form>
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
    {result && <section aria-label="Funding alternatives" className="mt-4 space-y-3">
      {result.alternatives.map(row => <section key={row.kind} className="rounded-lg border border-border p-3 text-sm">
        <h4 className="font-semibold">{titles[row.kind]}</h4>
        <dl className="mt-2 grid grid-cols-2 gap-2"><dt>Cash before new Put</dt><dd>{money(row.cash_before_put)}</dd>
          <dt>Debt repaid</dt><dd>{money(row.debt_repaid)}</dd><dt>Remaining debt</dt><dd>{money(row.margin_remaining)}</dd>
          <dt>Initial equity change</dt><dd>{money(row.initial_incremental_equity)}</dd>
          <dt>Largest position before new Put</dt><dd>{(row.pre_put_largest_position_weight * 100).toFixed(1)}%</dd>
          <dt>1-day 95% VaR before new Put</dt><dd>{row.pre_put_var_1d_95_usd === null ? "Unavailable" : money(row.pre_put_var_1d_95_usd)}</dd></dl>
        {row.put && <><dl className="mt-2 grid grid-cols-2 gap-2"><dt>Assignment obligation</dt><dd>{money(row.put.assignment_notional)}</dd>
          <dt>Funding gap before premium</dt><dd>{money(row.put.pre_trade_funding_gap)}</dd>
          <dt>Net option premium</dt><dd>{money(row.put.net_premium)}</dd><dt>Put maximum expiry loss</dt><dd>{money(row.put.maximum_loss)}</dd>
          <dt>Largest assignment reserve shortfall</dt><dd>{money(row.assignment_cash_shortfall)}</dd>
          <dt>Debt if that shortfall could be financed</dt><dd>{row.hypothetical_debt_if_shortfall_financed === null ? "Unknown" : money(row.hypothetical_debt_if_shortfall_financed)}</dd></dl>
          <p className="mt-2">{row.status === "financing_rules_required" ? "Financing rules and account permissions are required before judging feasibility." : row.status === "insufficient_cash" ? "Cash does not cover the assumed obligation and reserves." : "Cash covers the stated assumptions; broker approval remains unknown."}</p>
          <details className="mt-2"><summary>Put expiry funding scenarios</summary><ul className="space-y-1 pt-2">{row.put.scenarios.map(scenario => <li key={scenario.underlying_price}>Underlying {money(scenario.underlying_price)}: Put P&amp;L {money(scenario.candidate_incremental_pnl)}, cash after settlement {money(scenario.cash_after_settlement)}, reserve shortfall {money(scenario.funding_gap_after_reserves)}.</li>)}</ul></details></>}
      </section>)}
      {result.account_risk && <FundingAccountRisk risk={result.account_risk} />}
      <p className="text-xs">For the standalone Put funding rows, interest cost and broker approval of additional borrowing are unknown. Pre-Put risk metrics exclude the new option and cannot describe total post-Put portfolio risk. Broker buying power: unknown. No alternative is ranked without comparable risk and broker-rule coverage. Saving records the original assumptions, never an executed transaction.</p>
      <ul className="list-disc pl-5 text-xs">{result.limitations.map(text => <li key={text}>{text}</li>)}</ul>
      {result.receipt && <CopilotFundingPlans result={result} portfolioId={source.portfolio_id} token={token} />}
    </section>}
  </details>;
}
