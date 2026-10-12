import { z } from "zod";

// A research hypothesis carried into the comparison. Only the id, subject and
// the price change the USER types are sent; the claim is display-only.
export const hypothesisDraftSchema = z.object({
  id: z.string(), subject: z.string(), claim: z.string().max(300),
  pct: z.string(), confirmed: z.boolean(),
});
export type HypothesisDraft = z.infer<typeof hypothesisDraftSchema>;
export const changeDraftSchema = z.object({
  ticker: z.string(),
  amount: z.string(),
  proceeds: z.enum(["cash", "repay_margin"]),
  hypothesis: hypothesisDraftSchema.optional(),
});
export type ChangeDraft = z.infer<typeof changeDraftSchema>;
export const emptyChange: ChangeDraft = { ticker: "", amount: "", proceeds: "cash" };
const receiptSchema = z.object({ record: z.string().max(512000), signature: z.string().regex(/^[a-f0-9]{64}$/), save_available: z.boolean().default(false) });
const sideSchema = z.object({
  gross_assets: z.number(), net_equity: z.number(), cash: z.number(), margin: z.number(),
  leverage: z.number(), largest_position_weight: z.number(), annual_volatility: z.number().nullable(),
  var_1d_95_usd: z.number().nullable(), cvar_1d_95_usd: z.number().nullable(),
  option_assets: z.number().default(0), option_liabilities: z.number().default(0),
});
export const changeComparisonSchema = z.object({
  result_id: z.string().uuid(), portfolio_id: z.string().uuid(), computed_at: z.string().datetime({ offset: true }),
  snapshot_digest: z.string(), methodology_version: z.string(),
  assumptions: z.object({ expected_portfolio_id: z.string().uuid(), ticker: z.string(), amount: z.number(), proceeds: z.enum(["cash", "repay_margin"]),
    hypothesis: z.object({ hypothesis_id: z.string(), subject: z.string(), price_change_pct: z.number(), basis: z.literal("user_assumption"), user_confirmed: z.literal(true) }).nullable().optional() }),
  hypothesis_scenario: z.object({
    hypothesis_id: z.string(), subject: z.string(), price_change_pct: z.number(), basis: z.literal("user_assumption"),
    status: z.enum(["computed", "not_computable"]), reason: z.enum(["subject_not_held", "subject_has_options"]).nullable(),
    subject_value_baseline: z.number().nullable(), subject_value_candidate: z.number().nullable(),
    baseline_pnl: z.number().nullable(), candidate_pnl: z.number().nullable(),
    baseline_equity: z.number().nullable(), candidate_equity: z.number().nullable(),
  }).nullable().optional(),
  price_as_of: z.string(), history_start: z.string(), observations: z.number().int(),
  sources: z.record(z.string(), z.string()), baseline: sideSchema, candidate: sideSchema,
  limitations: z.array(z.string()),
  risk_method: z.enum(["historical_equity", "mixed_instant_stress"]).default("historical_equity"),
  option_quote_basis: z.string().nullable().optional(),
  replay_receipt: receiptSchema.nullable().optional(),
  scenarios: z.array(z.object({ label: z.string(), shocks: z.record(z.string(), z.number()), iv_shift: z.number(), horizon_days: z.number(),
    baseline_pnl: z.number(), candidate_pnl: z.number(), baseline_equity: z.number(), candidate_equity: z.number() })).default([]),
  option_groups: z.array(z.object({ underlying: z.string(), expiry: z.string(), name: z.string(), leg_count: z.number(),
    mark_basis_max_loss: z.number().nullable(), mark_basis_max_gain: z.number().nullable() })).default([]),
});
export type ChangeComparison = z.infer<typeof changeComparisonSchema>;
export const comparisonVerificationSummarySchema = z.object({
  verified_at: z.string().datetime({ offset: true }), inputs_match_now: z.boolean(),
  snapshot_age_seconds: z.number().int().nonnegative(), recent_capture: z.boolean(), notice: z.string(),
});
export const comparisonVerificationSchema = comparisonVerificationSummarySchema.extend({ result: changeComparisonSchema });
export type ComparisonVerification = z.infer<typeof comparisonVerificationSummarySchema>;
export const savedComparisonSummarySchema = z.object({
  plan_id: z.string().uuid(), portfolio_id: z.string().uuid(), result_id: z.string().uuid(),
  confirmed_at: z.string().datetime({ offset: true }), notice: z.string(),
});
export const savedComparisonSchema = savedComparisonSummarySchema.extend({ result: changeComparisonSchema });
export type SavedComparison = z.infer<typeof savedComparisonSummarySchema>;
export function isChangeRequest(text: string) {
  return /^(test a change|测试变更)[.!。！]?$/i.test(text.trim());
}

/** Validates a carried hypothesis draft. Returns the request fragment, an error, or nothing. */
export function hypothesisRequest(draft: HypothesisDraft | undefined):
  { ok: true; value: { hypothesis_id: string; subject: string; price_change_pct: number; basis: "user_assumption"; user_confirmed: true } | undefined } | { ok: false; error: string } {
  if (!draft) return { ok: true, value: undefined };
  const pct = Number(draft.pct);
  if (!/^-?\d+(\.\d{1,2})?$/.test(draft.pct.trim()) || !Number.isFinite(pct) || pct === 0 || pct < -95 || pct > 100)
    return { ok: false, error: "Enter your own price change for the research assumption: a non-zero percentage from -95 to 100, or remove it." };
  if (!draft.confirmed)
    return { ok: false, error: "Confirm that the price change is your own assumption, or remove the research assumption." };
  return { ok: true, value: { hypothesis_id: draft.id, subject: draft.subject, price_change_pct: pct, basis: "user_assumption", user_confirmed: true } };
}
