"use client";

/**
 * A small "show your work" footer — data freshness, source, sample size, and
 * coverage. Surfacing provenance is the cheapest, highest-leverage credibility
 * signal: it tells the user the number was computed from real data, not guessed.
 */

export function DataProvenance({
  asOf,
  source,
  observations,
  coverage,
  className,
}: {
  asOf?: string | null;
  source?: string;
  observations?: number | null;
  coverage?: number | null;
  className?: string;
}) {
  const parts: string[] = [];
  if (asOf) parts.push(`As of ${asOf}`);
  if (source) parts.push(source);
  if (observations != null && observations > 0) parts.push(`${observations} observations`);
  if (coverage != null) parts.push(`${(coverage * 100).toFixed(0)}% coverage`);
  if (parts.length === 0) return null;

  return (
    <p className={`text-[11px] text-muted-foreground ${className ?? ""}`}>
      {parts.join(" · ")}
    </p>
  );
}
