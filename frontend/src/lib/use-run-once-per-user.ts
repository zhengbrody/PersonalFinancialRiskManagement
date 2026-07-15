import { useEffect, useRef } from "react";

/**
 * Run `fn` once per signed-in user. Keyed on `userId` (the stable id — NOT the
 * user OBJECT, which Supabase recreates on every token refresh / tab refocus),
 * with a ref guard so a refresh/refocus doesn't re-fire while a genuine user
 * switch (sign out → in as someone else) does. Used by the pages that
 * auto-run an active-portfolio mutation on mount (dashboard, /risk,
 * /scenarios, /score).
 *
 * Pass `null`/`undefined` userId to skip (e.g. anonymous visitors).
 */
export function useRunOncePerUser(
  userId: string | null | undefined,
  fn: () => void,
): void {
  const ranFor = useRef<string | null>(null);
  useEffect(() => {
    const uid = userId ?? null;
    if (uid && ranFor.current !== uid) {
      ranFor.current = uid;
      fn();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);
}

/**
 * Composite run-once key for auto-run pages that analyze the ACTIVE portfolio
 * (the /risk report, /scenarios sweeps): `${userId}:${activePortfolioId}`.
 * Passing this to `useRunOncePerUser` re-fires the auto-run when the user
 * switches the active book — not only on a user change. Returns `undefined`
 * (skip) for anonymous visitors, matching the hook's null contract.
 */
export function runKeyForActivePortfolio(
  userId: string | null | undefined,
  activePortfolioId: string | null | undefined,
): string | undefined {
  return userId ? `${userId}:${activePortfolioId ?? "none"}` : undefined;
}
