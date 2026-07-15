"use client";

/**
 * A minimal right-side Sheet / drawer — no dependency (we have no Radix). It is
 * accessible: role=dialog + aria-modal, a focus TRAP (Tab cycles inside), Escape
 * to close, and focus RESTORE to the element that opened it. Respects
 * prefers-reduced-motion (skips the slide). Backdrop click closes.
 *
 * Rendered inline (no portal) — the app has a single scroll container and the
 * fixed overlay covers the viewport regardless of DOM position.
 */

import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  // Read onClose via a ref so the effect can key on [open] ONLY — otherwise an
  // inline `onClose={() => …}` (a new identity each parent render) would re-run
  // the effect while the sheet is open, stealing focus and flickering scroll-lock.
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const titleId = `sheet-${title.replace(/\s+/g, "-").toLowerCase()}`;

  useEffect(() => {
    if (!open) return;
    restoreRef.current = (document.activeElement as HTMLElement) ?? null;
    const panel = panelRef.current;
    // Move focus into the panel (first focusable, else the panel itself).
    const first = panel?.querySelector<HTMLElement>(FOCUSABLE);
    (first ?? panel)?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const items = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null,
      );
      if (items.length === 0) {
        e.preventDefault();
        panel.focus();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      const active = document.activeElement as HTMLElement;
      if (e.shiftKey && (active === firstEl || !panel.contains(active))) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && active === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    // Lock body scroll while the sheet is open.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      restoreRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[60] flex justify-end">
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-black/40 motion-safe:transition-opacity"
      />
      {/* Panel */}
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-border bg-background shadow-xl outline-none motion-safe:animate-in motion-safe:slide-in-from-right"
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-border bg-background px-4 py-3">
          <h2 id={titleId} className="text-base font-semibold">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 p-4">{children}</div>
      </div>
    </div>
  );
}
