"use client";

/**
 * Market-regime panel — VIX, Fear & Greed, and yield-curve status.
 *
 * Ported from the legacy Streamlit `3_Markets` "Market Regime" block.
 * Each leg is independently nullable (the backend nulls only the dead
 * upstream), so every tile renders its own "—" rather than the panel
 * failing as a whole. No auth required.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMarketRegime } from "@/lib/queries";

export function MarketRegime() {
  const regime = useMarketRegime();

  return (
    <section className="space-y-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          Market regime · live
        </p>
        <h2 className="text-2xl font-semibold tracking-tight">Risk climate</h2>
        <p className="text-xs text-muted-foreground">
          Volatility, sentiment &amp; the curve — cached ~5 min server-side.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {regime.isLoading &&
          [0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}

        {regime.isError && (
          <div className="col-span-full rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-muted-foreground">
            Could not load market-regime data.
          </div>
        )}

        {regime.data && (
          <>
            <RegimeTile
              title="VIX"
              caption="CBOE volatility index"
              value={fmtNum(regime.data.vix.current)}
              sub={regime.data.vix.level ?? "—"}
              delta={fmtPct(regime.data.vix.change)}
              // VIX up = risk up = bad → red on a rise (inverse of price).
              deltaTone={toneInverse(regime.data.vix.change)}
            />
            <RegimeTile
              title="Fear & Greed"
              caption="CNN index (0–100)"
              value={
                regime.data.fear_greed.score === null
                  ? "—"
                  : `${Math.round(regime.data.fear_greed.score)}`
              }
              sub={regime.data.fear_greed.rating ?? "—"}
            />
            <RegimeTile
              title="Yield curve"
              caption="3M → 10Y spread"
              value={fmtSignedPct(regime.data.yield_curve.spread_3m_10y)}
              sub={regime.data.yield_curve.status ?? "—"}
              badge={
                regime.data.yield_curve.inverted
                  ? { label: "Inverted", tone: "bad" as const }
                  : undefined
              }
            />
          </>
        )}
      </div>
    </section>
  );
}

type Tone = "good" | "bad" | "neutral";

function RegimeTile({
  title,
  caption,
  value,
  sub,
  delta,
  deltaTone = "neutral",
  badge,
}: {
  title: string;
  caption: string;
  value: string;
  sub: string;
  delta?: string;
  deltaTone?: Tone;
  badge?: { label: string; tone: Tone };
}) {
  return (
    <Card>
      <CardHeader className="space-y-0.5 p-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">{title}</CardTitle>
          {badge && (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium uppercase ${toneClass(
                badge.tone,
              )}`}
            >
              {badge.label}
            </span>
          )}
        </div>
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {caption}
        </p>
      </CardHeader>
      <CardContent className="space-y-1 p-4 pt-0">
        <p className="font-mono text-3xl leading-none">{value}</p>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{sub}</span>
          {delta && (
            <span className={`font-mono text-[11px] ${toneClass(deltaTone)}`}>
              {delta}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function toneClass(tone: Tone): string {
  if (tone === "good") return "text-emerald-500";
  if (tone === "bad") return "text-rose-500";
  return "text-muted-foreground";
}

function toneInverse(v: number | null): Tone {
  if (v === null || v === 0) return "neutral";
  return v > 0 ? "bad" : "good";
}

function fmtNum(v: number | null): string {
  return v === null || Number.isNaN(v) ? "—" : v.toFixed(2);
}

function fmtPct(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function fmtSignedPct(v: number | null): string {
  if (v === null || Number.isNaN(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}
