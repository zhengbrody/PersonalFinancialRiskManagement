import { z } from "zod";
import { candidateRunSchema } from "./copilot-candidates";

/** Server-minted, HMAC-signed. The client only stores and echoes it. */
export const taskStateTokenSchema = z.object({
  record: z.string().min(2).max(8192),
  signature: z.string().regex(/^[0-9a-f]{64}$/),
});

const slotSchema = z.enum(["goal", "amount", "protected_holdings"]);
const goalSchema = z.enum(["increase_cash", "reduce_margin"]);

export const taskStateViewSchema = z.object({
  task_id: z.string().uuid(),
  portfolio_id: z.string().uuid(),
  kind: z.enum(["candidate_request", "clarification"]),
  status: z.enum(["needs_input", "ready_to_confirm", "confirmed", "closed"]),
  missing_inputs: z.array(slotSchema),
  pending_question: slotSchema.nullable(),
  ambiguities: z.array(z.string()),
  clarification_turns: z.number().int(),
  max_clarification_turns: z.number().int(),
  // What the user SAID in chat. Never a confirmed parameter.
  assumptions: z.object({
    goal: goalSchema.nullable(),
    amount: z.number().nullable(),
    protected_holdings: z.array(z.string()).nullable(),
  }).passthrough(),
  // What the user CONFIRMED in the typed form, versioned.
  confirmed: z.object({
    version: z.number().int().min(1),
    goal: goalSchema,
    amount: z.number().positive(),
    protected_holdings: z.array(z.string()),
    confirmed_at: z.string(),
    run_id: z.string().uuid(),
    stale: z.boolean(),
  }).nullable(),
  superseded_run_ids: z.array(z.string().uuid()),
  expires_at: z.string(),
}).passthrough();

export const taskStateEnvelopeSchema = z.object({
  outcome: z.enum(["started", "continued", "ambiguous", "unrelated", "turn_limit", "closed", "expired", "discarded"]),
  state: taskStateViewSchema.nullable(),
  token: taskStateTokenSchema.nullable(),
});

export const taskResumeSchema = z.object({
  outcome: z.enum(["needs_input", "ready_to_confirm", "continuing", "completed", "stale_account_changed", "run_missing", "run_failed", "expired", "closed"]),
  state: taskStateViewSchema,
  token: taskStateTokenSchema,
  run: candidateRunSchema.nullable(),
  dispatched: z.boolean(),
});

export type TaskStateEnvelope = z.infer<typeof taskStateEnvelopeSchema>;
export type TaskStateView = z.infer<typeof taskStateViewSchema>;
export type TaskResume = z.infer<typeof taskResumeSchema>;

/** A task that a follow-up message may continue: live, unexpired, this book. */
export function openTask(envelope: TaskStateEnvelope | null | undefined, portfolioId: string | null, now = Date.now()) {
  const state = envelope?.state;
  if (!envelope?.token || !state || state.status === "closed" || state.portfolio_id !== portfolioId) return null;
  if (Date.parse(state.expires_at) <= now) return null;
  return envelope;
}
