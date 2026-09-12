import { z } from "zod";
import { changeComparisonSchema } from "./copilot-compare";

export const candidateTaskSchema = z.object({
  expected_portfolio_id: z.string().uuid(),
  goal: z.enum(["increase_cash", "reduce_margin"]),
  amount: z.number().positive(), protected_holdings: z.array(z.string()), confirmed: z.boolean(),
});
export const candidateBatchSchema = z.object({
  snapshot_id: z.string().uuid(), portfolio_id: z.string().uuid(), computed_at: z.string(),
  task: candidateTaskSchema,
  baseline: changeComparisonSchema.shape.baseline.nullable(),
  candidates: z.array(changeComparisonSchema).max(2),
  preferred_result_id: z.string().uuid().nullable(),
  coverage: z.enum(["evaluated", "insufficient_data", "unsupported"]), judgment: z.string(),
  excluded: z.record(z.string(), z.string()), limitations: z.array(z.string()),
});
export const candidateRunSchema = z.object({
  id: z.string().uuid(), portfolio_id: z.string().uuid(),
  state: z.enum(["queued", "running", "completed", "failed", "cancelled", "interrupted"]),
  result: candidateBatchSchema.nullable(), error_code: z.string().nullable(),
  step: z.string(), attempts: z.number(),
}).superRefine((run, ctx) => {
  if ((run.state === "completed") !== (run.result !== null) ||
      (run.result && (run.result.portfolio_id !== run.portfolio_id ||
        run.result.candidates.some(c => c.portfolio_id !== run.portfolio_id)))) {
    ctx.addIssue({ code: "custom", message: "Invalid candidate run scope or completion" });
  }
});
export type CandidateRun = z.infer<typeof candidateRunSchema>;
