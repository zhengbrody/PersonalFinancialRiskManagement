"use client";

/**
 * Minimal controlled segmented tabs — no extra dependency. Renders an
 * accessible tablist (arrow-key navigation, aria-selected) and the active
 * panel only. Used by the Health Score cockpit + the Risk Report.
 */

import { useId } from "react";
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
  const idx = Math.max(0, items.findIndex((t) => t.value === value));

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = e.key === "ArrowRight" ? (idx + 1) % items.length : (idx - 1 + items.length) % items.length;
    onValueChange(items[next].value);
  }

  return (
    <div
      role="tablist"
      aria-label="View"
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex flex-wrap gap-1 rounded-lg border border-border bg-muted/40 p-1",
        className,
      )}
    >
      {items.map((t) => {
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
