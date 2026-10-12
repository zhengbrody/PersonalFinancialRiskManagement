import { z } from "zod";
import { savedComparisonSchema } from "./copilot-compare";
import { fundingResultSchema } from "./copilot-funding";
import { putResultSchema } from "./copilot-put";

/** Build-time gate; pair with backend MINDMARKET_PLAN_HISTORY_ENABLED. Default off. */
export function planHistoryEnabled() {
  return process.env.NEXT_PUBLIC_PLAN_HISTORY_ENABLED === "true";
}

const kindSchema = z.enum(["comparison", "cash_secured_put", "funding_scenarios"]);
export const savedPlanItemSchema = z.object({
  kind: kindSchema, plan_id: z.string().uuid(), portfolio_id: z.string().uuid(),
  confirmed_at: z.string(), captured_at: z.string(), methodology_version: z.string(), summary: z.string(),
  evidence_sha256: z.string().regex(/^[a-f0-9]{64}$/), signature_verified: z.literal(true),
});
export type SavedPlanItem = z.infer<typeof savedPlanItemSchema>;
export const savedPlanPageSchema = z.object({
  plans: z.array(savedPlanItemSchema).max(20), next_cursor: z.string().nullable(),
  unverified_records: z.number().int().nonnegative(), order: z.literal("stable_plan_id"),
});
const savedBase = { plan_id: z.string().uuid(), portfolio_id: z.string().uuid(), confirmed_at: z.string() };
export const savedPlanDetailSchema = z.object({
  item: savedPlanItemSchema,
  comparison: savedComparisonSchema.nullable().optional(),
  put: z.object({ ...savedBase, result: putResultSchema }).nullable().optional(),
  funding: z.object({ ...savedBase, result: fundingResultSchema }).nullable().optional(),
}).superRefine((value, ctx) => {
  const set = [value.comparison, value.put, value.funding].filter(Boolean).length;
  const match = { comparison: value.comparison, cash_secured_put: value.put, funding_scenarios: value.funding }[value.item.kind];
  if (set !== 1 || !match) ctx.addIssue({ code: "custom", message: "Saved plan kind mismatch" });
});
export type SavedPlanDetail = z.infer<typeof savedPlanDetailSchema>;

const windowSchema = z.object({ price_as_of: z.string(), history_start: z.string(), observations: z.number().int() });
const num = z.number().nullable();
export const metricReviewSchema = z.object({
  plan_id: z.string().uuid(), portfolio_id: z.string().uuid(), kind: kindSchema, reviewed_at: z.string(),
  status: z.enum(["comparable", "method_changed", "not_computable"]), status_reason: z.string().nullable(),
  method: z.object({
    contract_version: z.literal("plan-review-metrics-v1"), original_method_version: z.string(),
    current_method_version: z.string(), same_method: z.boolean(), reproduced: z.boolean().nullable(),
  }).nullable(),
  original_window: windowSchema.nullable(), market_window: windowSchema.nullable(), account_window: windowSchema.nullable(),
  account_changes: z.array(z.string()),
  metrics: z.array(z.object({
    metric_id: z.string(), label: z.string(), unit: z.enum(["usd", "ratio", "fraction", "fraction_per_year"]), horizon: z.string(),
    original: num, original_inputs_current_method: num, original_holdings_current_prices: num, current: num,
    method_change: num, market_change: num, account_change: num, total_change: num, not_computable_reason: z.string().nullable(),
  })),
  decomposition: z.literal("sequential_market_then_account"), notes: z.array(z.string()),
  realised_return_attribution: z.literal(false), holdings_changed_by_review: z.literal(false), live_quote_checked: z.literal(false),
});
export type MetricReview = z.infer<typeof metricReviewSchema>;

export function formatMetric(value: number | null, unit: MetricReview["metrics"][number]["unit"], signed = false) {
  if (value === null) return "Not computable";
  const sign = signed && value > 0 ? "+" : "";
  if (unit === "usd") return sign + value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (unit === "ratio") return `${sign}${value.toFixed(2)}×`;
  return `${sign}${(value * 100).toFixed(2)}%`;
}

/** Rounded so float noise never triggers a repeat in-session notice. */
export function reviewFingerprint(review: MetricReview) {
  return JSON.stringify([review.status, review.account_changes, review.metrics.map(m =>
    [m.metric_id, m.market_change === null ? null : Number(m.market_change.toPrecision(4)),
      m.account_change === null ? null : Number(m.account_change.toPrecision(4)), m.not_computable_reason])]);
}
