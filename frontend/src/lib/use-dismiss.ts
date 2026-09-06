"use client";

import { type RefObject, useEffect, useRef } from "react";

/**
 * Outside-click + Escape dismissal for popovers/dropdowns/sheets. Returns a ref
 * to attach to the container; while `open`, a mousedown outside it or an Escape
 * key calls `close`. The `close` callback is kept in a ref so re-renders don't
 * re-subscribe. Shared by the nav dropdowns, the portfolio switcher, and any
 * lightweight overlay (we have no Radix/Dialog primitive).
 */
export function useDismiss<T extends HTMLElement = HTMLDivElement>(
  open: boolean,
  close: () => void,
  returnFocusRef?: RefObject<HTMLElement>,
) {
  const ref = useRef<T>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        closeRef.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Restore only keyboard dismissal from this disclosure. Outside clicks
      // must retain focus on the user's new target, not jump back to the opener.
      const ownsFocus = ref.current?.contains(document.activeElement);
      closeRef.current();
      if (ownsFocus) returnFocusRef?.current?.focus();
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, returnFocusRef]);
  return ref;
}
