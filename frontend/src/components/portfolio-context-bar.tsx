"use client";

/**
 * The always-visible "current portfolio" strip, directly under MarketStatusBar
 * in the signed-in header. Every analysis surface reads the SAME active book,
 * and this bar is where the user sees and switches it. Switching is one atomic
 * server op (the context's switchPortfolio) that resets the portfolio-scoped
 * caches so no prior-book data lingers.
 *
 * Deliberately lightweight: it reads ONLY the already-loaded portfolios list
 * (name · holdings count · updated date) — it never triggers a score/risk fetch,
 * so putting it on every page adds no heavy fan-out. The full DataConfidence
 * lives on the analysis pages that already load the score.
 */

import Link from "next/link";
import { type KeyboardEvent, useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { useDismiss } from "@/lib/use-dismiss";
import type { PortfolioRow } from "@/lib/queries";

function holdingsCount(p: PortfolioRow): number {
  const h = (p as { holdings?: Record<string, unknown> }).holdings;
  return h && typeof h === "object" ? Object.keys(h).length : 0;
}

const CONF_DOT: Record<string, string> = {
  high: "bg-emerald-500",
  medium: "bg-amber-500",
  low: "bg-destructive",
};

// The active score's confidence + data date, read PASSIVELY from cache
// (enabled:false → the bar never triggers a score fetch). Shows only when an
// analysis page has already loaded the score; cleared when a switch resets that
// cache. We use the SCORE's as_of (when the market data is from) as the "data
// date" — NOT the portfolio row's updated_at, which a rename / capital edit /
// active-switch all bump, so it wouldn't honestly mean "data freshness".
function useCachedScoreMeta(userId: string | null): {
  label: string | null;
  asOf: string | null;
} {
  const q = useQuery<
    | { data_confidence?: { label?: string; as_of?: string | null } | null }
    | undefined
  >({
    queryKey: ["risk", "score_active", userId],
    enabled: false,
    queryFn: () => Promise.resolve(undefined), // never called (enabled:false)
  });
  const dc = q.data?.data_confidence;
  return { label: dc?.label ?? null, asOf: dc?.as_of ?? null };
}

function asOf(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function PortfolioContextBar() {
  const { user } = useAuth();
  const {
    current,
    list,
    isLoading,
    switchingId,
    switchPortfolio,
    pendingSwitchId,
    confirmDiscardAndSwitch,
    cancelSwitch,
  } = usePortfolioContext();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const ref = useDismiss<HTMLDivElement>(
    open,
    () => setOpen(false),
    triggerRef,
  );
  const { label: confLabel, asOf: dataAsOf } = useCachedScoreMeta(
    user?.id ?? null,
  );

  // Proper listbox keyboarding: focus the active option when the menu opens,
  // and move focus with Arrow/Home/End (Escape/outside-click close via useDismiss).
  const onListboxMount = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;
    const opts = el.querySelectorAll<HTMLButtonElement>('[role="option"]');
    (
      opts[
        [...opts].findIndex((o) => o.getAttribute("aria-selected") === "true")
      ] ?? opts[0]
    )?.focus();
  }, []);
  const onListboxKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const opts = Array.from(
      e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="option"]'),
    );
    if (opts.length === 0) return;
    const idx = opts.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      opts[Math.min(idx + 1, opts.length - 1)]?.focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      opts[Math.max(idx - 1, 0)]?.focus();
    } else if (e.key === "Home") {
      e.preventDefault();
      opts[0]?.focus();
    } else if (e.key === "End") {
      e.preventDefault();
      opts[opts.length - 1]?.focus();
    }
  };

  // Signed-out or still loading → nothing (the shell already hides on marketing).
  if (!user || isLoading) return null;

  // No portfolios yet → a subtle create nudge (dashboard owns full onboarding).
  if (list.length === 0) {
    return (
      <div className="border-t border-border/60 bg-muted/30">
        <div className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-1.5 text-xs text-muted-foreground">
          <span>No portfolio yet.</span>
          <Link
            href="/portfolios/new"
            className="font-medium text-primary hover:underline"
          >
            Create one →
          </Link>
        </div>
      </div>
    );
  }

  const count = current ? holdingsCount(current) : 0;
  const dateLabel = asOf(dataAsOf);

  return (
    <div className="border-t border-border/60 bg-muted/30">
      <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-2 text-xs lg:px-8">
        <span className="shrink-0 font-medium uppercase tracking-wide text-muted-foreground">
          Portfolio
        </span>
        <div ref={ref} className="relative">
          <button
            ref={triggerRef}
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-haspopup="listbox"
            aria-expanded={open}
            className="flex min-h-10 max-w-[52vw] items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 font-medium text-foreground hover:bg-accent sm:max-w-[360px]"
          >
            <span className="truncate">
              {current?.name ?? "Select a portfolio"}
            </span>
            {switchingId ? (
              <span className="text-muted-foreground" aria-label="switching">
                …
              </span>
            ) : (
              <span className="text-muted-foreground" aria-hidden>
                ▾
              </span>
            )}
          </button>
          {open && (
            <div className="absolute left-0 z-40 mt-2 max-h-[min(20rem,calc(100dvh-14rem-env(safe-area-inset-bottom)))] w-64 max-w-[calc(100vw-7rem)] overflow-auto rounded-xl border border-border bg-card p-2 shadow-xl">
              <div
                role="listbox"
                aria-label="Switch portfolio"
                ref={onListboxMount}
                onKeyDown={onListboxKeyDown}
              >
                {list.map((p) => {
                  const active = p.id === current?.id;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      disabled={Boolean(switchingId)}
                      onClick={() => {
                        setOpen(false);
                        triggerRef.current?.focus();
                        if (!active) void switchPortfolio(p.id);
                      }}
                      className={`flex min-h-12 w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left hover:bg-accent disabled:opacity-60 ${
                        active ? "bg-accent/60" : ""
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-foreground">
                          {p.name}
                        </span>
                        <span className="block text-[11px] text-muted-foreground">
                          {holdingsCount(p)} holding
                          {holdingsCount(p) === 1 ? "" : "s"}
                        </span>
                      </span>
                      {active && (
                        <span className="shrink-0 text-[11px] font-medium text-primary">
                          Active
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <Link
                href="/portfolios"
                onClick={() => setOpen(false)}
                className="mt-1 block border-t border-border px-2 py-1.5 text-[11px] font-medium text-muted-foreground hover:text-foreground"
              >
                Manage portfolios →
              </Link>
            </div>
          )}
        </div>
        {/* Holdings count + the analyzed data date (score as_of), hidden on the
            smallest screens to keep the bar single-line. */}
        <span className="hidden shrink-0 text-muted-foreground sm:inline">
          {count} holding{count === 1 ? "" : "s"}
          {dateLabel ? ` · data ${dateLabel}` : ""}
        </span>
        {/* Data-confidence brief (only when a page already loaded the score). */}
        {confLabel && (
          <span
            className="ml-auto hidden shrink-0 items-center gap-1 text-muted-foreground sm:flex"
            title={`Data confidence: ${confLabel}`}
          >
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${CONF_DOT[confLabel] ?? "bg-muted-foreground/40"}`}
            />
            <span className="capitalize">{confLabel} confidence</span>
          </span>
        )}
      </div>

      {/* Unsaved-analysis guard (a surface registered a dirty predicate). PR1
          offers Discard/Stay; Save-as-plan arrives with the plans surface. */}
      {pendingSwitchId && (
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 pb-1.5 text-xs">
          <span className="text-amber-600 dark:text-amber-400">
            You have unsaved analysis on this portfolio.
          </span>
          <button
            type="button"
            onClick={() => void confirmDiscardAndSwitch()}
            className="rounded border border-border px-2 py-0.5 font-medium hover:bg-accent"
          >
            Discard &amp; switch
          </button>
          <button
            type="button"
            onClick={cancelSwitch}
            className="rounded px-2 py-0.5 font-medium text-muted-foreground hover:text-foreground"
          >
            Stay
          </button>
        </div>
      )}
    </div>
  );
}
