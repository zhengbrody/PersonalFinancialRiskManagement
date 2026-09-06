import { z } from "zod";

export const changeDraftSchema = z.object({
  ticker: z.string(),
  amount: z.string(),
  proceeds: z.enum(["cash", "repay_margin"]),
});
export type ChangeDraft = z.infer<typeof changeDraftSchema>;
export const emptyChange: ChangeDraft = { ticker: "", amount: "", proceeds: "cash" };
const sideSchema = z.object({
  gross_assets: z.number(), net_equity: z.number(), cash: z.number(), margin: z.number(),
  leverage: z.number(), largest_position_weight: z.number(), annual_volatility: z.number(),
  var_1d_95_usd: z.number(), cvar_1d_95_usd: z.number(),
});
export const changeComparisonSchema = z.object({
  result_id: z.string().uuid(), portfolio_id: z.string().uuid(), computed_at: z.string().datetime({ offset: true }),
  snapshot_digest: z.string(), methodology_version: z.string(),
  assumptions: z.object({ expected_portfolio_id: z.string().uuid(), ticker: z.string(), amount: z.number(), proceeds: z.enum(["cash", "repay_margin"]) }),
  price_as_of: z.string(), history_start: z.string(), observations: z.number().int(),
  sources: z.record(z.string(), z.string()), baseline: sideSchema, candidate: sideSchema,
  limitations: z.array(z.string()),
});
export type ChangeComparison = z.infer<typeof changeComparisonSchema>;
export function isChangeRequest(text: string) {
  return /^(test a change|测试变更)[.!。！]?$/i.test(text.trim());
}
