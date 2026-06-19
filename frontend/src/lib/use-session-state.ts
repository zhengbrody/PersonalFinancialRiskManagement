"use client";

/**
 * `useState` backed by `sessionStorage`, so a value survives in-app navigation
 * (and a same-tab reload — e.g. a mobile browser reloading a backgrounded tab)
 * but resets in a fresh tab / browser session. This is what keeps a searched
 * ticker or a Copilot conversation from vanishing when you switch screens and
 * come back.
 *
 * SSR-safe: the initial render uses `initial` (so server + first client render
 * match), then it hydrates from storage in an effect. Fail-soft — if storage is
 * unavailable (private mode, quota), it degrades to plain in-memory state.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export function useSessionState<T>(
  key: string,
  initial: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(initial);
  const hydrated = useRef(false);

  // Hydrate once, after mount, to avoid an SSR/CSR mismatch.
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(key);
      if (raw != null) setValue(JSON.parse(raw) as T);
    } catch {
      /* storage unavailable — keep the in-memory value */
    }
    hydrated.current = true;
  }, [key]);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved =
          typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        try {
          sessionStorage.setItem(key, JSON.stringify(resolved));
        } catch {
          /* ignore persistence failure */
        }
        return resolved;
      });
    },
    [key],
  );

  return [value, set];
}
