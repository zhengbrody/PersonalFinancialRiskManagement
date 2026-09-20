import type { FundingAccountRisk } from "@/lib/copilot-funding";
const usd = (value: number | null) => value === null ? "Unknown" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });
const names = { no_action: "Keep unchanged", sale_keep_cash_and_put: "Reduce holding, retain cash, add Put", sale_repay_margin_and_put: "Reduce holding, repay debt, add Put" };
export function FundingAccountRisk({ risk }: { risk: FundingAccountRisk }) {
  return <section aria-label="Account-wide expiry scenarios" className="space-y-3 text-sm">
    <h4 className="font-semibold">Account-wide expiry scenarios</h4>
    <p>Assumed annual borrowing rate: {risk.assumptions.annual_borrowing_rate === null ? "Unknown" : `${risk.assumptions.annual_borrowing_rate * 100}%`}. Interest period: {risk.days_of_interest} days. These are hypothetical account outcomes, not forecasts or broker approval.</p>
    {risk.scenarios.map(scenario => <section key={scenario.label} className="space-y-2 rounded border border-border p-2">
      <h5 className="font-medium">{scenario.label}</h5><p>Assumed expiry prices: {Object.entries(scenario.prices).map(([ticker, price]) => `${ticker} ${usd(price)}`).join(", ")}</p>
      {scenario.outcomes.map(row => <div key={row.kind} className="rounded border border-border p-2"><h6>{names[row.kind]}</h6>
        <dl className="grid grid-cols-2 gap-2">
          <dt>Net equity before interest</dt><dd>{usd(row.net_equity_before_interest)}</dd>
          <dt>Net equity after interest</dt><dd>{usd(row.net_equity_after_interest)}</dd>
          <dt>Account P&amp;L before interest</dt><dd>{usd(row.total_pnl_before_interest)}</dd>
          <dt>Account P&amp;L after interest</dt><dd>{usd(row.total_pnl)}</dd>
          <dt>Incremental P&amp;L vs unchanged</dt><dd>{usd(row.incremental_pnl_vs_no_action)}</dd>
          <dt>Borrowing cost</dt><dd>{usd(row.interest_cost)}</dd>
          <dt>Cash after interest</dt><dd>{usd(row.cash_after_interest)}</dd>
          <dt>Funding gap before interest</dt><dd>{usd(row.funding_gap_before_interest)}</dd>
          <dt>Funding gap after interest</dt><dd>{usd(row.funding_gap)}</dd>
          <dt>Debt if the gap could be financed</dt><dd>{usd(row.conditional_debt_if_gap_financed)}</dd>
          <dt>Largest position weight</dt><dd>{row.largest_position_weight === null ? "Unknown" : `${(row.largest_position_weight * 100).toFixed(1)}%`}</dd>
          <dt>Gross leverage if financed</dt><dd>{row.gross_leverage_if_gap_financed === null ? "Unknown" : `${row.gross_leverage_if_gap_financed.toFixed(2)}×`}</dd>
        </dl>
      </div>)}
    </section>)}
    <ul className="list-disc pl-4">{risk.limitations.map(text => <li key={text}>{text}</li>)}</ul>
  </section>;
}
