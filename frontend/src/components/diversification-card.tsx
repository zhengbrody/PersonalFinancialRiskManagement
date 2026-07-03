"use client";

/**
 * Diversification analysis — the "do my holdings secretly move together?"
 * desk view. Everything shown is deterministic backend output (the engine's
 * correlation matrix + insights computed server-side); the takeaway line is
 * a fixed threshold table, not prose from a model.
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Kpi } from "@/components/ui/kpi";
import { TickerBadge } from "@/components/ui/ticker-badge";
import { CorrHeatmap } from "@/components/ui/corr-heatmap";
import { LearnHint } from "@/components/learn-hint";
import type { Correlation } from "@/lib/queries";

// Deterministic takeaway bands over the average pairwise correlation.
const AVG_RHO_ONE_BLOCK = 0.7;
const AVG_RHO_MODERATE = 0.4;

function takeaway(avg: number | null | undefined, dr: number | null | undefined): string {
  const saved = dr != null && dr > 0 ? Math.max(0, 1 - 1 / dr) : null;
  const savedTxt =
    saved != null ? ` Diversification is cutting ~${Math.round(saved * 100)}% of the risk your holdings would carry standalone.` : "";
  if (avg == null) return savedTxt.trim() || "Not enough overlapping history to judge co-movement.";
  if (avg >= AVG_RHO_ONE_BLOCK)
    return `Your holdings move largely as one block (avg ρ ${avg.toFixed(2)}) — ticker count is not buying much diversification.${savedTxt}`;
  if (avg >= AVG_RHO_MODERATE)
    return `Moderate co-movement (avg ρ ${avg.toFixed(2)}) — diversified, with room to add uncorrelated sleeves.${savedTxt}`;
  return `Meaningful diversification (avg ρ ${avg.toFixed(2)}) — your holdings don't all swing together.${savedTxt}`;
}

export function DiversificationCard({ correlation }: { correlation: Correlation }) {
  const c = correlation;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Diversification &amp; correlation</CardTitle>
        <CardDescription>
          Pairwise correlation of your holdings&apos; daily returns — where the book secretly
          moves as one trade.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi
            label="Avg pairwise ρ"
            value={c.avg_pairwise != null ? c.avg_pairwise.toFixed(2) : "—"}
            tone={
              c.avg_pairwise == null
                ? "neutral"
                : c.avg_pairwise >= AVG_RHO_ONE_BLOCK
                  ? "bad"
                  : c.avg_pairwise >= AVG_RHO_MODERATE
                    ? "warn"
                    : "ok"
            }
          />
          <Kpi
            label="Diversification ratio"
            value={c.diversification_ratio != null ? `${c.diversification_ratio.toFixed(2)}×` : "—"}
            tone={c.diversification_ratio != null && c.diversification_ratio >= 1.3 ? "ok" : "neutral"}
          />
          <div className="rounded-xl border border-border bg-background/40 p-3">
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Most correlated pair
            </p>
            {c.top_pair ? (
              <p className="mt-1 flex flex-wrap items-center gap-1 font-mono text-sm tabular-nums">
                <TickerBadge ticker={c.top_pair.a} />
                <span className="text-muted-foreground">×</span>
                <TickerBadge ticker={c.top_pair.b} />
                <span>ρ {c.top_pair.rho.toFixed(2)}</span>
              </p>
            ) : (
              <p className="mt-1 font-mono text-sm">—</p>
            )}
          </div>
          <div className="rounded-xl border border-border bg-background/40 p-3">
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">
              Best diversifier
            </p>
            {c.best_diversifier ? (
              <p className="mt-1 flex flex-wrap items-center gap-1 font-mono text-sm tabular-nums">
                <TickerBadge ticker={c.best_diversifier.ticker} />
                <span>avg ρ {c.best_diversifier.avg_rho.toFixed(2)}</span>
              </p>
            ) : (
              <p className="mt-1 font-mono text-sm">—</p>
            )}
          </div>
        </div>

        <p className="text-sm text-muted-foreground">{takeaway(c.avg_pairwise, c.diversification_ratio)}</p>

        <CorrHeatmap tickers={c.tickers} matrix={c.matrix} totalTickers={c.total_tickers} />

        <p className="text-[11px] text-muted-foreground">
          Correlations are estimated on the risk engine&apos;s ~2-year daily-return window; the
          diversification ratio on the report&apos;s price window (~1 year) — two honest estimates,
          not one.
        </p>

        <LearnHint topic="diversification-correlation" />
      </CardContent>
    </Card>
  );
}
