/** Optional server journal. Retrieving a run never starts another analysis. */
import { z } from "zod";
import { apiFetch, ApiError } from "./api";
import { riskCheckSchema } from "./risk-check";

export const savedRunSchema = z.object({
  id: z.string().uuid(),
  portfolio_id: z.string().uuid(),
  state: z.enum(["running", "completed", "failed", "cancelled", "interrupted"]),
  created_at: z.string().datetime({ offset: true }),
  expires_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  result: riskCheckSchema.nullable(),
  error_code: z.enum(["analysis_failed", "run_expired"]).nullable(),
}).refine((run) => (run.state === "completed") === (run.result !== null), {
  message: "Completed runs must carry a result",
});
export type SavedRun = z.infer<typeof savedRunSchema>;

export function savedRunsEnabled() {
  return process.env.NEXT_PUBLIC_COPILOT_RUNS_ENABLED === "true";
}

function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, 2500);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export async function loadSavedRun(
  id: string,
  portfolioId: string,
  token: string | null,
  signal: AbortSignal,
  operation: "start" | "retrieve" | "cancel",
): Promise<SavedRun> {
  const base = "/api/v1/copilot/runs";
  let next: "start" | "retrieve" | "cancel" = operation;
  while (!signal.aborted) {
    const run = await apiFetch<SavedRun>(
      next === "start" ? base : `${base}/${id}${next === "cancel" ? "/cancel" : ""}`,
      {
        method: next === "retrieve" ? "GET" : "POST",
        authToken: token ?? undefined,
        signal,
        ...(next === "start" ? { body: { id, expected_portfolio_id: portfolioId } } : {}),
        schema: savedRunSchema,
      },
    );
    if (run.id !== id || run.portfolio_id !== portfolioId ||
        (run.result && run.result.portfolio_id !== portfolioId)) {
      throw new ApiError(409, "run_scope_mismatch", "The saved result does not match this portfolio and request.");
    }
    if (run.state !== "running") return run;
    // An idempotent start may find a run already running in another request.
    // Poll only: no analysis replay, even after a browser refresh.
    await pause(signal);
    next = "retrieve";
  }
  throw new DOMException("Aborted", "AbortError");
}
