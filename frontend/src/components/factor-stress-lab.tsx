"use client";

/**
 * Stress Lab — the seven-factor stress engine, interactive.
 *
 * Every figure on this panel comes from `POST /risk/factor_stress`; nothing is
 * computed here except unit formatting and which slice of the response is on
 * screen. Controls that change the calculation (horizon, confidence, fill,
 * your own scenario) refetch; controls that change the view (selected
 * scenario, regime, selected holding) do not.
 */

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TimeSeriesChart } from "@/components/ui/chart-line";
import { Kpi } from "@/components/ui/kpi";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import {
  FACTOR_IDS,
  INPUT_HINT,
  inputToShock,
  shockToDisplay,
  useFactorStress,
  type FactorId,
  type FactorStress,
  type FactorStressParams,
  type Regime,
  type StressScenario,
} from "@/lib/factor-stress";
import { usePortfolioContext } from "@/lib/portfolio-context";

const LOSS = "hsl(var(--destructive))";
const GAIN = "hsl(var(--success))";
const INK = "hsl(var(--primary))";
const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";

const SHORT: Record<string, string> = {
  equity: "Equity",
  rates: "Rates",
  credit: "Credit",
  usd: "Dollar",
  oil: "Oil",
  vol: "Vol",
  gold: "Gold",
};

const usd = (v: number) =>
  `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const pct = (v: number, d = 1) => `${v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;
const signedPct = (v: number, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;

function Seg<T extends string | number | boolean>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <div role="group" aria-label={label} className="inline-flex rounded-md border border-border p-0.5">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={o.value === value}
            onClick={() => onChange(o.value)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              o.value === value
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Tip({ rows }: { rows: [string, string][] }) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
      {rows.map(([k, v]) => (
        <p key={k} className="flex justify-between gap-4">
          <span className="text-muted-foreground">{k}</span>
          <span className="font-mono font-medium text-foreground">{v}</span>
        </p>
      ))}
    </div>
  );
}

export function FactorStressLab() {
  const { activePortfolioId } = usePortfolioContext();
  const [params, setParams] = useState<FactorStressParams>({
    horizon_weeks: 2,
    confidence: 0.95,
    fill_unspecified: true,
    custom_shocks: null,
  });
  const [regime, setRegime] = useState<Regime>("crisis");
  const [selectedId, setSelectedId] = useState<string>("equity_crash");
  const [kind, setKind] = useState<"all" | "hypothetical" | "historical">("all");
  const [holding, setHolding] = useState<string | null>(null);

  const q = useFactorStress(activePortfolioId, params, true);
  const data = q.data;

  if (q.isPending) return <LabSkeleton />;
  if (q.isError || !data) return <LabError error={q.error} onRetry={() => q.refetch()} />;

  const scenarios = data.scenarios;
  const selected =
    scenarios.find((s) => s.id === selectedId) ??
    scenarios.find((s) => s.id === "equity_crash") ??
    scenarios[0];

  return (
    <div className="space-y-6" data-testid="stress-lab" aria-busy={q.isFetching}>
      <Card>
        <CardHeader>
          <CardTitle>Stress Lab</CardTitle>
          <CardDescription>
            Seven market factors — equities, rates, credit, the dollar, oil, volatility and gold —
            shocked together the way they move in a crisis. Prices as of {data.as_of}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
            <Seg
              label="Horizon"
              value={params.horizon_weeks}
              options={[
                { value: 1, label: "1 week" },
                { value: 2, label: "2 weeks" },
                { value: 4, label: "4 weeks" },
              ]}
              onChange={(v) => setParams((p) => ({ ...p, horizon_weeks: v }))}
            />
            <Seg
              label="Confidence"
              value={params.confidence}
              options={[
                { value: 0.9, label: "90%" },
                { value: 0.95, label: "95%" },
                { value: 0.99, label: "99%" },
              ]}
              onChange={(v) => setParams((p) => ({ ...p, confidence: v }))}
            />
            <Seg
              label="Other factors"
              value={params.fill_unspecified}
              options={[
                { value: true, label: "Move with the shock" },
                { value: false, label: "Hold flat" },
              ]}
              onChange={(v) => setParams((p) => ({ ...p, fill_unspecified: v }))}
            />
            {q.isFetching ? <span className="text-xs text-muted-foreground">Recalculating…</span> : null}
          </div>
          <AccountStrip data={data} />
          <CoverageNotes data={data} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Scenario comparison</CardTitle>
          <CardDescription>
            Estimated change in your net equity under each scenario. The thin bar is the{" "}
            {Math.round(data.confidence * 100)}% range. Select a scenario to inspect it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Seg
            label="Show"
            value={kind}
            options={[
              { value: "all", label: "All" },
              { value: "hypothetical", label: "Hypothetical" },
              { value: "historical", label: "Historical" },
            ]}
            onChange={setKind}
          />
          <ScenarioBars
            scenarios={scenarios.filter((s) => kind === "all" || s.kind === kind || s.kind === "custom")}
            base={data.account.net_equity > 0 ? data.account.net_equity : data.account.gross_long}
            selectedId={selected.id}
            onSelect={setSelectedId}
          />
        </CardContent>
      </Card>

      <ScenarioDetail
        data={data}
        s={selected}
        holding={holding}
        onHolding={(t) => setHolding((cur) => (cur === t ? null : t))}
      />

      <CustomScenario
        data={data}
        active={params.custom_shocks}
        onApply={(shocks) => {
          setParams((p) => ({ ...p, custom_shocks: shocks }));
          if (shocks) setSelectedId("custom");
        }}
      />

      <Card>
        <CardHeader>
          <CardTitle>Loss distribution</CardTitle>
          <CardDescription>
            {data.distribution[regime].n_sims.toLocaleString()} simulated {data.horizon_weeks}-week
            outcomes with fat tails, using {regime === "crisis" ? "crisis-period" : "recent calm-market"}{" "}
            factor behaviour. Options are fully repriced in every outcome.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Seg
            label="Market regime"
            value={regime}
            options={[
              { value: "crisis", label: "Crisis" },
              { value: "calm", label: "Calm" },
            ]}
            onChange={setRegime}
          />
          <Distribution data={data} regime={regime} />
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Factor exposure by holding</CardTitle>
            <CardDescription>
              Each cell is the holding&apos;s sensitivity (beta) to a factor. Faded cells are not
              statistically distinguishable from zero. Select a row for details.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ExposureHeatmap
              data={data}
              holding={holding}
              onHolding={(t) => setHolding((cur) => (cur === t ? null : t))}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Factor correlations</CardTitle>
            <CardDescription>
              How the seven factors move together in {regime === "crisis" ? "past crises" : "the recent calm period"}{" "}
              ({regime === "crisis" ? data.correlation.crisis_n_obs : data.correlation.calm_n_obs} weeks).
              Switch regime above to compare.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FactorCorr matrix={data.correlation[regime]} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Where the risk comes from</CardTitle>
          <CardDescription>
            Share of your stock book&apos;s {regime} volatility explained by each factor, and by
            single-name risk the factors do not explain. A negative share is a hedge.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Decomposition data={data} regime={regime} />
        </CardContent>
      </Card>

      <details className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium">How this is calculated</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">
          {data.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
          <li>Model version {data.model_version}. Educational analysis, not investment advice.</li>
        </ul>
        <table className="mt-4 w-full text-left text-xs">
          <thead className="text-muted-foreground">
            <tr>
              <th className="py-1 pr-3 font-medium">Factor</th>
              <th className="py-1 pr-3 font-medium">Built from</th>
              <th className="py-1 font-medium">What a shock means</th>
            </tr>
          </thead>
          <tbody>
            {data.factors.map((f) => (
              <tr key={f.id} className="border-t border-border align-top">
                <td className="py-1.5 pr-3 font-medium text-foreground">
                  {f.label}
                  {f.available ? null : <span className="ml-1 text-warning">(no data)</span>}
                </td>
                <td className="py-1.5 pr-3 font-mono">{f.proxy}</td>
                <td className="py-1.5 text-muted-foreground">{f.unit}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

// ── account + coverage ───────────────────────────────────────────────

function AccountStrip({ data }: { data: FactorStress }) {
  const a = data.account;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Kpi label="Net equity" value={usd(a.net_equity)} />
      <Kpi
        label="Leverage"
        value={a.leverage == null ? "n/a" : `${a.leverage.toFixed(2)}×`}
        tone={a.leverage != null && a.leverage > 1.5 ? "warn" : "neutral"}
      />
      <Kpi
        label="Modelled"
        value={pct(data.coverage.modelled_weight, 0)}
        tone={data.coverage.modelled_weight < 0.9 ? "warn" : "neutral"}
      />
      <Kpi
        label="Effective holdings"
        value={data.concentration.effective_holdings == null ? "n/a" : data.concentration.effective_holdings.toFixed(1)}
      />
    </div>
  );
}

function CoverageNotes({ data }: { data: FactorStress }) {
  const c = data.coverage;
  const notes: string[] = [];
  if (c.proxied.length)
    notes.push(
      `${c.proxied.join(", ")}: too little price history, so the sector fund's loadings are used (marked "proxy").`,
    );
  if (c.unmodelled.length)
    notes.push(
      `${c.unmodelled.map((u) => `${u.ticker} (${pct(u.weight, 0)})`).join(", ")} could not be modelled and is left out of every scenario — it is not assumed to move with the market.`,
    );
  if (c.unpriced.length) notes.push(`No price for ${c.unpriced.join(", ")}.`);
  for (const leg of c.option_legs_skipped) notes.push(`${leg.contract}: ${leg.reason}.`);
  const all = [...notes, ...data.warnings];
  if (!all.length) return null;
  return (
    <ul
      className="space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground"
      data-testid="stress-coverage-notes"
    >
      {all.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}

// ── scenario comparison ──────────────────────────────────────────────

function ScenarioBars({
  scenarios,
  base,
  selectedId,
  onSelect,
}: {
  scenarios: StressScenario[];
  base: number;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const span = Math.max(
    0.01,
    ...scenarios.flatMap((s) => [Math.abs(s.band_low_usd / base), Math.abs(s.band_high_usd / base)]),
  );
  const x = (v: number) => 50 + (v / span) * 50; // percent of track; 50 = zero
  return (
    <ul className="space-y-1" aria-label="Scenarios">
      {scenarios.map((s) => {
        const lo = x(s.band_low_usd / base);
        const hi = x(s.band_high_usd / base);
        const mid = x(s.pnl_pct);
        const on = s.id === selectedId;
        return (
          <li key={s.id}>
            <button
              type="button"
              onClick={() => onSelect(s.id)}
              aria-pressed={on}
              title={`${s.label}: ${signedPct(s.pnl_pct)} (${usd(s.band_low_usd)} to ${usd(s.band_high_usd)})`}
              className={`grid w-full grid-cols-[minmax(7rem,13rem)_1fr_4.5rem] items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                on ? "bg-muted" : "hover:bg-muted/50"
              }`}
            >
              <span className="truncate">
                {s.label}
                {s.kind !== "hypothetical" ? (
                  <span className="ml-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    {s.kind === "historical" ? "replay" : "yours"}
                  </span>
                ) : null}
              </span>
              <span className="relative h-5">
                <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <span
                  className="absolute top-1/2 h-px -translate-y-1/2"
                  style={{ left: `${Math.min(lo, hi)}%`, width: `${Math.abs(hi - lo)}%`, backgroundColor: AXIS }}
                />
                <span
                  className="absolute top-1 bottom-1 rounded-sm"
                  style={{
                    left: `${Math.min(50, mid)}%`,
                    width: `${Math.abs(mid - 50)}%`,
                    backgroundColor: s.pnl_pct < 0 ? LOSS : GAIN,
                  }}
                />
              </span>
              <span className="text-right font-mono tabular-nums">{signedPct(s.pnl_pct)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// ── one scenario ─────────────────────────────────────────────────────

function ScenarioDetail({
  data,
  s,
  holding,
  onHolding,
}: {
  data: FactorStress;
  s: StressScenario;
  holding: string | null;
  onHolding: (t: string) => void;
}) {
  const hasOptions = data.coverage.option_legs_repriced > 0;
  const hasLoan = data.account.margin_loan > 0;
  const waterfall = useMemo(() => {
    let run = 0;
    const steps = s.by_factor
      .filter((f) => Math.abs(f.pnl_usd) > 0.005)
      .map((f) => ({ label: SHORT[f.factor] ?? f.factor, delta: f.pnl_usd }));
    if (hasOptions) steps.push({ label: "Options", delta: s.options.pnl_usd });
    const rows = steps.map((st) => {
      const start = run;
      run += st.delta;
      return { label: st.label, range: [Math.min(start, run), Math.max(start, run)], delta: st.delta, total: false };
    });
    rows.push({ label: "Total", range: [Math.min(0, s.pnl_usd), Math.max(0, s.pnl_usd)], delta: s.pnl_usd, total: true });
    return rows;
  }, [s, hasOptions]);

  const holdings = s.by_holding.filter((h) => Math.abs(h.pnl_usd) > 0.005);

  return (
    <Card data-testid="stress-scenario-detail">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {s.label}
          <Badge tone={s.pnl_usd < 0 ? "danger" : "success"}>{signedPct(s.pnl_pct)}</Badge>
        </CardTitle>
        <CardDescription>{s.source}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Kpi label="Estimated P&L" value={usd(s.pnl_usd)} tone={s.pnl_usd < 0 ? "bad" : "ok"} />
          <Kpi
            label={`${Math.round(data.confidence * 100)}% range`}
            value={`${usd(s.band_low_usd)} to ${usd(s.band_high_usd)}`}
          />
          <Kpi
            label="Margin used after"
            value={s.margin.utilisation_after == null ? "n/a" : pct(s.margin.utilisation_after, 0)}
            tone={s.margin.breach ? "bad" : (s.margin.utilisation_after ?? 0) > 0.75 ? "warn" : "neutral"}
          />
          <Kpi
            label="Margin call at"
            value={
              !hasLoan
                ? "no loan"
                : s.margin.breach
                  ? "breached"
                  : s.margin.breach_multiple == null
                    ? "not on this path"
                    : `${s.margin.breach_multiple.toFixed(1)}× this shock`
            }
            tone={s.margin.breach ? "bad" : "neutral"}
          />
        </div>

        <div>
          <h4 className="mb-2 text-sm font-medium">Factor moves in this scenario</h4>
          <div className="flex flex-wrap gap-2">
            {FACTOR_IDS.map((f) => {
              const spec = data.factors.find((x) => x.id === f);
              const state = !spec?.available ? "no data" : s.specified.includes(f) ? "set" : s.filled.includes(f) ? "implied" : "flat";
              return (
                <span
                  key={f}
                  title={spec?.unit}
                  className={`rounded-md border px-2 py-1 text-xs ${
                    state === "set" ? "border-primary/50 bg-primary/10" : "border-border"
                  }`}
                >
                  <span className="text-muted-foreground">{SHORT[f]} </span>
                  <span className="font-mono font-medium">{spec?.available ? shockToDisplay(f, s.shocks[f] ?? 0) : "—"}</span>
                  <span className="ml-1 text-[10px] uppercase tracking-wide text-muted-foreground">{state}</span>
                </span>
              );
            })}
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h4 className="mb-2 text-sm font-medium">P&L by factor</h4>
            <div style={{ width: "100%", height: 260 }} role="img" aria-label="Profit and loss waterfall by factor">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={waterfall} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={{ stroke: GRID }} interval={0} />
                  <YAxis tickFormatter={usd} tick={{ fontSize: 11, fill: AXIS }} width={64} tickLine={false} axisLine={false} />
                  <ReferenceLine y={0} stroke={AXIS} />
                  <Tooltip
                    cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
                    content={({ active, payload }) => {
                      const row = active ? (payload?.[0]?.payload as (typeof waterfall)[number] | undefined) : undefined;
                      return row ? <Tip rows={[[row.label, usd(row.delta)]]} /> : null;
                    }}
                  />
                  <Bar dataKey="range" radius={2} isAnimationActive={false}>
                    {waterfall.map((r) => (
                      <Cell key={r.label} fill={r.total ? INK : r.delta < 0 ? LOSS : GAIN} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            {hasOptions ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Options {usd(s.options.pnl_usd)} = delta {usd(s.options.delta_usd)} + convexity{" "}
                {usd(s.options.convexity_usd)} + volatility {usd(s.options.vega_usd)} (full reprice).
              </p>
            ) : null}
          </div>

          <div>
            <h4 className="mb-2 text-sm font-medium">P&L by holding</h4>
            <ul className="max-h-[260px] space-y-0.5 overflow-y-auto pr-1">
              {holdings.map((h) => {
                const max = Math.max(...holdings.map((x) => Math.abs(x.pnl_usd)), 1);
                return (
                  <li key={h.ticker}>
                    <button
                      type="button"
                      onClick={() => onHolding(h.ticker)}
                      aria-pressed={holding === h.ticker}
                      className={`grid w-full grid-cols-[4.5rem_1fr_5.5rem_4rem] items-center gap-2 rounded px-1.5 py-1 text-left text-xs ${
                        holding === h.ticker ? "bg-muted" : "hover:bg-muted/50"
                      }`}
                    >
                      <span className="font-mono font-medium">
                        {h.ticker}
                        {h.source !== "own" ? <span className="ml-1 text-[9px] uppercase text-warning">proxy</span> : null}
                      </span>
                      <span className="relative h-3">
                        <span
                          className="absolute inset-y-0 left-0 rounded-sm"
                          style={{ width: `${(Math.abs(h.pnl_usd) / max) * 100}%`, backgroundColor: h.pnl_usd < 0 ? LOSS : GAIN }}
                        />
                      </span>
                      <span className="text-right font-mono tabular-nums">{usd(h.pnl_usd)}</span>
                      <span className="text-right font-mono tabular-nums text-muted-foreground">{signedPct(h.move_pct, 0)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <h4 className="mb-1 text-sm font-medium">If the shock were smaller or larger</h4>
            <p className="mb-2 text-xs text-muted-foreground">
              {hasOptions
                ? "The solid line reprices options at every size; the dashed line is the straight-line (delta-only) estimate. The gap is convexity."
                : "P&L at 0.25× to 2× this shock."}
            </p>
            <Ladder s={s} showLinear={hasOptions} />
          </div>
          <div>
            <h4 className="mb-1 text-sm font-medium">Margin used at each shock size</h4>
            <p className="mb-2 text-xs text-muted-foreground">
              Requirement ÷ equity under a flat {Math.round(data.maintenance_requirement * 100)}% maintenance
              rule. 100% is the margin-call line.
            </p>
            <MarginLadder s={s} />
          </div>
        </div>

        {s.path ? <EpisodePath s={s} /> : null}
        {s.realised ? (
          <p className="rounded-md border border-border px-3 py-2 text-xs text-muted-foreground" data-testid="stress-realised-check">
            Cross-check: the holdings that already existed then ({pct(s.realised.coverage, 0)} of the book today)
            actually returned <span className="font-mono text-foreground">{signedPct(s.realised.return_pct)}</span> over this
            window. The model, using today&apos;s loadings, gives{" "}
            <span className="font-mono text-foreground">{signedPct(s.realised.model_return_pct)}</span> for the same holdings.
            The difference is model error plus how those companies have changed since.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Ladder({ s, showLinear }: { s: StressScenario; showLinear: boolean }) {
  const rows = s.ladder.map((l) => ({ x: `${l.multiple}×`, full: l.pnl_usd, linear: l.linear_pnl_usd }));
  return (
    <div style={{ width: "100%", height: 220 }} role="img" aria-label="Profit and loss at different shock sizes">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tickFormatter={usd} tick={{ fontSize: 11, fill: AXIS }} width={64} tickLine={false} axisLine={false} />
          <ReferenceLine y={0} stroke={AXIS} />
          <Tooltip
            content={({ active, payload, label }) => {
              const row = active ? (payload?.[0]?.payload as (typeof rows)[number] | undefined) : undefined;
              if (!row) return null;
              const out: [string, string][] = [[`${label} shock`, usd(row.full)]];
              if (showLinear) out.push(["Straight-line", usd(row.linear)]);
              return <Tip rows={out} />;
            }}
          />
          {showLinear ? (
            <Line dataKey="linear" stroke={AXIS} strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
          ) : null}
          <Line dataKey="full" stroke={INK} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function MarginLadder({ s }: { s: StressScenario }) {
  const rows = s.ladder
    .filter((l) => l.margin_utilisation != null)
    .map((l) => ({ x: `${l.multiple}×`, u: l.margin_utilisation as number, breach: l.breach }));
  if (!rows.length) return <p className="text-sm text-muted-foreground">Equity would be wiped out on this path.</p>;
  return (
    <div style={{ width: "100%", height: 220 }} role="img" aria-label="Margin utilisation at different shock sizes">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="x" tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis tickFormatter={(v: number) => pct(v, 0)} tick={{ fontSize: 11, fill: AXIS }} width={48} tickLine={false} axisLine={false} />
          <ReferenceLine y={1} stroke={LOSS} strokeDasharray="4 4" label={{ value: "margin call", fontSize: 10, fill: AXIS, position: "insideTopRight" }} />
          <Tooltip
            cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
            content={({ active, payload, label }) => {
              const row = active ? (payload?.[0]?.payload as (typeof rows)[number] | undefined) : undefined;
              return row ? <Tip rows={[[`${label} shock`, pct(row.u, 0)]]} /> : null;
            }}
          />
          <Bar dataKey="u" radius={[2, 2, 0, 0]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.x} fill={r.breach ? LOSS : INK} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function EpisodePath({ s }: { s: StressScenario }) {
  const path = s.path ?? [];
  const [view, setView] = useState<"equity" | "drawdown" | "margin">("equity");
  const series = path
    .map((p) => ({
      date: p.date,
      value: view === "equity" ? p.equity : view === "drawdown" ? p.drawdown : p.margin_utilisation,
    }))
    .filter((p): p is { date: string; value: number } => p.value != null);
  return (
    <div data-testid="stress-episode-path">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">Day by day through the episode</h4>
        <Seg
          label="Series"
          value={view}
          options={[
            { value: "equity", label: "Equity" },
            { value: "drawdown", label: "Drawdown" },
            { value: "margin", label: "Margin used" },
          ]}
          onChange={setView}
        />
      </div>
      <TimeSeriesChart
        data={series}
        variant={view === "drawdown" ? "area" : "line"}
        color={view === "drawdown" ? LOSS : INK}
        height={220}
        valueFormatter={view === "equity" ? usd : (v) => pct(v, 0)}
        ariaLabel={`Modelled ${view} through ${s.label}`}
      />
      <p className="mt-1 text-xs text-muted-foreground">
        Modelled from the factors&apos; actual daily moves and today&apos;s stock loadings. Option positions are
        not carried along this path.
      </p>
    </div>
  );
}

// ── your own scenario ────────────────────────────────────────────────

function CustomScenario({
  data,
  active,
  onApply,
}: {
  data: FactorStress;
  active: FactorStressParams["custom_shocks"];
  onApply: (s: FactorStressParams["custom_shocks"]) => void;
}) {
  const [raw, setRaw] = useState<Partial<Record<FactorId, string>>>({});
  const [error, setError] = useState<string | null>(null);

  function apply() {
    const out: Partial<Record<FactorId, number>> = {};
    for (const f of FACTOR_IDS) {
      const text = (raw[f] ?? "").trim();
      if (!text) continue;
      const n = Number(text);
      if (!Number.isFinite(n) || (f === "vol" && n <= 0)) {
        setError(`${SHORT[f]}: enter a number${f === "vol" ? " above 0 (2 = VIX doubles)" : ""}.`);
        return;
      }
      const shock = inputToShock(f, n);
      const limit = f === "vol" ? 2.5 : 0.9;
      if (Math.abs(shock) > limit) {
        setError(`${SHORT[f]}: that move is outside the supported range.`);
        return;
      }
      out[f] = shock;
    }
    if (!Object.keys(out).length) {
      setError("Enter a move for at least one factor.");
      return;
    }
    setError(null);
    onApply(out);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Build your own scenario</CardTitle>
        <CardDescription>
          Enter a move for any factors. Leave the others blank and they follow from the ones you set
          (or stay flat, per the control at the top).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          {FACTOR_IDS.map((f) => {
            const spec = data.factors.find((x) => x.id === f);
            return (
              <label key={f} className="space-y-1 text-xs">
                <span className="text-muted-foreground">
                  {SHORT[f]} ({INPUT_HINT[f]})
                </span>
                <input
                  inputMode="decimal"
                  disabled={!spec?.available}
                  value={raw[f] ?? ""}
                  onChange={(e) => setRaw((r) => ({ ...r, [f]: e.target.value }))}
                  placeholder={f === "vol" ? "2" : f === "rates" ? "+100" : "-10"}
                  title={spec?.unit}
                  aria-label={`${SHORT[f]} move in ${INPUT_HINT[f]}`}
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 font-mono text-sm text-foreground disabled:opacity-50"
                />
              </label>
            );
          })}
        </div>
        {error ? <p className="text-xs text-destructive" role="alert">{error}</p> : null}
        <div className="flex gap-2">
          <Button onClick={apply}>Run my scenario</Button>
          {active ? (
            <Button
              variant="outline"
              onClick={() => {
                setRaw({});
                onApply(null);
              }}
            >
              Remove it
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

// ── distribution ─────────────────────────────────────────────────────

function Distribution({ data, regime }: { data: FactorStress; regime: Regime }) {
  const d = data.distribution[regime];
  const t95 = d.tails.find((t) => Math.abs(t.level - 0.95) < 1e-9);
  const t99 = d.tails.find((t) => Math.abs(t.level - 0.99) < 1e-9);
  const rows = d.histogram.map((b) => ({ mid: (b.lo + b.hi) / 2, p: b.p, lo: b.lo, hi: b.hi }));
  return (
    <>
      <div style={{ width: "100%", height: 260 }} role="img" aria-label={`Simulated ${regime} loss distribution`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 16, right: 8, left: 0, bottom: 0 }} barCategoryGap={1}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="mid"
              type="number"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) => pct(v, 0)}
              tick={{ fontSize: 11, fill: AXIS }}
              tickLine={false}
              axisLine={{ stroke: GRID }}
            />
            <YAxis tickFormatter={(v: number) => pct(v, 0)} tick={{ fontSize: 11, fill: AXIS }} width={40} tickLine={false} axisLine={false} />
            <Tooltip
              cursor={{ fill: "hsl(var(--muted) / 0.4)" }}
              content={({ active, payload }) => {
                const row = active ? (payload?.[0]?.payload as (typeof rows)[number] | undefined) : undefined;
                return row ? (
                  <Tip rows={[["Outcome", `${signedPct(row.lo)} to ${signedPct(row.hi)}`], ["Probability", pct(row.p)]]} />
                ) : null;
              }}
            />
            {t95 ? <ReferenceLine x={-t95.var} stroke={AXIS} strokeDasharray="4 4" label={{ value: "VaR 95", fontSize: 10, fill: AXIS, position: "top" }} /> : null}
            {t99 ? <ReferenceLine x={-t99.var} stroke={LOSS} strokeDasharray="4 4" label={{ value: "VaR 99", fontSize: 10, fill: AXIS, position: "top" }} /> : null}
            <Bar dataKey="p" isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.mid} fill={t95 && r.hi <= -t95.var ? LOSS : INK} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-left text-sm" data-testid="stress-tail-table">
          <thead className="text-xs text-muted-foreground">
            <tr>
              <th className="py-1 pr-3 font-medium">Confidence</th>
              <th className="py-1 pr-3 font-medium">VaR (loss not exceeded)</th>
              <th className="py-1 font-medium">CVaR (average loss beyond it)</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums">
            {d.tails.map((t) => (
              <tr key={t.level} className="border-t border-border">
                <td className="py-1.5 pr-3">{Math.round(t.level * 100)}%</td>
                <td className="py-1.5 pr-3">
                  {pct(t.var)}
                  {t.var_se != null ? <span className="text-muted-foreground"> ± {pct(t.var_se, 2)}</span> : null}
                </td>
                <td className="py-1.5">
                  {pct(t.cvar)}
                  {t.cvar_se != null ? <span className="text-muted-foreground"> ± {pct(t.cvar_se, 2)}</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Losses are a share of net equity over {data.horizon_weeks} week{data.horizon_weeks > 1 ? "s" : ""}. The ± is
        simulation noise only.
        {d.prob_margin_call != null
          ? ` Simulated chance of reaching the margin-call line: ${pct(d.prob_margin_call, d.prob_margin_call < 0.01 ? 2 : 1)}.`
          : ""}
      </p>
    </>
  );
}

// ── exposure heatmap ─────────────────────────────────────────────────

function ExposureHeatmap({
  data,
  holding,
  onHolding,
}: {
  data: FactorStress;
  holding: string | null;
  onHolding: (t: string) => void;
}) {
  const rows = data.exposures.slice(0, 25);
  const scale: Record<string, number> = {};
  for (const f of FACTOR_IDS) scale[f] = Math.max(...rows.map((r) => Math.abs(r.betas[f] ?? 0)), 1e-9);
  const sel = rows.find((r) => r.ticker === holding);
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-max min-w-full border-separate border-spacing-px font-mono text-[11px] tabular-nums">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-1 py-1 text-left font-medium">Holding</th>
              <th className="px-1 py-1 text-right font-medium">Weight</th>
              {FACTOR_IDS.map((f) => (
                <th key={f} className="px-1 py-1 text-center font-medium">
                  {SHORT[f]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.ticker}
                onClick={() => onHolding(r.ticker)}
                aria-selected={holding === r.ticker}
                className={`cursor-pointer ${holding === r.ticker ? "outline outline-1 outline-primary" : ""}`}
              >
                <td className="px-1 py-1 text-left font-medium text-foreground">
                  <button type="button" className="text-left" aria-label={`Inspect ${r.ticker}`}>
                    {r.ticker}
                  </button>
                  {r.source !== "own" ? <span className="ml-1 text-[9px] uppercase text-warning">proxy</span> : null}
                </td>
                <td className="px-1 py-1 text-right text-muted-foreground">{pct(r.weight, 0)}</td>
                {FACTOR_IDS.map((f) => {
                  const b = r.betas[f] ?? 0;
                  const t = r.t_stats[f];
                  const weak = t == null || Math.abs(t) < 2;
                  const a = Math.min(0.75, 0.08 + 0.67 * (Math.abs(b) / scale[f]));
                  return (
                    <td
                      key={f}
                      title={`${r.ticker} · ${SHORT[f]} beta ${b.toFixed(2)}${t == null ? "" : ` (t = ${t.toFixed(1)})`}`}
                      className={`h-7 w-14 rounded-sm text-center ${weak ? "text-muted-foreground/70" : "text-foreground"}`}
                      style={{
                        backgroundColor: weak
                          ? "hsl(var(--muted) / 0.5)"
                          : `hsl(var(${b >= 0 ? "--destructive" : "--primary"}) / ${a.toFixed(2)})`,
                      }}
                    >
                      {b.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-muted-foreground">
        Red = rises and falls with the factor · blue = moves against it. Shading is relative within each column.
        {data.exposures.length > rows.length ? ` Showing the ${rows.length} largest of ${data.exposures.length} holdings.` : ""}
      </p>
      {sel ? (
        <div className="rounded-md border border-border px-3 py-2 text-xs" data-testid="stress-holding-detail">
          <p className="font-medium text-foreground">
            {sel.ticker} — {usd(sel.value_usd)} ({pct(sel.weight)} of the stock book)
          </p>
          <p className="mt-1 text-muted-foreground">
            {sel.source === "own"
              ? `Loadings from its own ${sel.n_obs} weeks of returns.`
              : `Too little history of its own: using ${sel.source.replace("sector_proxy:", "")} as a stand-in (${sel.n_obs} weeks).`}{" "}
            The seven factors explain {pct(sel.r2, 0)} of its weekly moves; the rest is single-name risk of about{" "}
            {pct(sel.resid_vol_weekly)} a week.
            {sel.unstable ? " The factors were too correlated in this window for these loadings to be reliable." : ""}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function FactorCorr({ matrix }: { matrix: number[][] }) {
  return (
    <div className="space-y-1.5">
      <div className="overflow-x-auto">
        <div
          role="table"
          aria-label="Correlation between the seven factors"
          className="grid w-max gap-px font-mono text-[11px] tabular-nums"
          style={{ gridTemplateColumns: `3.6rem repeat(${FACTOR_IDS.length}, 3rem)` }}
        >
          <div />
          {FACTOR_IDS.map((f) => (
            <div key={f} className="py-1 text-center text-muted-foreground">
              {SHORT[f]}
            </div>
          ))}
          {FACTOR_IDS.map((r, i) => (
            <FactorCorrRow key={r} r={r} row={matrix[i] ?? []} i={i} />
          ))}
        </div>
      </div>
      <p className="text-[11px] text-muted-foreground">Red = move together · blue = move opposite.</p>
    </div>
  );
}

function FactorCorrRow({ r, row, i }: { r: string; row: number[]; i: number }) {
  return (
    <>
      <div className="py-1 pr-1 text-right text-muted-foreground">{SHORT[r]}</div>
      {FACTOR_IDS.map((c, j) => {
        const v = row[j] ?? 0;
        const diag = i === j;
        return (
          <div
            key={c}
            title={diag ? undefined : `${SHORT[r]} × ${SHORT[c]} · ρ = ${v.toFixed(2)}`}
            className={`flex h-8 items-center justify-center rounded-sm ${diag ? "bg-muted text-muted-foreground/60" : "text-foreground"}`}
            style={
              diag
                ? undefined
                : { backgroundColor: `hsl(var(${v >= 0 ? "--destructive" : "--primary"}) / ${(0.06 + 0.64 * Math.abs(v)).toFixed(2)})` }
            }
          >
            {diag ? "1.0" : v.toFixed(2)}
          </div>
        );
      })}
    </>
  );
}

function Decomposition({ data, regime }: { data: FactorStress; regime: Regime }) {
  const d = data.decomposition[regime];
  const rows = [
    ...FACTOR_IDS.map((f) => ({ label: SHORT[f], v: d.factor_share[f] ?? 0 })),
    { label: "Single-name", v: d.idio_share },
  ];
  const max = Math.max(...rows.map((r) => Math.abs(r.v)), 0.01);
  return (
    <>
      <ul className="space-y-1" aria-label="Share of volatility by source">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[6rem_1fr_3.5rem] items-center gap-3 text-sm" title={`${r.label}: ${signedPct(r.v)}`}>
            <span className="text-muted-foreground">{r.label}</span>
            <span className="relative h-4">
              <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
              <span
                className="absolute inset-y-0.5 rounded-sm"
                style={{
                  left: r.v >= 0 ? "50%" : `${50 - (Math.abs(r.v) / max) * 50}%`,
                  width: `${(Math.abs(r.v) / max) * 50}%`,
                  backgroundColor: r.v >= 0 ? INK : GAIN,
                }}
              />
            </span>
            <span className="text-right font-mono tabular-nums">{signedPct(r.v, 0)}</span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Modelled weekly volatility of the stock book in this regime: {pct(d.weekly_vol)}. Largest position:{" "}
        {data.concentration.top_weight == null ? "n/a" : pct(data.concentration.top_weight, 0)}.
      </p>
    </>
  );
}

// ── states ───────────────────────────────────────────────────────────

function LabSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" data-testid="stress-lab-loading">
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-72 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}

function LabError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const code = error instanceof ApiError ? error.code : null;
  const message =
    code === "no_active_portfolio"
      ? "Add holdings to a portfolio first, then come back to stress it."
      : code === "no_modelled_holdings"
        ? "None of your holdings has a year of price history yet, so factor loadings can't be estimated."
        : code === "no_factor_data" || code === "no_market_data"
          ? "Market data is unavailable right now. Try again in a minute."
          : "The stress test hit a snag. Please try again.";
  return (
    <div className="space-y-3 rounded-lg border border-border bg-card px-4 py-4 text-sm" role="alert">
      <p className="font-medium text-foreground">Couldn&apos;t run the stress test</p>
      <p className="text-muted-foreground">{message}</p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
