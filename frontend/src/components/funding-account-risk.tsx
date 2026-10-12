import type { FundingAccountRisk } from "@/lib/copilot-funding";
const usd = (value: number | null) => value === null ? "Unknown" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });
// Ratios round-trip through JSON as binary floats (0.07 * 100 = 7.000000000000001);
// display at most four decimals so the user sees the rate they typed, never noise.
const percent = (value: number) => `${(value * 100).toLocaleString("en-US", { maximumFractionDigits: 4 })}%`;
const names = { no_action: "Keep unchanged", sale_keep_cash_and_put: "Reduce holding, retain cash, add Put", sale_repay_margin_and_put: "Reduce holding, repay debt, add Put" };
export function FundingAccountRisk({ risk }: { risk: FundingAccountRisk }) {
  return <section aria-label="Account-wide expiry scenarios" className="space-y-3 text-sm">
    <h4 className="font-semibold">Account-wide expiry scenarios</h4>
    {risk.methodology_version === "funding-account-scenarios-v2" && <AccountContext risk={risk} />}
    <p>Assumed annual borrowing rate: {risk.assumptions.annual_borrowing_rate === null ? "Unknown" : percent(risk.assumptions.annual_borrowing_rate)}. Interest period: {risk.days_of_interest} days. These are hypothetical account outcomes, not forecasts or broker approval.</p>
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
          {risk.methodology_version === "funding-account-scenarios-v2" && <>
            <dt>Options still open (model value)</dt><dd>{usd(row.residual_option_value ?? null)}</dd>
            <dt>Short stock after settlement</dt><dd>{usd(row.short_stock_value ?? null)}</dd>
            <dt>Sold-stock opportunity cost (inside P&amp;L)</dt><dd>{usd(row.sold_stock_opportunity_cost ?? null)}</dd>
          </>}
        </dl>
        {row.settlement_events.length > 0 && <ul aria-label="Settlement events" className="list-disc pl-4 text-xs">{row.settlement_events.map(event => <li key={event.contract}>{event.contract}: {event.action} at {usd(event.underlying_price)} on {event.expiry} (shares {event.shares_delta}, cash {usd(event.cash_delta)})</li>)}</ul>}
        {row.not_computable.length > 0 && <ul aria-label="Not computable" className="list-disc pl-4 text-xs">{row.not_computable.map((item, at) => <li key={at}>Not computable{item.contract ? ` (${item.contract})` : ""}: {item.message}</li>)}</ul>}
      </div>)}
    </section>)}
    <ul className="list-disc pl-4">{risk.limitations.map(text => <li key={text}>{text}</li>)}</ul>
  </section>;
}

const rankingText: Record<string, string> = {
  not_requested: "No objective was chosen, so alternatives are not ranked.",
  objective_not_confirmed: "The objective was not confirmed, so alternatives are not ranked.",
  not_computable: "No ranking: some compared figures are unknown or a loss is unbounded.",
  no_dominant_alternative: "No alternative is at least as good in every scenario under your objective.",
};
function AccountContext({ risk }: { risk: FundingAccountRisk }) {
  const ranking = risk.ranking;
  return <div className="space-y-2">
    <p>Valuation date: {risk.valuation_date}. All alternatives use one captured snapshot{risk.market_snapshot ? ` (prices as of ${risk.market_snapshot.price_as_of}, id ${risk.market_snapshot.snapshot_id.slice(0, 12)})` : ""}.</p>
    {risk.broker_rules && <p>Buying power and margin requirements: unknown — {risk.broker_rules.source}</p>}
    {risk.alternatives.filter(row => row.coverage_changes.length > 0 || row.unbounded_loss).map(row => <div key={row.kind} role="note" className="rounded border border-amber-500 p-2">
      <p className="font-medium">{names[row.kind]}: option coverage changes</p>
      <ul className="list-disc pl-4">{row.coverage_changes.map(change => <li key={change.contract} className="break-words">{change.contract}: {change.before} → {change.after}. {change.reason}</li>)}
        {row.unbounded_loss && <li>An uncovered short call has unbounded loss; its collateral needs broker rules that are not connected.</li>}</ul>
    </div>)}
    {ranking && <p aria-label="Conditional ranking">{ranking.status === "preferred" && ranking.preferred_kind ? `Under your confirmed objective: ${names[ranking.preferred_kind]} is no worse in every scenario and better in at least one. Conditional arithmetic, not a recommendation.` : rankingText[ranking.status] ?? ranking.status}{ranking.status === "not_computable" && ranking.reasons.length ? ` ${ranking.reasons.join(" ")}` : ""}</p>}
  </div>;
}
