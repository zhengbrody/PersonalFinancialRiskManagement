"use client";

/**
 * Market movers + sector heatmap (public, fail-soft tiles — the MarketRegime
 * pattern). A sector grid colored green/red by today's move, plus top
 * gainers / losers / unusual-volume lists. Free yfinance data; renders empty
 * rather than erroring if an upstream is down.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMarketMovers, type MoverRow, type SectorRow } from "@/lib/queries";
import { cn } from "@/lib/utils";

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v >= 0 ? "+" : "";
  return `${s}${v.toFixed(2)}%`;
}

function changeTone(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  return v >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400";
}

/** Heat background scaled by the move magnitude (capped ±3%). */
function heatBg(v: number | null | undefined): string {
  if (v == null) return "bg-muted/30";
  if (v >= 1.5) return "bg-emerald-500/25";
  if (v >= 0.3) return "bg-emerald-500/10";
  if (v <= -1.5) return "bg-red-500/25";
  if (v <= -0.3) return "bg-red-500/10";
  return "bg-muted/30";
}

export function MarketMovers() {
  const q = useMarketMovers();
  const d = q.data;

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">What&apos;s moving today</h2>
        <p className="text-sm text-muted-foreground">
          Sector performance and the day&apos;s biggest S&amp;P 500 movers.
          {d?.scan_date ? ` As of ${d.scan_date}.` : ""}
        </p>
      </div>

      {/* Sector heatmap */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Sectors</CardTitle>
          <CardDescription>SPDR sector ETFs, today&apos;s move.</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {Array.from({ length: 8 }).map((_, i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : !d || d.sectors.length === 0 ? (
            <p className="text-sm text-muted-foreground">Sector data unavailable right now.</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {d.sectors.map((s: SectorRow) => (
                <div
                  key={s.ticker}
                  className={cn("rounded-md border border-border p-2.5", heatBg(s.change_pct))}
                >
                  <div className="truncate text-xs font-medium" title={s.sector}>
                    {s.sector}
                  </div>
                  <div className={cn("font-mono text-sm", changeTone(s.change_pct))}>
                    {pct(s.change_pct)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Movers lists */}
      <div className="grid gap-4 md:grid-cols-3">
        <MoverList title="Top gainers" rows={d?.top_gainers} loading={q.isLoading} />
        <MoverList title="Top losers" rows={d?.top_losers} loading={q.isLoading} />
        <MoverList title="Unusual volume" rows={d?.unusual_volume} loading={q.isLoading} showVol />
      </div>
    </section>
  );
}

function MoverList({
  title,
  rows,
  loading,
  showVol,
}: {
  title: string;
  rows: MoverRow[] | undefined;
  loading: boolean;
  showVol?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {loading ? (
          <>
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
            <Skeleton className="h-5" />
          </>
        ) : !rows || rows.length === 0 ? (
          <p className="text-xs text-muted-foreground">—</p>
        ) : (
          rows.slice(0, 6).map((m) => (
            <div key={m.ticker} className="flex items-center justify-between gap-2 text-sm">
              <span className="font-mono">{m.ticker}</span>
              <span className={cn("font-mono", changeTone(m.change_pct))}>
                {showVol && m.avg_volume_ratio != null
                  ? `${m.avg_volume_ratio.toFixed(1)}× vol`
                  : pct(m.change_pct)}
              </span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
