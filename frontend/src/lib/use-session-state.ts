"use client";

/**
 * sessionStorage-backed state, so a value survives in-app navigation (and a
 * same-tab reload — e.g. a mobile browser reloading a backgrounded tab) but
 * resets in a fresh tab / browser session. This is what keeps a searched ticker
 * or a Copilot conversation from vanishing when you switch screens and come back.
 *
 * `readSession` / `writeSession` are the fail-soft JSON primitives (the single
 * place the serialization convention lives). `useSessionState` is the `useState`
 * drop-in; components that own their state elsewhere (e.g. the streaming chat,
 * whose `setMessages` must persist only on completed turns) call the primitives
 * directly from their own effects.
 *
 * Fail-soft: if storage is unavailable (private mode, quota), reads return
 * `undefined` and writes no-op — state degrades to plain in-memory.
 */

import { useCallback, useEffect, useState } from "react";

export function readSession<T>(key: string): T | undefined {
  try {
    const raw = sessionStorage.getItem(key);
    return raw == null ? undefined : (JSON.parse(raw) as T);
  } catch {
    return undefined;
  }
}

export function writeSession<T>(key: string, value: T): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable — value stays in-memory only */
  }
}

export function useSessionState<T>(
  key: string,
  initial: T,
): [T, (value: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(initial);

  // Hydrate once, after mount, to avoid an SSR/CSR mismatch.
  useEffect(() => {
    const stored = readSession<T>(key);
    if (stored !== undefined) setValue(stored);
  }, [key]);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const resolved =
          typeof next === "function" ? (next as (p: T) => T)(prev) : next;
        writeSession(key, resolved);
        return resolved;
      });
    },
    [key],
  );

  return [value, set];
}
