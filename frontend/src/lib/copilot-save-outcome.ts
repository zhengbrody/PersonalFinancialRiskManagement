/**
 * Classify a failed save / read-back of a signed Copilot calculation.
 *
 * Deny-list, not an allow-list: a write MAY have committed unless the server
 * code provably precedes the transaction. Every confirm endpoint validates the
 * stored row AFTER the RPC commits, so a post-commit rejection (or a network
 * failure, timeout, schema drift, unknown code) can arrive with a draft plan
 * already created. Reporting those as definite failure would tell the user the
 * opposite of what happened; reporting a definite pre-commit rejection as
 * "uncertain" hides a concrete reason the user must act on (expired capture,
 * changed portfolio, missing consent).
 */
import { ApiError } from "./api";

export type SaveFailure = {
  /** The server provably rejected before writing anything. */
  definite: boolean;
  /** A read-back found no record: the plan is gone (deleted or never saved). */
  vanished: boolean;
  message: string;
};

/** Pre-commit codes for POST /copilot/compare-change/{id}/confirm and its /saved read. */
export const COMPARISON_SETTLED_CODES: readonly string[] = [
  "confirmation_required", "analysis_busy", "comparison_expired", "comparison_stale",
  "portfolio_changed", "comparison_snapshot_too_large", "comparison_save_unavailable",
  "saved_comparison_missing", "unauthorized", "forbidden",
];
export const COMPARISON_MISSING_CODE = "saved_comparison_missing";

/** Pre-commit codes for POST /copilot/funding-plans/{id}/confirm and its GET read. */
export const FUNDING_PLAN_SETTLED_CODES: readonly string[] = [
  "confirmation_required", "risk_busy", "funding_save_disabled", "funding_plan_expired",
  "funding_implementation_changed", "funding_source_mismatch", "funding_replay_mismatch",
  "funding_plan_stale", "funding_plan_missing", "portfolio_changed", "unauthorized", "forbidden",
];
export const FUNDING_PLAN_MISSING_CODE = "funding_plan_missing";

/** Pre-commit codes for POST /copilot/put-plans/{id}/confirm. */
export const PUT_PLAN_SETTLED_CODES: readonly string[] = [
  "confirmation_required", "put_save_disabled", "put_plans_unavailable", "put_signing_unavailable",
  "put_scenario_disabled", "put_plan_expired", "put_implementation_changed", "put_replay_mismatch",
  "put_plan_stale", "put_snapshot_too_large", "put_plan_missing", "portfolio_changed",
  "unauthorized", "forbidden",
];

export function classifySaveFailure(error: unknown, options: {
  settled: readonly string[];
  missing?: string;
  /** True when the failed call was a read-back, not a write. */
  retrieve: boolean;
  uncertainSave: string;
  uncertainRead: string;
  vanished: string;
}): SaveFailure {
  const api = error instanceof ApiError ? error : null;
  if (options.retrieve && api && options.missing && api.code === options.missing) {
    return { definite: true, vanished: true, message: options.vanished };
  }
  if (api && options.settled.includes(api.code)) {
    return { definite: true, vanished: false, message: api.message };
  }
  return { definite: false, vanished: false, message: options.retrieve ? options.uncertainRead : options.uncertainSave };
}
