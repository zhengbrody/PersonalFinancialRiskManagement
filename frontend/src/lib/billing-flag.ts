/**
 * Free-beta flag.
 *
 * When `NEXT_PUBLIC_BILLING_ENABLED === "false"` the product runs as a free
 * beta: ALL user-facing billing / pricing / credits / upgrade UI is hidden.
 * Backend metering, cost logging, the owner/admin dashboard, and the entire
 * Stripe infrastructure stay intact — this flag only gates the UI.
 *
 * Defaults to ENABLED (anything other than the literal "false"), so existing
 * behavior + tests are unchanged until the env var is explicitly set. The
 * deployed beta build sets `NEXT_PUBLIC_BILLING_ENABLED=false`.
 *
 * Implemented as a function (not a cached const) so it re-reads `process.env`
 * each call — easy to vary per test via `vi.stubEnv`.
 */
export function isBillingEnabled(): boolean {
  return process.env.NEXT_PUBLIC_BILLING_ENABLED !== "false";
}

/** Copy shown where billing UI used to be, during the free beta. */
export const FREE_BETA_TITLE = "Free Beta";
export const FREE_BETA_BODY =
  "All core features are currently open during beta. Usage limits may apply to keep the service reliable.";

/** Friendly reframe of a quota/429 error when billing is disabled — never a payment prompt. */
export const BETA_LIMIT_MESSAGE =
  "You've hit a temporary usage limit. Limits keep the beta reliable — please try again in a little while.";
