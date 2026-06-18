"use client";

/**
 * Concentration preview for the Health Score Overview — top name / top-5 /
 * effective holdings / top sector, with an amber flag when one name >25% or one
 * sector >50% of the book. Pure display of the score response's `concentration`
 * block (cheap weights + sector roll-up, no extra fetch). The full sector +
 * liquidity tables stay on /risk (cross-linked).
 */

import Link from "next/link";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Kpi } from "@/components/ui/kpi";
import { AllocationDonut } from "@/components/ui/allocation-donut";
import type { Concentration } from "@/lib/schemas";

const pct = (v: number | null | undefined) =>
  typeof v === "number" && Number.isFinite(v) ? `${(v * 100).toFixed(0)}%` : "—";

export function ScoreConcentration({
  concentration,
}: {
  concentration: Concentration | null | undefined;
}) {
  const c = concentration;
  if (!c || !c.num_holdings) return null;

  const topName = c.top_holding_weight ?? 0;
  const topSector = c.top_sector_weight ?? 0;
  const singleFlag = topName > 0.25;
  const sectorFlag = topSector > 0.5;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Concentration</CardTitle>
        <CardDescription>How much of your book rides on one name or one sector.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {c.sectors && c.sectors.length > 0 && (
          <AllocationDonut
            slices={c.sectors.map((s) => ({ label: s.sector, weight: s.weight }))}
            centerTop={String(c.num_holdings)}
            centerSub="holdings"
          />
        )}
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <Kpi
            label={c.top_holding_ticker ? `Top · ${c.top_holding_ticker}` : "Top holding"}
            value={pct(topName)}
            tone={singleFlag ? "warn" : "neutral"}
          />
          <Kpi label="Top 5" value={pct(c.top5_weight)} />
          <Kpi
            label="Effective holdings"
            value={c.effective_holdings != null ? c.effective_holdings.toFixed(1) : "—"}
          />
          <Kpi
            label={c.top_sector ? `Sector · ${c.top_sector}` : "Top sector"}
            value={pct(topSector)}
            tone={sectorFlag ? "warn" : "neutral"}
          />
        </div>

        {(singleFlag || sectorFlag) && (
          <p className="rounded-md bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-300">
            ⚠{" "}
            {singleFlag && `${c.top_holding_ticker} is ${pct(topName)} of your book`}
            {singleFlag && sectorFlag && " · "}
            {sectorFlag && `${c.top_sector} is ${pct(topSector)} of your book`} — a shock to{" "}
            {singleFlag ? "that name" : "that sector"} hits you hard.
          </p>
        )}

        <Link href="/risk" className="inline-block text-sm text-primary hover:underline">
          Full sector + liquidity breakdown →
        </Link>
      </CardContent>
    </Card>
  );
}
