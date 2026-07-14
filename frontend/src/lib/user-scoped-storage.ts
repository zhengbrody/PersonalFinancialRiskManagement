"use client";

/**
 * Per-user browser storage that must NOT bleed across accounts on a shared
 * machine. Copilot insight dismissals, the last saved answer, chat transcripts
 * and the researched ticker all live under these prefixes. On sign-out — and on
 * any change of the signed-in identity — we wipe them, the same data-isolation
 * boundary `queryClient.clear()` already enforces for the React Query cache
 * (without it, user A's dismissals could hide user B's insights, and A's last
 * Copilot answer could render to B on a shared browser).
 *
 * Everything is fail-soft: storage being unavailable (private mode, quota,
 * SSR) never throws.
 */

// Keys under these prefixes are per-user CONTENT (never analytics/behavioural
// flags like mm_first_utm / mm_last_seen, which are intentionally left alone).
const USER_SCOPED_PREFIXES = ["mm:copilot:", "mm:research:"];

// Where we remember which account the per-user storage currently belongs to.
const LAST_USER_KEY = "mm:auth:last-user";

function purge(store: Storage): void {
  const doomed: string[] = [];
  for (let i = 0; i < store.length; i += 1) {
    const key = store.key(i);
    if (key && USER_SCOPED_PREFIXES.some((p) => key.startsWith(p))) doomed.push(key);
  }
  doomed.forEach((k) => store.removeItem(k));
}

/** Remove every per-user CONTENT key from both local + session storage. */
export function clearUserScopedStorage(): void {
  if (typeof window === "undefined") return;
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      purge(store);
    } catch {
      /* storage unavailable — nothing to clear */
    }
  }
}

/**
 * Wipe per-user storage when the signed-in identity CHANGES to a different
 * account (a real prior user → a different user, or → signed-out). The SAME
 * identity — a reload, a token refresh — keeps the state so the user's own
 * saved answer / dismissals survive. First-ever use (no prior identity) never
 * wipes. Returns true when a wipe happened (for tests).
 */
export function syncUserScopedStorage(userId: string | null): boolean {
  if (typeof window === "undefined") return false;
  const current = userId ?? "";
  let prev: string | null = null;
  try {
    prev = window.localStorage.getItem(LAST_USER_KEY);
  } catch {
    /* ignore */
  }
  const changed = prev !== null && prev !== current;
  if (changed) clearUserScopedStorage();
  try {
    if (current) window.localStorage.setItem(LAST_USER_KEY, current);
    else window.localStorage.removeItem(LAST_USER_KEY);
  } catch {
    /* ignore */
  }
  return changed;
}
