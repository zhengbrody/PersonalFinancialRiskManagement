"use client";

/**
 * A small "show your work" footer — data freshness, source, sample size, and
 * coverage. Surfacing provenance is the cheapest, highest-leverage credibility
 * signal: it tells the user the number was computed from real data, not guessed.
 */

import Link from "next/link";
import type { PriceProvenance } from "@/lib/schemas";

function displaySource(source?: string | null): string {
  if (!source) return "Unknown";
  if (source === "massive") return "Massive";
  if (source === "yfinance") return "Yahoo Finance";
  return source;
}

function sourceRank(source?: string): number {
  if (source === "massive") return 0;
  if (source === "yfinance") return 1;
  return 2;
}

export function DataProvenance({
  asOf,
  source,
  observations,
  coverage,
  priceProvenance,
  scoreVersion,
  className,
}: {
  asOf?: string | null;
  source?: string;
  observations?: number | null;
  coverage?: number | null;
  priceProvenance?: PriceProvenance | null;
  // The methodology version that produced the number — links to the auditable
  // /methodology/health-score page.
  scoreVersion?: string | null;
  className?: string;
}) {
  const parts: string[] = [];
  if (asOf) parts.push(`As of ${asOf}`);
  if (source) parts.push(source);
  if (observations != null && observations > 0) parts.push(`${observations} observations`);
  if (coverage != null) parts.push(`${(coverage * 100).toFixed(0)}% coverage`);

  const pp = priceProvenance;
  const sourceCounts = new Map<string, number>();
  for (const source of Object.values(pp?.by_ticker ?? {})) {
    sourceCounts.set(source, (sourceCounts.get(source) ?? 0) + 1);
  }
  const yfinanceFallback = pp?.yfinance_fallback_used ?? [];
  const legacyMassiveFallback = pp?.massive_fallback_used ?? [];
  const missing = pp?.missing ?? [];
  const priceSourceParts: { text: string; title?: string }[] = [];
  if (pp) {
    if (sourceCounts.size > 0) {
      const items = Array.from(sourceCounts.entries())
        .sort(([a], [b]) => sourceRank(a) - sourceRank(b) || a.localeCompare(b))
        .map(([sourceName, count]) => {
          if (sourceName === "yfinance") return `Yahoo fallback (${count})`;
          if (sourceName === "massive") return `Massive (${count})`;
          return `${sourceName} (${count})`;
        });
      priceSourceParts.push({
        text: `Price sources: ${items.join(" · ")}`,
        title: Object.entries(pp.by_ticker ?? {})
          .map(([ticker, sourceName]) => `${ticker}: ${displaySource(sourceName)}`)
          .join(", "),
      });
    } else if (yfinanceFallback.length > 0) {
      priceSourceParts.push({
        text: `Price source: ${displaySource(pp.primary ?? "massive")} + Yahoo fallback (${yfinanceFallback.length})`,
        title: yfinanceFallback.join(", "),
      });
    } else if (legacyMassiveFallback.length > 0) {
      priceSourceParts.push({
        text: `Price source: Massive (${legacyMassiveFallback.length})`,
        title: legacyMassiveFallback.join(", "),
      });
    } else {
      priceSourceParts.push({ text: `Price source: ${displaySource(pp.primary ?? "massive")}` });
    }
    if (pp.trading_days != null) {
      priceSourceParts.push({ text: `Historical coverage: ${pp.trading_days} trading days` });
    }
  }

  if (
    parts.length === 0 &&
    priceSourceParts.length === 0 &&
    missing.length === 0 &&
    !scoreVersion
  ) {
    return null;
  }

  return (
    <div className={`text-[11px] text-muted-foreground space-y-0.5 ${className ?? ""}`}>
      {parts.length > 0 && <p>{parts.join(" · ")}</p>}
      {scoreVersion && (
        <p>
          Methodology {scoreVersion} ·{" "}
          <Link href="/methodology/health-score" className="underline hover:text-foreground">
            how the score is calculated
          </Link>
        </p>
      )}
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
