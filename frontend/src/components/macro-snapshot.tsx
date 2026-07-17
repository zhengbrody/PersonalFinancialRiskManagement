"use client";

/**
 * Macro-snapshot widget — landing-page above-the-fold proof that the
 * new backend is alive and pulling source-stamped public data. No auth needed.
 *
 * Layout: 4 KPI tiles (Fed Funds, 10Y, CPI, Unemployment) + an inline
 * yield-curve mini-bar. Skeleton on load; a short notice card on
 * error so the home page never looks broken.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMacroSnapshot, useYieldCurve } from "@/lib/queries";

const SERIES = ["DFF", "DGS10", "CPIAUCSL", "UNRATE"];

const FRIENDLY_LABEL: Record<string, string> = {
  DFF: "Fed Funds",
  DGS10: "10Y Treasury",
  CPIAUCSL: "CPI (level)",
  UNRATE: "Unemployment",
};

const FRIENDLY_UNIT: Record<string, string> = {
  DFF: "%",
  DGS10: "%",
  CPIAUCSL: "",
  UNRATE: "%",
};

export function MacroSnapshot() {
  const snapshot = useMacroSnapshot(SERIES);
  const yc = useYieldCurve();
  const ttl = snapshot.data?.cache_ttl_seconds ?? yc.data?.cache_ttl_seconds ?? 3600;

  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Live macro · source-stamped data
          </p>
          <h2 className="text-2xl font-semibold tracking-tight">
            US rates &amp; macro
          </h2>
          <p className="text-xs text-muted-foreground">
            FRED + US Treasury. Auto-refreshes after {fmtTtl(ttl)}; new
            observations appear as soon as the source publishes and cache
            expires.
          </p>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {snapshot.isLoading &&
          SERIES.map((id) => <Skeleton key={id} className="h-24" />)}

        {snapshot.isError && (
          <MacroErrorTile message="Could not load FRED data." />
        )}

        {snapshot.data?.series.map((s) => (
          <Card key={s.series_id}>
            <CardHeader className="space-y-1 p-4">
              <CardTitle className="text-sm font-medium">
                {FRIENDLY_LABEL[s.series_id] ?? s.label}
              </CardTitle>
              <p className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                {s.series_id}
              </p>
            </CardHeader>
            <CardContent className="space-y-1 p-4 pt-0">
              <p className="font-mono text-2xl">
                {fmtValue(s.latest_value)}
                <span className="ml-0.5 text-xs text-muted-foreground">
                  {FRIENDLY_UNIT[s.series_id] ?? ""}
                </span>
              </p>
            <p className="text-[10px] text-muted-foreground">
                as of {s.latest_date ?? "—"} · {snapshot.data?.source ?? "FRED"}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Yield curve mini-bar */}
      <Card>
        <CardHeader className="flex flex-row items-end justify-between p-4 pb-2">
          <div>
            <CardTitle className="text-sm font-medium">
              US Treasury yield curve
            </CardTitle>
            <p className="text-[10px] text-muted-foreground">
              as of {yc.data?.as_of ?? "—"} · {yc.data?.source ?? "US Treasury"}
            </p>
          </div>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {yc.isLoading && <Skeleton className="h-16" />}
          {yc.isError && (
            <p className="text-xs text-muted-foreground">
              Could not load Treasury data.
            </p>
          )}
          {yc.data && yc.data.points.length > 0 && (
            <YieldCurveStrip points={yc.data.points} />
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function YieldCurveStrip({
  points,
}: {
  points: { tenor: string; yield_pct: number }[];
}) {
  // Layout: per-tenor mini column, height ~= yield relative to max.
  const max = Math.max(...points.map((p) => p.yield_pct), 0.01);
  return (
    <div className="flex items-end gap-2">
      {points.map((p) => {
        const heightPct = (p.yield_pct / max) * 100;
        return (
          <div key={p.tenor} className="flex flex-1 flex-col items-center gap-1">
            <div
              className="w-full rounded-sm bg-primary/70"
              style={{ height: `${Math.max(heightPct, 4)}%`, minHeight: 8 }}
              title={`${p.tenor}: ${p.yield_pct.toFixed(2)}%`}
            />
            <span className="font-mono text-[10px] text-muted-foreground">
              {p.tenor}
            </span>
            <span className="font-mono text-[10px]">
              {p.yield_pct.toFixed(2)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

function MacroErrorTile({ message }: { message: string }) {
  return (
    <div className="col-span-full rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-muted-foreground">
      {message}
    </div>
  );
}

function fmtValue(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  // Heuristic — CPI level is in the 300s, rates are <10. Different
  // decimal counts read better in each regime.
  if (Math.abs(v) >= 100) return v.toFixed(1);
  return v.toFixed(2);
}

function fmtTtl(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "about 1 hour";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}
