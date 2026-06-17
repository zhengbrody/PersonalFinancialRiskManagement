/**
 * Kpi — the metric tile that tiles the cockpit (MindMarket design system,
 * components/data/Kpi). A small uppercase label over a big mono tabular value
 * on a faint surface inside a hairline border. `tone` colors the value with the
 * risk palette; optional `delta` adds a colored change line (sign → success/
 * destructive, flip with `deltaInvert` when "down is good").
 *
 * One canonical tile for every KPI grid (risk report, sample cockpit, markets,
 * score) so figures read the same everywhere.
 */

import { type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type KpiTone = "neutral" | "ok" | "warn" | "bad";

const VALUE_TONE: Record<KpiTone, string> = {
  neutral: "text-foreground",
  ok: "text-success",
  warn: "text-warning",
  bad: "text-destructive",
};

export function Kpi({
  label,
  value,
  tone = "neutral",
  delta,
  deltaInvert = false,
  className,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: KpiTone;
  delta?: number | string;
  deltaInvert?: boolean;
  className?: string;
}) {
  let deltaCls = "text-muted-foreground";
  if (typeof delta === "number") {
    const good = deltaInvert ? delta < 0 : delta > 0;
    deltaCls = good ? "text-success" : "text-destructive";
  }
  return (
    <div className={cn("rounded-xl border border-border bg-background/40 p-3", className)}>
      <p className="text-[10px] uppercase tracking-widest text-muted-foreground">{label}</p>
      <p className={cn("mt-0.5 font-mono text-xl font-semibold tabular-nums", VALUE_TONE[tone])}>
        {value}
      </p>
      {delta != null && (
        <p className={cn("mt-0.5 font-mono text-xs tabular-nums", deltaCls)}>
          {typeof delta === "number" ? `${delta >= 0 ? "+" : ""}${delta}` : delta}
        </p>
      )}
    </div>
  );
}
