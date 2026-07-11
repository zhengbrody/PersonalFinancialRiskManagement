"use client";

/**
 * Reusable source-provenance UI — makes the multi-source data layer visible so
 * the product never looks like everything comes from one provider.
 *
 * - `DataSourceBadges`: a compact row of provider chips (FMP · Massive · FRED …)
 *   with a subtle Yahoo-fallback warning when a fallback was used.
 * - `DataSourcesPanel`: an expandable "Data Sources Used" list (per-field
 *   provider · role · freshness) for Research + Risk.
 *
 * Provider-agnostic: it renders whatever `SourceProvenance[]` the backend sends
 * (label/role come from the server registry) — no provider-specific logic here.
 */

import type { SourceProvenance } from "@/lib/schemas";

function roleTone(role?: string | null): string {
  if (role === "primary") return "border-primary/40 bg-primary/10 text-primary";
  if (role === "fallback") return "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400";
  return "border-border bg-muted/50 text-muted-foreground";
}

/** De-dupe sources to one chip per provider (keep the first / highest-role). */
function uniqueProviders(sources: SourceProvenance[]): SourceProvenance[] {
  const seen = new Map<string, SourceProvenance>();
  for (const s of sources) {
    if (!seen.has(s.provider)) seen.set(s.provider, s);
  }
  return Array.from(seen.values());
}

export function DataSourceBadges({
  sources,
  className,
}: {
  sources: SourceProvenance[] | undefined;
  className?: string;
}) {
  if (!sources || sources.length === 0) return null;
  const providers = uniqueProviders(sources);
  const fallback = sources.some((s) => s.fallback_used || s.role === "fallback");

  return (
    <div className={`flex flex-wrap items-center gap-1.5 ${className ?? ""}`}>
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Sources</span>
      {providers.map((s) => (
        <span
          key={s.provider}
          title={s.role ?? undefined}
          className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${roleTone(s.role)}`}
        >
          {s.label ?? s.provider}
        </span>
      ))}
      {fallback && (
        <span className="text-[10px] text-amber-600 dark:text-amber-400">
          · Using Yahoo fallback because Massive/FMP was unavailable
        </span>
      )}
    </div>
  );
}

export function DataSourcesPanel({
  sources,
  warnings,
  className,
}: {
  sources: SourceProvenance[] | undefined;
  warnings?: string[];
  className?: string;
}) {
  if (!sources || sources.length === 0) return null;
  return (
    <details className={`rounded-md border border-border bg-muted/20 px-3 py-2 ${className ?? ""}`}>
      <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
        Data sources used ({uniqueProviders(sources).length})
      </summary>
      <div className="mt-2 space-y-1">
        {sources.map((s, i) => (
          <div key={i} className="flex flex-wrap items-baseline gap-x-2 text-[11px]">
            <span className="font-mono text-muted-foreground">{s.field}</span>
            <span
              className={`rounded border px-1 py-0.5 text-[10px] font-medium ${roleTone(s.role)}`}
            >
              {s.label ?? s.provider}
            </span>
            {s.role && <span className="text-muted-foreground">{s.role}</span>}
            {s.as_of && <span className="text-muted-foreground">· as of {s.as_of}</span>}
            {s.freshness && <span className="text-muted-foreground">· {s.freshness}</span>}
            {typeof s.confidence === "number" && (
              <span className="text-muted-foreground">
                · {(s.confidence * 100).toFixed(0)}% coverage
              </span>
            )}
          </div>
        ))}
        {warnings && warnings.length > 0 && (
          <p className="pt-1 text-[10px] text-amber-600 dark:text-amber-400">
            {warnings.join(" · ")}
          </p>
        )}
      </div>
    </details>
  );
}
