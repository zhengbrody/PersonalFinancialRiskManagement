"use client";

/**
 * Minimal controlled segmented tabs — no extra dependency. Renders an
 * accessible tablist (arrow-key navigation, aria-selected) and the active
 * panel only. Used by the Health Score cockpit + the Risk Report.
 */

import { useId, useRef } from "react";
import { cn } from "@/lib/utils";

export type TabItem = { value: string; label: string };

// Shared id helpers so a caller can wire aria-labelledby/aria-controls between
// the Tabs and its own panels (the panels live outside this component).
export const tabId = (base: string, value: string) => `${base}-tab-${value}`;
export const tabPanelId = (base: string, value: string) => `${base}-panel-${value}`;

export function Tabs({
  items,
  value,
  onValueChange,
  className,
  idBase,
}: {
  items: TabItem[];
  value: string;
  onValueChange: (v: string) => void;
  className?: string;
  /** When set, tabs get stable ids + aria-controls so external panels can link
   *  back with aria-labelledby (see tabId/tabPanelId). Falls back to a local
   *  useId when omitted (existing callers unaffected). */
  idBase?: string;
}) {
  const localId = useId();
  const base = idBase ?? localId;
  const tablistRef = useRef<HTMLDivElement>(null);

  function onKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, currentIndex: number) {
    let next = currentIndex;
    if (e.key === "ArrowRight") next = (currentIndex + 1) % items.length;
    else if (e.key === "ArrowLeft") next = (currentIndex - 1 + items.length) % items.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else return;
    e.preventDefault();
    onValueChange(items[next].value);
    const tabs = tablistRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    tabs?.[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label="View"
      aria-orientation="horizontal"
      ref={tablistRef}
      className={cn(
        "inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/40 p-1",
        className,
      )}
    >
      {items.map((t, itemIndex) => {
        const active = t.value === value;
        return (
          <button
            key={t.value}
            type="button"
            role="tab"
            id={tabId(base, t.value)}
            aria-selected={active}
            aria-controls={idBase ? tabPanelId(base, t.value) : undefined}
            tabIndex={active ? 0 : -1}
            onClick={() => onValueChange(t.value)}
            onKeyDown={(event) => onKeyDown(event, itemIndex)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
