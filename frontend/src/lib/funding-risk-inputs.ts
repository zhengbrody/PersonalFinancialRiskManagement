export const FUNDING_OBJECTIVES = ["preserve_terminal_equity", "minimize_funding_gap", "minimize_conditional_debt"] as const;
export type FundingObjective = typeof FUNDING_OBJECTIVES[number];
export type FundingRiskInputs = {
  scenarios: Array<{ label: string; prices: Record<string, number> }>;
  annual_borrowing_rate: number | null;
  residual_risk_free_rate: number | null;
  objective: FundingObjective | null;
  objective_confirmed: boolean;
};
export type RiskInputDraft = { label: string; rows: Array<{ ticker: string; price: string }> };

/** Blank is unknown, never zero. Validate before converting UI strings. */
export function parseFundingRiskInputs(scenarios: RiskInputDraft[], rate: string, residualRate = "", objective = "", objectiveConfirmed = false): FundingRiskInputs {
  if (scenarios.length < 1 || scenarios.length > 3) throw new Error("Enter one to three price scenarios.");
  const annualRate = rate.trim() === "" ? null : Number(rate);
  if (annualRate !== null && (!Number.isFinite(annualRate) || annualRate < 0 || annualRate > 100)) throw new Error("Annual borrowing rate must be between 0% and 100%, or left blank if unknown.");
  const residual = residualRate.trim() === "" ? null : Number(residualRate);
  if (residual !== null && (!Number.isFinite(residual) || residual < 0 || residual > 20)) throw new Error("Residual-valuation risk-free rate must be between 0% and 20%, or left blank if unknown.");
  const goal = objective === "" ? null : FUNDING_OBJECTIVES.find(item => item === objective);
  if (goal === undefined) throw new Error("Choose a listed objective or none.");
  if (objectiveConfirmed && goal === null) throw new Error("Choose an objective before confirming it.");
  const labels = new Set<string>();
  const parsed = scenarios.map(scenario => {
    const label = scenario.label.trim();
    if (!label || label.length > 80) throw new Error("Give each scenario a name of 1–80 characters.");
    if (labels.has(label.toUpperCase())) throw new Error("Scenario names must be distinct.");
    labels.add(label.toUpperCase());
    if (scenario.rows.length < 1 || scenario.rows.length > 100) throw new Error("Enter one to 100 tickers per scenario.");
    const prices: Record<string, number> = {};
    for (const row of scenario.rows) {
      const ticker = row.ticker.trim().toUpperCase();
      if (!/^[A-Z][A-Z0-9.\-]{0,14}$/.test(ticker)) throw new Error("Enter a valid ticker for every price row.");
      if (Object.hasOwn(prices, ticker)) throw new Error(`Duplicate ticker ${ticker}; each ticker needs one price per scenario.`);
      const price = Number(row.price);
      if (row.price.trim() === "" || !Number.isFinite(price) || price < 0 || price > 1_000_000) throw new Error("Enter an expiry price between 0 and 1,000,000 USD for every ticker. Missing prices are not zero.");
      prices[ticker] = price;
    }
    return { label, prices };
  });
  return { scenarios: parsed, annual_borrowing_rate: annualRate === null ? null : annualRate / 100,
    residual_risk_free_rate: residual === null ? null : residual / 100, objective: goal, objective_confirmed: goal !== null && objectiveConfirmed };
}
