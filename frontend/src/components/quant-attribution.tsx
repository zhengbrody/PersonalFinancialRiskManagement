"use client";

/**
 * Performance-attribution tab for /quant. On-demand (heavy compute): KPIs
 * (tracking error / information ratio / hit ratio) + Brinson allocation vs
 * selection bars + factor-beta bars. Plain-language captions keep it readable
 * for a retail user. Deterministic — no credits.
 */

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HorizontalBarChart, type BarDatum } from "@/components/ui/bar-chart";
import { DataProvenance } from "@/components/data-provenance";
import { ApiError } from "@/lib/api";
import { useAttribution, type Attribution } from "@/lib/queries";

function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}
function num(v: number | null | undefined, digits = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}

export function QuantAttribution() {
  const attr = useAttribution();
  const err = attr.error as ApiError | null;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Where your return came from vs the S&amp;P 500 — sector bets
          (allocation), stock picks (selection), and factor exposure.
        </p>
        <Button size="sm" disabled={attr.isPending} onClick={() => attr.mutate()}>
          {attr.isPending ? "Computing…" : attr.data ? "Re-run" : "Run attribution"}
        </Button>
      </div>

      {attr.isPending && <Skeleton className="h-64" />}
      {err && <AttributionError error={err} />}
      {!attr.isPending && attr.data && <AttributionResult data={attr.data} />}
      {!attr.isPending && !attr.data && !err && (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Run attribution to break down your active return vs the benchmark.
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function AttributionResult({ data }: { data: Attribution }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Active return (ann.)" value={pct(data.active_return_annual)} />
        <Kpi label="Tracking error" value={pct(data.tracking_error)} />
        <Kpi label="Information ratio" value={num(data.information_ratio)} />
        <Kpi label="Hit ratio" value={pct(data.hit_ratio, 0)} />
      </div>

      {data.brinson && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Brinson decomposition</CardTitle>
            <CardDescription>
              Did your sector weighting (allocation) or your stock-picking
              (selection) drive the active return?
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 p-4 md:grid-cols-2">
            <dl className="space-y-1 text-sm">
              <Row label="Allocation effect" value={pct(data.brinson.allocation_effect)} />
              <Row label="Selection effect" value={pct(data.brinson.selection_effect)} />
              <Row label="Interaction" value={pct(data.brinson.interaction_effect)} />
              <Row
                label="Total active"
                value={pct(data.brinson.total_active_return)}
                strong
              />
            </dl>
            {data.brinson.sector_detail.length > 0 && (
              <HorizontalBarChart
                data={sectorBars(data)}
                valueFormatter={(v) => `${v.toFixed(2)}%`}
                ariaLabel="Sector total effect"
              />
            )}
          </CardContent>
        </Card>
      )}

      {data.factor && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Factor exposure</CardTitle>
            <CardDescription>
              How your portfolio loads on the big market factors (regression
              betas). Alpha {pct(data.factor.alpha)} · R² {num(data.factor.r_squared)}.
            </CardDescription>
          </CardHeader>
          <CardContent className="p-4">
            <HorizontalBarChart
              data={factorBars(data)}
              valueFormatter={(v) => v.toFixed(2)}
              ariaLabel="Factor betas"
            />
          </CardContent>
        </Card>
      )}
      <DataProvenance
        asOf={data.as_of}
        source="Brinson + factor regression on daily yfinance closes"
        observations={data.observations}
      />
    </div>
  );
}

function sectorBars(data: Attribution): BarDatum[] {
  return (data.brinson?.sector_detail ?? [])
    .filter((s) => s.total_effect != null)
    .map((s) => ({
      label: s.sector,
      value: Math.round((s.total_effect as number) * 1000) / 10,
      color: (s.total_effect as number) >= 0 ? "hsl(var(--primary))" : "hsl(var(--destructive))",
    }));
}

function factorBars(data: Attribution): BarDatum[] {
  return Object.entries(data.factor?.factor_betas ?? {})
    .filter(([, b]) => b != null)
    .map(([factor, b]) => ({
      label: factor,
      value: Math.round((b as number) * 1000) / 1000,
      color: (b as number) >= 0 ? "hsl(var(--primary))" : "hsl(var(--muted-foreground))",
    }));
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
        <p className="font-mono text-2xl">{value}</p>
      </CardContent>
    </Card>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={`flex justify-between border-b border-border/40 py-1 ${strong ? "font-medium" : ""}`}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-mono">{value}</dd>
    </div>
  );
}

function AttributionError({ error }: { error: ApiError }) {
  const msg =
    error.code === "no_active_portfolio"
      ? "Create a portfolio (2+ holdings) to attribute performance."
      : error.code === "unprocessable"
        ? error.message
        : "Couldn't compute attribution — try again shortly.";
  return (
    <Card className="border-destructive/40">
      <CardContent className="py-4 text-sm">{msg}</CardContent>
    </Card>
  );
}
