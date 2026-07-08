"use client";

/**
 * VaR backtest — proves the risk model holds up. Shows how often the realised
 * daily loss actually breached the 1-day VaR vs how often a normal model
 * predicts, plus the empirical return distribution with the VaR thresholds
 * drawn on it. The "more breaches than expected → fatter tails" read is the
 * credibility moment. Fail-soft to null.
 */

import {
  Bar,
  BarChart,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import type { VarBacktest as VarBacktestData } from "@/lib/queries";

const AXIS = "hsl(var(--muted-foreground))";

function pct(v: number | null | undefined, d = 1): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(d)}%`;
}

export function VarBacktest({
  data,
  loading,
}: {
  data: VarBacktestData | undefined;
  loading: boolean;
}) {
  if (loading && !data) return <Skeleton className="h-64" />;
  if (!data || data.n_days < 60 || data.var_95 == null) return null;

  const expected = data.expected_95 ?? 0.05 * data.n_days;
  const breaches = data.breaches_95;
  // Tail read: meaningfully more breaches than a normal predicts = fat tails.
  const ratio = expected > 0 ? breaches / expected : 1;
  const read =
    ratio >= 1.3
      ? "more often than a normal model predicts — your returns have fatter tails (bigger surprises) than the bell curve assumes."
      : ratio <= 0.7
        ? "less often than a normal model predicts — calmer than the bell curve assumes over this window."
        : "about as often as a normal model predicts — the bell-curve assumption held up over this window.";

  const var95 = data.var_95 as number;
  const var99 = data.var_99 ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Does your VaR hold up?</CardTitle>
        <CardDescription>
          A backtest over the last {data.n_days} trading days — how often the
          real daily loss exceeded the model&apos;s 1-day Value-at-Risk.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm">
          Your 1-day <strong>95% VaR is {pct(var95)}</strong>. Over this window it
          was breached <strong>{breaches}</strong> {breaches === 1 ? "day" : "days"} — a
          normal model expects ~{Math.round(expected)}. That&apos;s {read}
        </p>

        {(data.coverage_95 || data.coverage_99) && (
          <div className="flex flex-wrap items-center gap-2" data-testid="var-reliability">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              VaR reliability
            </span>
            {data.coverage_95 && <CoverageBadge level="95%" c={data.coverage_95} />}
            {data.coverage_99 && <CoverageBadge level="99%" c={data.coverage_99} />}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="95% VaR (1d)" value={pct(var95)} />
          <Stat label="99% VaR (1d)" value={pct(var99)} />
          <Stat label="Breaches (95%)" value={`${breaches} / ~${Math.round(expected)}`} />
          <Stat label="Worst day" value={pct(data.worst_day)} />
        </div>

        <div style={{ width: "100%", height: 220 }} data-testid="var-histogram">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data.histogram} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <XAxis
                dataKey="x"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                stroke={AXIS}
                tick={{ fontSize: 11, fill: AXIS }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} width={28} tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
                formatter={(v) => [`${v} days`, "Count"]}
                labelFormatter={(v) => `Daily return ${(Number(v) * 100).toFixed(1)}%`}
                contentStyle={{ fontSize: 12 }}
              />
              {/* VaR thresholds sit on the LOSS side (negative returns). */}
              <ReferenceLine x={-var95} stroke="hsl(var(--destructive))" strokeDasharray="4 2" />
              {var99 > 0 && (
                <ReferenceLine x={-var99} stroke="hsl(var(--destructive))" strokeOpacity={0.6} strokeDasharray="2 2" />
              )}
              <Bar dataKey="count" isAnimationActive={false}>
                {data.histogram.map((b, i) => (
                  <Cell
                    key={i}
                    fill={
                      (b.x ?? 0) <= -var95
                        ? "hsl(var(--destructive))"
                        : "hsl(var(--primary) / 0.6)"
                    }
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="text-[11px] text-muted-foreground">
          Red bars are days worse than your 95% VaR; the dashed lines mark the
          95% / 99% VaR thresholds.
        </p>
      </CardContent>
    </Card>
  );
}

function CoverageBadge({ level, c }: { level: string; c: NonNullable<VarBacktestData["coverage_95"]> }) {
  const passed = c.passed === true;
  const p = c.p_cc;
  const title =
    `Kupiec + Christoffersen coverage tests at ${level}: ` +
    (passed
      ? "PASS — neither the breach-count test (Kupiec) nor the joint count+clustering test rejects a well-calibrated VaR at the 5% level."
      : "FAIL — the breach count and/or breach clustering is unlikely under a well-calibrated VaR. Treat this VaR level with caution.") +
    ` Observed ${c.breaches} breaches vs ~${c.expected ?? "?"} expected` +
    (c.p_uc != null && p != null
      ? `; count p = ${c.p_uc.toFixed(3)}, joint p = ${p.toFixed(3)}.`
      : ".") +
    " Note: this VaR is fitted on the same window it is scored against, and the 99% level has few expected breaches — read verdicts as a health check, not a certification.";
  return (
    <span
      title={title}
      className={`inline-flex cursor-help items-center gap-1 rounded-full border px-2.5 py-0.5 font-mono text-[11px] tabular-nums ${
        passed
          ? "border-[hsl(var(--success))]/40 text-[hsl(var(--success))]"
          : "border-destructive/50 text-destructive"
      }`}
    >
      {level} {passed ? "PASS" : "FAIL"}
      {p != null && <span className="text-muted-foreground">p={p.toFixed(2)}</span>}
    </span>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-2.5">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-mono text-lg">{value}</div>
    </div>
  );
}
