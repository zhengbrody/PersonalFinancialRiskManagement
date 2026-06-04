"use client";

/**
 * AI risk diagnosis renderer — shared by the Health Score cockpit + the Risk
 * Report executive summary. Presentational: it takes the `useRiskExplain` query
 * state and renders a skeleton → the diagnosis. severity + every number come
 * from the backend (deterministic); this component never computes risk.
 */

import { useEffect, useRef } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { track } from "@/lib/analytics";
import type { RiskExplain, Severity } from "@/lib/queries";
import { cn } from "@/lib/utils";

const SEVERITY_STYLE: Record<Severity, { label: string; cls: string }> = {
  low: { label: "Low risk", cls: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30" },
  moderate: { label: "Moderate risk", cls: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30" },
  elevated: { label: "Elevated risk", cls: "bg-orange-500/15 text-orange-600 dark:text-orange-400 border-orange-500/30" },
  high: { label: "High risk", cls: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY_STYLE[severity];
  return (
    <span className={cn("rounded-full border px-2.5 py-0.5 text-xs font-semibold", s.cls)}>
      {s.label}
    </span>
  );
}

export function RiskDiagnosis({
  explain,
  loading,
  source,
  title = "AI Portfolio Diagnosis",
}: {
  explain: RiskExplain | undefined;
  loading: boolean;
  source: "score" | "risk";
  title?: string;
}) {
  // Fire a privacy-safe funnel event once per severity (no tickers / $).
  const tracked = useRef<string | null>(null);
  useEffect(() => {
    if (explain && tracked.current !== explain.severity) {
      tracked.current = explain.severity;
      track("risk_diagnosis_viewed", { severity: explain.severity, source });
    }
  }, [explain, source]);

  if (loading && !explain) return <DiagnosisSkeleton />;
  if (!explain) return null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          <div className="flex items-center gap-2">
            <SeverityBadge severity={explain.severity} />
            <span
              className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
              title={
                explain.ai_generated
                  ? "Narrated by AI from your computed metrics"
                  : "Auto-generated from your computed metrics"
              }
            >
              {explain.ai_generated ? "AI summary" : "Auto summary"}
            </span>
          </div>
        </div>
        <CardDescription className="pt-1 text-sm text-foreground">
          {explain.headline}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ul className="space-y-1.5 text-sm">
          {explain.summary_bullets.map((b, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/70" />
              <span>{b}</span>
            </li>
          ))}
        </ul>

        <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            Inspect first
          </span>
          <p className="mt-0.5 font-medium">{explain.primary_driver}</p>
        </div>

        {explain.watch_items.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {explain.watch_items.map((w, i) => (
              <span
                key={i}
                className="rounded-full border border-border bg-background px-2 py-0.5 text-xs text-muted-foreground"
              >
                {w}
              </span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/** The "Actions" view: educational action cards (reason / evidence / next step
 * / disclaimer). Falls back to a calm message when there's nothing pressing. */
export function ActionCards({
  explain,
  loading,
}: {
  explain: RiskExplain | undefined;
  loading: boolean;
}) {
  if (loading && !explain) return <DiagnosisSkeleton />;
  if (!explain) return null;

  if (explain.suggested_actions.length === 0) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">
          No pressing actions surfaced from the current metrics. Keep an eye on
          the watch items above.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {explain.suggested_actions.map((a, i) => (
        <Card key={i}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">{a.reason}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {a.evidence && (
              <p>
                <span className="text-xs uppercase tracking-wide text-muted-foreground">
                  Why
                </span>
                <br />
                {a.evidence}
              </p>
            )}
            {a.next_step && (
              <p>
                <span className="text-xs uppercase tracking-wide text-muted-foreground">
                  Possible next step
                </span>
                <br />
                {a.next_step}
              </p>
            )}
            <p className="text-xs italic text-muted-foreground">{a.disclaimer}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function DiagnosisSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <Skeleton className="h-4 w-40" />
          <Skeleton className="h-5 w-24" />
        </div>
        <Skeleton className="mt-2 h-4 w-3/4" />
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-5/6" />
        <Skeleton className="h-3 w-2/3" />
        <Skeleton className="mt-3 h-10 w-full" />
      </CardContent>
    </Card>
  );
}
