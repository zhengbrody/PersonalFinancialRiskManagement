import { z } from "zod";
import { putRequestSchema, putResultSchema } from "./copilot-put";

const finite = z.number().finite();
const optionalNumber = finite.nullable();
export const fundingRiskAssumptionsSchema = z.object({
  scenarios: z.array(z.object({ label: z.string().min(1).max(80), prices: z.record(z.string(), finite.min(0).max(1_000_000)) })).min(1).max(3),
  annual_borrowing_rate: finite.min(0).max(1).nullable(),
  residual_risk_free_rate: finite.min(0).max(0.2).nullable().default(null),
  objective: z.enum(["preserve_terminal_equity", "minimize_funding_gap", "minimize_conditional_debt"]).nullable().default(null),
  objective_confirmed: z.boolean().default(false),
});
export function sameFundingRisk(a: unknown, b: unknown): boolean {
  const canonical = (value: unknown): string => JSON.stringify(value, (_key, item) => item && typeof item === "object" && !Array.isArray(item) ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
  return canonical(a ?? null) === canonical(b ?? null);
}
const nullableRecord = z.record(z.string(), finite).nullable();
const notComputableSchema = z.object({ code: z.string(), contract: z.string().nullish(), message: z.string() });
const coverageSchema = z.object({ contract: z.string(), underlying: z.string(), option_type: z.enum(["call", "put"]), side: z.enum(["long", "short"]),
  expiry: z.string(), strike: finite, contracts: z.number().int(), coverage: z.string(), covered_by: z.string().nullish(),
  max_loss_excl_premium: optionalNumber, collateral: z.string() });
const outcomeSchema = z.object({
  kind: z.enum(["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]),
  positions: nullableRecord, position_values: nullableRecord, stock_assets: optionalNumber,
  initial_net_equity: finite, cash_before_interest: optionalNumber, cash_after_interest: optionalNumber, principal_debt: finite,
  interest_cost: optionalNumber, net_equity_before_interest: optionalNumber, net_equity_after_interest: optionalNumber,
  total_pnl_before_interest: optionalNumber, total_pnl: optionalNumber, incremental_pnl_vs_no_action: optionalNumber,
  assignment_shares: nullableRecord, assignment_cash_paid: optionalNumber, funding_gap_before_interest: optionalNumber,
  funding_gap: optionalNumber, conditional_debt_if_gap_financed: optionalNumber, largest_position_weight: optionalNumber, gross_leverage_if_gap_financed: optionalNumber,
  snapshot_id: z.string().nullish(), short_stock_value: optionalNumber.optional(), residual_option_value: optionalNumber.optional(),
  sold_stock_opportunity_cost: optionalNumber.optional(), min_cash_through_horizon: optionalNumber.optional(),
  residual_valuations: z.array(z.object({ contract: z.string(), iv: optionalNumber, iv_source: z.string(), rate: optionalNumber, position_value: optionalNumber })).default([]),
  settlement_events: z.array(z.object({ contract: z.string(), expiry: z.string(), underlying_price: finite, action: z.string(), shares_delta: finite, cash_delta: finite })).default([]),
  not_computable: z.array(notComputableSchema).default([]),
});
export const fundingAccountRiskSchema = z.object({
  methodology_version: z.enum(["funding-common-expiry-v1", "funding-account-scenarios-v2"]), portfolio_id: z.string().uuid(), source_result_id: z.string().uuid(), captured_at: z.string(),
  assumptions: fundingRiskAssumptionsSchema, days_of_interest: z.number().int().nonnegative(), preferred_alternative: z.null(), limitations: z.array(z.string()),
  valuation_date: z.string().nullish(),
  market_snapshot: z.object({ snapshot_id: z.string(), price_as_of: z.string(), quote_time_note: z.string() }).nullish(),
  broker_rules: z.object({ provider_id: z.literal("unknown"), rule_version: z.string(), source: z.string() }).nullish(),
  ranking: z.object({ status: z.string(), objective: z.string().nullish(), preferred_kind: z.enum(["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]).nullish(), reasons: z.array(z.string()) }).nullish(),
  alternatives: z.array(z.object({ kind: z.enum(["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]), snapshot_id: z.string(),
    coverage_at_capture: z.array(coverageSchema), coverage_changes: z.array(z.object({ contract: z.string(), before: z.string(), after: z.string(), reason: z.string() })),
    unbounded_loss: z.boolean(), buying_power: z.object({ status: z.literal("unknown"), reason: z.string() }) })).default([]),
  scenarios: z.array(z.object({ label: z.string(), prices: z.record(z.string(), finite), outcomes: z.array(outcomeSchema).length(3) })).min(1).max(3),
}).superRefine((risk, ctx) => {
  if (!sameFundingRisk(risk.scenarios.map(({ label, prices }) => ({ label, prices })), risk.assumptions.scenarios) || risk.scenarios.some(row => new Set(row.outcomes.map(outcome => outcome.kind)).size !== 3)
    || (risk.market_snapshot && [...risk.alternatives.map(row => row.snapshot_id), ...risk.scenarios.flatMap(row => row.outcomes.map(outcome => outcome.snapshot_id))].some(id => id !== risk.market_snapshot?.snapshot_id))) ctx.addIssue({ code: "custom", message: "Account scenario evidence mismatch" });
});
export type FundingAccountRisk = z.infer<typeof fundingAccountRiskSchema>;

export const fundingResultSchema = z.object({
  result_id: z.string().uuid(), computed_at: z.string(), captured_at: z.string(),
  methodology_version: z.literal("funding-scenarios-v1"),
  receipt: z.object({ record: z.string(), signature: z.string(), save_available: z.boolean() }).nullish(),
  assumptions: z.object({ expected_portfolio_id: z.string().uuid(), source_result_id: z.string().uuid(),
    put: putRequestSchema, risk: fundingRiskAssumptionsSchema.nullish().transform(value => value ?? null), protected_holdings: z.array(z.string()), sale_fees: z.number().finite().nonnegative(), confirmed: z.literal(true) }),
  portfolio_id: z.string().uuid(), source_result_id: z.string().uuid(), snapshot_digest: z.string(),
  account_risk: fundingAccountRiskSchema.nullish().transform(value => value ?? null),
  sale_ticker: z.string(), sale_price: z.number().finite().positive(),
  broker_buying_power: z.null(), preferred_alternative: z.null(), limitations: z.array(z.string()),
  alternatives: z.array(z.object({
    kind: z.enum(["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]),
    cash_before_put: z.number().finite(), margin_remaining: z.number().finite().nonnegative(),
    debt_repaid: z.number().finite().nonnegative(), sale_proceeds_net: z.number().finite(),
    shares_sold: z.number().finite().nonnegative(), initial_incremental_equity: z.number().finite(),
    assignment_cash_shortfall: z.number().finite().nonnegative(),
    hypothetical_debt_if_shortfall_financed: z.number().finite().nonnegative().nullable(),
    pre_put_largest_position_weight: z.number().finite(), pre_put_var_1d_95_usd: z.number().finite().nullable(),
    expiry_funding: z.array(z.object({ underlying_price: z.number().finite(), assignment_cash_shortfall: z.number().finite(),
      hypothetical_debt_if_shortfall_financed: z.number().finite(), interest_cost: z.null() })).max(7),
    status: z.enum(["no_action", "covered_under_assumptions", "insufficient_cash", "financing_rules_required"]),
    put: putResultSchema.nullish(),
  })).length(3),
}).superRefine((value, ctx) => {
  const risk = value.account_risk;
  if ((value.assumptions.risk === null) !== (risk === null) || (risk && (risk.portfolio_id !== value.portfolio_id || risk.source_result_id !== value.source_result_id || risk.captured_at !== value.captured_at || !sameFundingRisk(risk.assumptions, value.assumptions.risk)))) ctx.addIssue({ code: "custom", message: "Account risk scope or assumptions mismatch" });
  const kinds = value.alternatives.map(row => row.kind);
  if (new Set(kinds).size !== 3) ctx.addIssue({ code: "custom", message: "Missing comparison alternative" });
  for (const row of value.alternatives) {
    if (row.kind !== "no_action" && row.margin_remaining > 0 && row.status !== "financing_rules_required") ctx.addIssue({ code: "custom", message: "Remaining debt requires financing rules" });
    if (row.kind === "no_action" ? row.put != null || row.status !== "no_action" :
        !row.put || row.put.portfolio_id !== value.portfolio_id) {
      ctx.addIssue({ code: "custom", message: "Funding alternative scope mismatch" });
    }
  }
});
export type FundingResult = z.infer<typeof fundingResultSchema>;
