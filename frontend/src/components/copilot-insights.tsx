"use client";

/**
 * Proactive insight cards — "what changed for you", server-computed and
 * deterministic (material changes only, never advice). Each card: what
 * changed, why it matters, expandable evidence, and one non-transactional
 * next-analysis link. Dismissals are kept in localStorage by the insight's
 * STABLE episode id, so a persisting condition stays dismissed instead of
 * re-appearing as new on every visit. Renders nothing while loading/empty/
 * unavailable — the page never blocks on insights.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { track } from "@/lib/analytics";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { type CopilotInsight, useCopilotInsights } from "@/lib/queries";

// Dismissals are PER-PORTFOLIO: the same insight kind on two books is a
// different episode, so switching the active portfolio starts fresh (and never
// hides another book's alert). The `mm:copilot:` prefix keeps it inside the
// user-scoped-storage wipe on sign-out.
const DISMISSED_KEY_BASE = "mm:copilot:insights:dismissed";
const dismissedKey = (portfolioId: string | null) =>
  `${DISMISSED_KEY_BASE}:${portfolioId ?? "none"}`;
const MAX_REMEMBERED = 50;

const SEVERITY_DOT: Record<string, string> = {
  high: "bg-destructive",
  watch: "bg-amber-500",
  info: "bg-sky-500",
};

function readDismissed(key: string): string[] {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function writeDismissed(key: string, ids: string[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(ids.slice(-MAX_REMEMBERED)));
  } catch {
    /* storage unavailable — dismissal just won't persist */
  }
}

export function CopilotInsightsStrip() {
  const insights = useCopilotInsights();
  const { activePortfolioId } = usePortfolioContext();
  const key = dismissedKey(activePortfolioId);
  const [dismissed, setDismissed] = useState<string[]>([]);
  // Re-read when the active portfolio changes — a switch must not carry the
  // prior book's dismissals into the new one.
  useEffect(() => {
    setDismissed(readDismissed(key));
  }, [key]);

  if (insights.isLoading || insights.isError) return null;
  const data = insights.data;
  if (!data || !data.portfolio_available) return null;
  const visible = data.insights.filter((i) => !dismissed.includes(i.id));
  if (visible.length === 0) return null;

  function dismiss(id: string, kind: string) {
    const next = [...dismissed, id];
    setDismissed(next);
    writeDismissed(key, next);
    track("copilot_insight_dismissed", { kind }); // kind only — never content
  }

  return (
    <section aria-label="What changed for you" className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        What changed for you
      </h3>
      <div className="space-y-2">
        {visible.map((i) => (
          <InsightCard key={i.id} insight={i} onDismiss={() => dismiss(i.id, i.kind)} />
        ))}
      </div>
    </section>
  );
}

function InsightCard({
  insight,
  onDismiss,
}: {
  insight: CopilotInsight;
  onDismiss: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-card/50 p-3">
      <div className="flex items-start gap-2">
        <span
          aria-hidden
          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${SEVERITY_DOT[insight.severity] ?? SEVERITY_DOT.info}`}
        />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="text-sm font-medium leading-snug">{insight.what_changed}</p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            {insight.why_it_matters}
          </p>

          {insight.evidence.length > 0 && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Evidence ({insight.evidence.length})
              </summary>
              <ul className="mt-1 space-y-0.5 text-muted-foreground">
                {insight.evidence.map((e, idx) => (
                  <li key={`${e.id ?? e.label}-${idx}`}>
                    <span className="font-mono text-[10px]">{e.id}</span> {e.label}:{" "}
                    <span className="font-medium text-foreground">{e.value}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {insight.missing_data.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              Missing: {insight.missing_data.join("; ")}
            </p>
          )}

          {insight.suggested_next_analysis && (
            <Link href={insight.suggested_next_analysis.href} className="inline-block">
              <Button size="sm" variant="outline" className="h-7 text-xs">
                {insight.suggested_next_analysis.label} →
              </Button>
            </Link>
          )}
        </div>
        <button
          type="button"
          onClick={onDismiss}
          aria-label={`Dismiss insight: ${insight.what_changed}`}
          className="rounded p-1 text-muted-foreground transition hover:bg-muted hover:text-foreground"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
