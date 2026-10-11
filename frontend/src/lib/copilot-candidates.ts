import { z } from "zod";
import { changeComparisonSchema } from "./copilot-compare";
import { ApiError } from "./api";

export const candidateTaskSchema = z.object({
  expected_portfolio_id: z.string().uuid(),
  goal: z.enum(["increase_cash", "reduce_margin"]),
  amount: z.number().positive(), protected_holdings: z.array(z.string()), confirmed: z.boolean(),
});
export type CandidateTask = z.infer<typeof candidateTaskSchema>;
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

/**
 * What a refused start/resume of a background decision run means for the
 * SAME run id. Codes come from backend/app/services/copilot_jobs.py:
 *   - too_many_active_runs (429): nothing reserved; the owner already has a
 *     queued/running job (database-enforced, one per owner).
 *   - analysis_queue_full (429): two variants, distinguished only by message.
 *     "Nothing was saved" = refused before reserving. "Saved as queued but not
 *     started" = the record exists but no worker took it; retrying the SAME id
 *     with the SAME task is idempotent and dispatches it. An unrecognised
 *     variant is treated as "may be saved" because the safe action (retry the
 *     same id) is correct in both cases and never duplicates work.
 *   - run_conflict (409): the database refused this record; it cannot be
 *     reused. Definite failure; start a fresh calculation.
 */
export type RunStartFailure =
  | { kind: "active_elsewhere"; message: string }
  | { kind: "queue_full_not_saved"; message: string }
  | { kind: "queued_not_started"; certain: boolean; message: string }
  | { kind: "run_conflict"; message: string }
  | { kind: "other" };

export function classifyRunStartFailure(error: unknown): RunStartFailure {
  if (!(error instanceof ApiError)) return { kind: "other" };
  if (error.code === "too_many_active_runs") {
    return { kind: "active_elsewhere", message: "Another background analysis is already queued or running for your account. Open it from recent analyses, or cancel it, before starting another. Nothing new was saved." };
  }
  if (error.code === "analysis_queue_full") {
    if (/nothing was saved/i.test(error.message)) {
      return { kind: "queue_full_not_saved", message: "The analysis queue is full. Nothing was saved and nothing is running. Try again in a moment." };
    }
    const certain = /^saved as queued/i.test(error.message);
    return {
      kind: "queued_not_started", certain,
      message: certain
        ? "Saved as queued, but not started: the analysis queue is full and nothing is running yet. Try starting again; it reuses this same request and will not create a duplicate."
        : "The analysis queue is full. This request may have been saved as queued, but it is not running. Try starting again; it reuses this same request and will not create a duplicate.",
    };
  }
  if (error.code === "run_conflict") {
    return { kind: "run_conflict", message: "This analysis record was refused and cannot be reused. Nothing is running for it. Start a fresh calculation." };
  }
  return { kind: "other" };
}
