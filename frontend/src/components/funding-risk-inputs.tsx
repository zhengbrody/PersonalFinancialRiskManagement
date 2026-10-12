"use client";

import { useEffect, useRef, useState } from "react";
import { FUNDING_OBJECTIVES, parseFundingRiskInputs, type FundingRiskInputs as Inputs, type RiskInputDraft } from "@/lib/funding-risk-inputs";

const objectiveNames: Record<string, string> = {
  preserve_terminal_equity: "Keep the most account equity in every scenario",
  minimize_funding_gap: "Smallest cash funding gap in every scenario",
  minimize_conditional_debt: "Lowest debt if gaps were financed, in every scenario",
};
import { Button } from "./ui/button";

const initialRows = (symbols: string[]) => {
  const tickers = [...new Set(symbols.map(symbol => symbol.trim().toUpperCase()))].filter(symbol => /^[A-Z][A-Z0-9.\-]{0,14}$/.test(symbol)).slice(0, 100);
  return (tickers.length ? tickers : [""]).map(ticker => ({ ticker, price: "" }));
};

export function FundingRiskInputs({ expiry, disabled, onChange, requiredSymbols = [] }: {
  expiry: string; disabled: boolean; requiredSymbols?: string[]; onChange: (value: Inputs | null, valid: boolean) => void;
}) {
  const [enabled, setEnabled] = useState(false);
  const [scenarios, setScenarios] = useState<RiskInputDraft[]>(() => [{ label: "Scenario 1", rows: initialRows(requiredSymbols) }]);
  const [rate, setRate] = useState("");
  const [residualRate, setResidualRate] = useState("");
  const [objective, setObjective] = useState("");
  const [objectiveConfirmed, setObjectiveConfirmed] = useState(false);
  const notify = useRef(onChange);
  notify.current = onChange;
  let value: Inputs | null = null;
  let error = "";
  if (enabled) {
    try { value = parseFundingRiskInputs(scenarios, rate, residualRate, objective, objectiveConfirmed); }
    catch (e) { error = e instanceof Error ? e.message : "Check the price scenarios."; }
  }
  const serialized = JSON.stringify(value);
  const valid = !enabled || value !== null;
  useEffect(() => { notify.current(JSON.parse(serialized) as Inputs | null, valid); }, [serialized, expiry, valid]);

  function updateScenario(index: number, patch: Partial<RiskInputDraft>) {
    setScenarios(previous => previous.map((scenario, at) => at === index ? { ...scenario, ...patch } : scenario));
  }
  return <section aria-label="Optional account expiry scenarios" className="min-w-0 space-y-3 rounded border border-border p-3 text-sm">
    <label className="flex gap-2"><input type="checkbox" checked={enabled} disabled={disabled} onChange={event => setEnabled(event.target.checked)} />Include explicit account-wide expiry price scenarios</label>
    {enabled && <fieldset disabled={disabled} className="min-w-0 space-y-3">
      <p>Common expiry: {expiry || "Choose the Put expiry above"}. Enter a price for every existing stock and every option underlying, including the proposed Put underlying. The server checks complete coverage.</p>
      <p>These prices are your assumptions, not forecasts. Missing prices are never filled in. Options expiring on this date settle at these prices; options expiring earlier need a separate settlement price and are otherwise reported as not computable.</p>
      <label className="block">Annual borrowing rate (%) — leave blank if unknown<input aria-label="Annual borrowing rate (%)" type="number" min="0" max="100" step="any" value={rate} onChange={event => setRate(event.target.value)} className="ml-2 rounded border border-input bg-background p-1" /></label>
      <p className="text-xs">An explicit 0% means zero interest. Blank means borrowing cost is unknown.</p>
      <label className="block">Risk-free rate for options still open after this date (%) — leave blank if unknown<input aria-label="Residual valuation risk-free rate (%)" type="number" min="0" max="20" step="any" value={residualRate} onChange={event => setResidualRate(event.target.value)} className="ml-2 rounded border border-input bg-background p-1" /></label>
      <p className="text-xs">Options expiring later are valued with the captured quote&apos;s implied volatility and this rate. Blank leaves them, and every total that includes them, not computable.</p>
      <label className="block">Comparison objective (optional)<select aria-label="Comparison objective" value={objective} onChange={event => { setObjective(event.target.value); setObjectiveConfirmed(false); }} className="ml-2 max-w-full rounded border border-input bg-background p-1">
        <option value="">No ranking</option>
        {FUNDING_OBJECTIVES.map(item => <option key={item} value={item}>{objectiveNames[item]}</option>)}
      </select></label>
      {objective && <label className="flex gap-2"><input type="checkbox" aria-label="Confirm comparison objective" checked={objectiveConfirmed} onChange={event => setObjectiveConfirmed(event.target.checked)} />I confirm this objective. A preference is shown only if every compared figure is known for every alternative.</label>}
      {scenarios.map((scenario, index) => <div key={index} role="group" aria-label={`Price scenario ${index + 1}`} className="space-y-2 rounded border border-border p-2">
        <label className="block">Scenario name<input aria-label={`Scenario ${index + 1} name`} maxLength={80} value={scenario.label} onChange={event => updateScenario(index, { label: event.target.value })} className="ml-2 rounded border border-input bg-background p-1" /></label>
        <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th>Ticker</th><th>Price at expiry (USD)</th><th>Actions</th></tr></thead><tbody>
          {scenario.rows.map((row, rowIndex) => <tr key={rowIndex}>
            <td><input aria-label={`Scenario ${index + 1} ticker ${rowIndex + 1}`} value={row.ticker} maxLength={15} onChange={event => updateScenario(index, { rows: scenario.rows.map((old, at) => at === rowIndex ? { ...old, ticker: event.target.value.toUpperCase() } : old) })} className="w-28 rounded border border-input bg-background p-1" /></td>
            <td><input aria-label={`Scenario ${index + 1} price ${rowIndex + 1}`} type="number" min="0" max="1000000" step="any" value={row.price} onChange={event => updateScenario(index, { rows: scenario.rows.map((old, at) => at === rowIndex ? { ...old, price: event.target.value } : old) })} className="w-32 rounded border border-input bg-background p-1" /></td>
            <td><Button type="button" size="sm" variant="ghost" onClick={() => updateScenario(index, { rows: scenario.rows.filter((_, at) => at !== rowIndex) })}>Remove ticker {rowIndex + 1}</Button></td>
          </tr>)}
        </tbody></table></div>
        <Button type="button" size="sm" variant="outline" disabled={scenario.rows.length >= 100} onClick={() => updateScenario(index, { rows: [...scenario.rows, { ticker: "", price: "" }] })}>Add ticker to scenario {index + 1}</Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => setScenarios(previous => previous.filter((_, at) => at !== index))}>Remove scenario {index + 1}</Button>
      </div>)}
      <Button type="button" size="sm" variant="outline" disabled={scenarios.length >= 3} onClick={() => setScenarios(previous => [...previous, { label: Array.from({ length: 4 }, (_, at) => `Scenario ${at + 1}`).find(label => !previous.some(scenario => scenario.label.trim().toUpperCase() === label.toUpperCase()))!, rows: initialRows(requiredSymbols) }])}>Add price scenario</Button>
      {error && <p role="alert">{error}</p>}
    </fieldset>}
  </section>;
}
