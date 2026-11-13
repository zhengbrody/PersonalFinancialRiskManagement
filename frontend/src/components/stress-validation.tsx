"use client";

/**
 * Model validation — the published point-in-time backtest of the stress model.
 * Public data (`GET /risk/stress_validation`); nothing here is the user's.
 *
 * The panel states what was tested and what was not, shows where the model is
 * weak (interval coverage, worst episodes) as plainly as where it is strong,
 * and never presents the test as a forecast of crises.
 */

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Kpi } from "@/components/ui/kpi";
import { Skeleton } from "@/components/ui/skeleton";
import { AXIS, GRID, INK, Seg, Tip, pct, signedPct } from "@/components/stress-shared";
import { useStressValidation, type StressValidation, type ValidationRow } from "@/lib/crisis-replay";

const MODEL_LABEL: Record<string, string> = {
  seven_factor: "Seven-factor model",
  market_beta_only: "Market beta only",
  beta_one: "Assume beta = 1",
};
const MODEL_NOTE: Record<string, string> = {
  seven_factor: "what the Stress Lab uses",
  market_beta_only: "one factor: the stock market",
  beta_one: "no model: everything moves with the market",
};

const abs = (v: number | null | undefined, d = 1) => (v == null ? "n/a" : pct(Math.abs(v), d));

export function StressValidationPanel() {
  const q = useStressValidation();
  if (q.isPending) {
    return (
      <div className="space-y-6" aria-busy="true">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="space-y-3 rounded-lg border border-border bg-card px-4 py-4 text-sm" role="alert">
        <p className="font-medium text-foreground">The validation report is unavailable</p>
        <Button variant="outline" onClick={() => q.refetch()}>
          Try again
        </Button>
      </div>
    );
  }
  return <Report r={q.data} />;
}

function Report({ r }: { r: StressValidation }) {
  const c = r.conditional;
  const seven = c.models.seven_factor;
  const iv = c.interval;
  const pooled95 = r.rolling_var.pooled.find((p) => Math.abs(p.level - 0.95) < 1e-9);
  const pooled99 = r.rolling_var.pooled.find((p) => Math.abs(p.level - 0.99) < 1e-9);
  const intervalShort = iv.coverage != null && iv.coverage < iv.nominal - 0.05;

  return (
    <div className="space-y-6" data-testid="stress-validation">
      <Card>
        <CardHeader>
          <CardTitle>How accurate is the stress model?</CardTitle>
          <CardDescription>
            An out-of-sample test. Before each past crisis the model was fitted only on data available at
            the time, then asked what {c.models.seven_factor.n} fund portfolios would lose given the market
            moves that followed. The answers are compared with what those portfolios actually did.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!r.hash_verified ? (
            <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm" role="alert">
              This report&apos;s contents do not match its recorded hash. Do not rely on it.
            </p>
          ) : null}
          {!r.model_version_current ? (
            <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
              This report validated model {r.model_version}, which is not the version running now.
            </p>
          ) : null}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Typical error" value={abs(seven.mae)} />
            <Kpi label="Average bias" value={seven.bias == null ? "n/a" : signedPct(seven.bias)} />
            <Kpi
              label={`${Math.round(iv.nominal * 100)}% range held`}
              value={iv.coverage == null ? "n/a" : pct(iv.coverage, 0)}
              tone={intervalShort ? "warn" : "neutral"}
            />
            <Kpi
              label="99% VaR breached"
              value={pooled99?.breach_rate == null ? "n/a" : pct(pooled99.breach_rate)}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            Typical error is the average gap, in percentage points of return, between the predicted and the
            actual loss. A negative bias means the model predicted larger losses than happened.
            {intervalShort
              ? ` The model's ${Math.round(iv.nominal * 100)}% range contained the real outcome only ${pct(iv.coverage ?? 0, 0)} of the time (${iv.inside} of ${iv.n}): its ranges are too narrow, so treat the range in the Stress Lab as a lower bound on the uncertainty.`
              : ""}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Against simpler models</CardTitle>
          <CardDescription>
            The same {seven.n} outcomes scored three ways. A model is only worth having if it beats the
            simpler ones.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm" data-testid="validation-models">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Model</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Typical error (MAE)</th>
                  <th className="py-1.5 pr-3 text-right font-medium">RMSE</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Bias</th>
                  <th className="py-1.5 text-right font-medium">Calibration slope</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(MODEL_LABEL).map((k) => {
                  const m = c.models[k];
                  if (!m) return null;
                  return (
                    <tr key={k} className="border-t border-border">
                      <td className="py-2 pr-3">
                        <span className={k === "seven_factor" ? "font-medium" : ""}>{MODEL_LABEL[k]}</span>
                        <div className="text-xs text-muted-foreground">{MODEL_NOTE[k]}</div>
                      </td>
                      <td className="py-2 pr-3 text-right font-mono tabular-nums">{abs(m.mae)}</td>
                      <td className="py-2 pr-3 text-right font-mono tabular-nums">{abs(m.rmse)}</td>
                      <td className="py-2 pr-3 text-right font-mono tabular-nums">
                        {m.bias == null ? "n/a" : signedPct(m.bias)}
                      </td>
                      <td className="py-2 text-right font-mono tabular-nums">
                        {m.calibration_slope == null ? "n/a" : m.calibration_slope.toFixed(2)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            A calibration slope of 1.00 means predicted and actual losses scale together; below 1, large
            predicted losses tend to be overstated.
          </p>
        </CardContent>
      </Card>

      <PredictedVsRealised r={r} />

      <Card>
        <CardHeader>
          <CardTitle>Is the loss distribution calibrated?</CardTitle>
          <CardDescription>
            A separate, unconditional test. Every two weeks since 2010 the model, fitted only on the past,
            stated the loss that should be exceeded 5% and 1% of the time over the next ten trading days.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-left text-sm" data-testid="validation-var">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Level</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Windows</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Breaches</th>
                  <th className="py-1.5 pr-3 text-right font-medium">Breach rate</th>
                  <th className="py-1.5 text-right font-medium">Expected</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                {[pooled95, pooled99].map((p) =>
                  p ? (
                    <tr key={p.level} className="border-t border-border">
                      <td className="py-2 pr-3">{Math.round(p.level * 100)}% VaR</td>
                      <td className="py-2 pr-3 text-right">{(p.windows ?? 0).toLocaleString()}</td>
                      <td className="py-2 pr-3 text-right">{p.breaches}</td>
                      <td className="py-2 pr-3 text-right">{p.breach_rate == null ? "n/a" : pct(p.breach_rate)}</td>
                      <td className="py-2 text-right text-muted-foreground">{pct(p.expected_rate)}</td>
                    </tr>
                  ) : null,
                )}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            A breach rate below the expected rate means the model was cautious at that level; above it, too
            optimistic. Pooled across {r.rolling_var.portfolios.length} fund portfolios, whose windows
            overlap in time and are not independent.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>What this does and does not show</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <ul className="list-disc space-y-1.5 pl-5 text-muted-foreground">
            {r.caveats.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
          <dl className="grid gap-x-6 gap-y-2 text-xs sm:grid-cols-2" data-testid="validation-provenance">
            <Prov k="Generated" v={r.generated_at} />
            <Prov k="Model version" v={r.model_version} />
            <Prov k="Prices" v={`${r.data.source}, ${r.data.first_date} to ${r.data.last_date}`} />
            <Prov
              k="Fitting rule"
              v={`${r.method.lookback_weeks} weeks of history, ending ${r.method.embargo_trading_days} trading days before each episode`}
            />
            <Prov k="Report hash (sha256)" v={r.content_sha256} mono />
            <Prov k="Data hash (sha256)" v={r.data.sha256} mono />
            <Prov k="Code hash (sha256)" v={r.method.code_sha256} mono />
            <Prov k="Hash check" v={r.hash_verified ? "Contents match the report hash" : "MISMATCH"} />
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}

function Prov({ k, v, mono = false }: { k: string; v: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-muted-foreground">{k}</dt>
      <dd className={`break-all text-foreground ${mono ? "font-mono" : ""}`}>{v}</dd>
    </div>
  );
}

function PredictedVsRealised({ r }: { r: StressValidation }) {
  const episodes = useMemo(() => {
    const seen = new Map<string, string>();
    for (const row of r.conditional.rows) seen.set(row.episode, row.episode_label);
    return [...seen.entries()];
  }, [r]);
  const [episode, setEpisode] = useState<string>("all");
  const [showHindsight, setShowHindsight] = useState(false);
  const rows = r.conditional.rows.filter(
    (x) => (episode === "all" || x.episode === episode) && (showHindsight || x.selection === "rule_based"),
  );
  const points = rows.map((x) => ({ x: x.predicted, y: x.realised, row: x }));
  const lo = Math.min(-0.05, ...points.flatMap((p) => [p.x, p.y]));
  const hi = Math.max(0.05, ...points.flatMap((p) => [p.x, p.y]));
  const level = Math.round(r.method.interval_level * 100);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Predicted against actual, case by case</CardTitle>
        <CardDescription>
          Each point is one portfolio in one crisis. On the diagonal the model was exactly right; below it
          the real loss was larger than predicted.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Episode
            <select
              value={episode}
              onChange={(e) => setEpisode(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground"
            >
              <option value="all">All episodes</option>
              {episodes.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <Seg
            label="Hindsight-picked basket"
            value={showHindsight}
            options={[
              { value: false, label: "Hide" },
              { value: true, label: "Show" },
            ]}
            onChange={setShowHindsight}
          />
        </div>
        <div style={{ width: "100%", height: 320 }} role="img" aria-label="Predicted versus actual portfolio returns">
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 24 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
              <XAxis
                type="number"
                dataKey="x"
                domain={[lo, hi]}
                tickFormatter={(v: number) => pct(v, 0)}
                tick={{ fontSize: 11, fill: AXIS }}
                tickLine={false}
                axisLine={{ stroke: GRID }}
                label={{ value: "Predicted return", position: "insideBottom", offset: -12, fontSize: 11, fill: AXIS }}
              />
              <YAxis
                type="number"
                dataKey="y"
                domain={[lo, hi]}
                tickFormatter={(v: number) => pct(v, 0)}
                tick={{ fontSize: 11, fill: AXIS }}
                width={48}
                tickLine={false}
                axisLine={false}
              />
              <ZAxis range={[60, 60]} />
              <ReferenceLine segment={[{ x: lo, y: lo }, { x: hi, y: hi }]} stroke={AXIS} strokeDasharray="4 4" />
              <Tooltip
                cursor={{ strokeDasharray: "3 3" }}
                content={({ active, payload }) => {
                  const row = active ? (payload?.[0]?.payload as { row: ValidationRow } | undefined)?.row : undefined;
                  return row ? (
                    <Tip
                      rows={[
                        [row.portfolio_label, row.episode_label],
                        ["Predicted", signedPct(row.predicted)],
                        ["Actual", signedPct(row.realised)],
                        ["Fitted up to", row.fit_cutoff],
                      ]}
                    />
                  ) : null;
                }}
              />
              <Scatter data={points} fill={INK} fillOpacity={0.75} isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs" data-testid="validation-rows">
            <thead className="text-muted-foreground">
              <tr>
                <th className="py-1.5 pr-3 font-medium">Episode</th>
                <th className="py-1.5 pr-3 font-medium">Portfolio</th>
                <th className="py-1.5 pr-3 font-medium">Fitted up to</th>
                <th className="py-1.5 pr-3 text-right font-medium">Actual</th>
                <th className="py-1.5 pr-3 text-right font-medium">Predicted</th>
                <th className="py-1.5 pr-3 text-right font-medium">{level}% range</th>
                <th className="py-1.5 text-right font-medium">Error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => {
                const inside = x.band_low <= x.realised && x.realised <= x.band_high;
                return (
                  <tr key={`${x.episode}-${x.portfolio}`} className="border-t border-border">
                    <td className="py-1.5 pr-3">{x.episode_label}</td>
                    <td className="py-1.5 pr-3">
                      {x.portfolio_label}
                      {x.selection === "hindsight" ? (
                        <span className="ml-1.5">
                          <Badge tone="warning">picked with hindsight</Badge>
                        </span>
                      ) : null}
                    </td>
                    <td className="py-1.5 pr-3 font-mono">{x.fit_cutoff}</td>
                    <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{signedPct(x.realised)}</td>
                    <td className="py-1.5 pr-3 text-right font-mono tabular-nums">{signedPct(x.predicted)}</td>
                    <td className={`py-1.5 pr-3 text-right font-mono tabular-nums ${inside ? "text-muted-foreground" : "text-warning"}`}>
                      {signedPct(x.band_low, 0)} to {signedPct(x.band_high, 0)}
                      {inside ? "" : " · missed"}
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums">{signedPct(x.error)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">
          All outcomes are actual market prices of real funds. The basket of today&apos;s five largest
          technology stocks could not have been chosen in advance, so it is hidden by default and kept out
          of every summary number.
          {r.conditional.skipped.length
            ? ` ${r.conditional.skipped.length} portfolio-episode pairs were skipped because a fund had too little history before the episode.`
            : ""}
        </p>
      </CardContent>
    </Card>
  );
}
