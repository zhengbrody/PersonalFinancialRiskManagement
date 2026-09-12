import { z } from "zod";

export const putRequestSchema = z.object({
  expected_portfolio_id: z.string().uuid(), underlying: z.string().regex(/^[A-Z]{1,6}$/),
  expiry: z.string(), strike: z.number().positive(), premium_per_share: z.number().positive(),
  assumed_spot: z.number().positive(), contracts: z.number().int().min(1).max(100),
  fees_total: z.number().nonnegative(), other_reserved_cash: z.number().nonnegative(),
  cash_buffer: z.number().nonnegative(), confirmed: z.boolean(),
  gross_settled_usd_cash_confirmed: z.boolean(), standard_contract_confirmed: z.boolean(),
});
export const putResultSchema = z.object({
  result_id: z.string().uuid(), portfolio_id: z.string().uuid(), computed_at: z.string(),
  snapshot_digest: z.string(), assumptions: putRequestSchema,
  methodology_version: z.literal("cash-secured-put-v1"), input_basis: z.literal("user_hypothesis_not_live_quote"),
  recorded_cash: z.number().finite(), existing_put_reserve: z.number().finite(),
  no_action_free_cash: z.number().finite(), assignment_notional: z.number().finite(),
  gross_premium: z.number().finite(), net_premium: z.number().finite(), initial_incremental_equity: z.number().finite(),
  pre_trade_funding_gap: z.number().nonnegative(), funding_status: z.enum(["covered_under_assumptions", "insufficient_cash"]),
  best_expiry_pnl: z.number().finite(), maximum_loss: z.number().nonnegative(), breakeven: z.number().finite(),
  scenarios: z.array(z.object({
    underlying_price: z.number().nonnegative(), assumes_assignment: z.boolean(),
    no_action_incremental_pnl: z.literal(0), candidate_incremental_pnl: z.number().finite(),
    shares_acquired: z.number().int().nonnegative(), cash_after_settlement: z.number().finite(),
    free_cash_after_reserves: z.number().finite(), funding_gap_after_reserves: z.number().nonnegative(),
  })).min(1).max(7), limitations: z.array(z.string()),
  source_url: z.literal("https://www.optionseducation.org/strategies/all-strategies/cash-secured-put"),
  save_available: z.literal(false),
}).superRefine((result, ctx) => {
  if (result.portfolio_id !== result.assumptions.expected_portfolio_id ||
      !result.assumptions.confirmed || !result.assumptions.gross_settled_usd_cash_confirmed ||
      !result.assumptions.standard_contract_confirmed) {
    ctx.addIssue({ code: "custom", message: "Put result scope or confirmation mismatch" });
  }
});
export type PutResult = z.infer<typeof putResultSchema>;
