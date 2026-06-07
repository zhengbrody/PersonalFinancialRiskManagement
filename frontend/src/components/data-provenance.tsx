"use client";

/**
 * A small "show your work" footer — data freshness, source, sample size, and
 * coverage. Surfacing provenance is the cheapest, highest-leverage credibility
 * signal: it tells the user the number was computed from real data, not guessed.
 */

import type { PriceProvenance } from "@/lib/schemas";

export function DataProvenance({
  asOf,
  source,
  observations,
  coverage,
  priceProvenance,
  className,
}: {
  asOf?: string | null;
  source?: string;
  observations?: number | null;
  coverage?: number | null;
  priceProvenance?: PriceProvenance | null;
  className?: string;
}) {
  const parts: string[] = [];
  if (asOf) parts.push(`As of ${asOf}`);
  if (source) parts.push(source);
  if (observations != null && observations > 0) parts.push(`${observations} observations`);
  if (coverage != null) parts.push(`${(coverage * 100).toFixed(0)}% coverage`);

  const pp = priceProvenance;
  const fallbackUsed = pp?.massive_fallback_used ?? [];
  const missing = pp?.missing ?? [];
  const priceSourceParts: { text: string; title?: string }[] = [];
  if (pp) {
    const primary = pp.primary ?? "yfinance";
    if (fallbackUsed.length > 0) {
      const fallbackName = pp.fallback ?? "Massive";
      priceSourceParts.push({
        text: `Price source: ${primary} + ${fallbackName} fallback (${fallbackUsed.length})`,
        title: fallbackUsed.join(", "),
      });
    } else {
      priceSourceParts.push({ text: `Price source: ${primary}` });
    }
    if (pp.trading_days != null) {
      priceSourceParts.push({ text: `Historical coverage: ${pp.trading_days} trading days` });
    }
  }

  if (parts.length === 0 && priceSourceParts.length === 0 && missing.length === 0) {
    return null;
  }

  return (
    <div className={`text-[11px] text-muted-foreground space-y-0.5 ${className ?? ""}`}>
      {parts.length > 0 && <p>{parts.join(" · ")}</p>}
      {priceSourceParts.length > 0 && (
        <p>
          {priceSourceParts.map((p, i) => (
            <span key={i} title={p.title}>
              {i > 0 && " · "}
              {p.text}
            </span>
          ))}
        </p>
      )}
      {missing.length > 0 && (
        <p className="text-amber-600 dark:text-amber-500" title={missing.join(", ")}>
          Missing: {missing.join(", ")}
        </p>
      )}
    </div>
  );
}
