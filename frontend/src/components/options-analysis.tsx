"use client";

/**
 * Options risk cockpit — the desk-style view of an option book on /risk.
 * Everything is deterministic backend math (POST /options/analyze + /scenarios);
 * the LLM is not involved. Renders nothing when the book has no options, so it's
 * safe to drop onto /risk unconditionally.
 *
 * Layout: exposure summary (net/gross Greeks · notional · collateral) → risk
 * flags → stress grid (underlying × IV reprice heatmap + top movers) → expiry
 * ladder + moneyness → per-contract cards (Greeks · max loss/gain · payoff).
 */

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
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
import { TickerBadge } from "@/components/ui/ticker-badge";
import { ReportExportButton } from "@/components/report-export-button";
import {
  type OptionAnalytics,
  type OptionContract,
  type OptionExplain,
  type OptionExposure,
  type OptionScenarioGrid,
  type OptionStrategy,
  useOptionAnalytics,
  useOptionExplain,
} from "@/lib/queries";

export function OptionsAnalysis({ contracts }: { contracts: OptionContract[] }) {
  const analytics = useOptionAnalytics(contracts);
  const explain = useOptionExplain(analytics.data?.exposure);

  if (contracts.length === 0) return null;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold tracking-tight">Options risk</h2>
        <div className="flex items-center gap-3">
          {analytics.data && (
            <ReportExportButton
              kind="options"
              payload={{ analysis: analytics.data }}
              label="Export options report"
            />
          )}
          <span className="text-[11px] uppercase tracking-widest text-muted-foreground">
            Black-Scholes · deterministic
          </span>
        </div>
      </div>

      {analytics.isPending ? (
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : analytics.isError ? (
        <Card>
          <CardHeader>
            <CardDescription className="text-sm text-muted-foreground">
              Couldn&apos;t price your options right now (market-data hiccup) — the
              risk report above is unaffected. Try again shortly.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : analytics.data ? (
        <>
          <OptionDiagnosis explain={explain.data} loading={explain.isPending} />
          <ExposureSummary exposure={analytics.data.exposure} asOf={analytics.data.as_of} />
          <RiskFlags exposure={analytics.data.exposure} />
          <StressGrid data={analytics.data.scenarios} loading={false} />
          <div className="grid gap-3 lg:grid-cols-2">
            <ExpiryLadder exposure={analytics.data.exposure} />
            <MoneynessBar results={analytics.data.results} />
          </div>
          <StrategyList
            strategies={analytics.data.strategies ?? []}
            results={analytics.data.results}
          />
        </>
      ) : null}
    </section>
  );
}

// ── AI diagnosis (deterministic skeleton → optional LLM rephrase) ─────────────

const SEVERITY_TONE: Record<string, string> = {
  high: "border-red-500/40 bg-red-500/5",
  elevated: "border-amber-500/40 bg-amber-500/5",
  moderate: "border-primary/30",
  low: "border-emerald-500/30 bg-emerald-500/5",
};

function OptionDiagnosis({
  explain,
  loading,
}: {
  explain: OptionExplain | undefined;
  loading: boolean;
}) {
  if (loading) return <Skeleton className="h-28" />;
  if (!explain) return null;
  return (
    <Card className={SEVERITY_TONE[explain.severity] ?? ""}>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-2 text-sm">
          <span>{explain.headline}</span>
          <Chip
            label={explain.ai_generated ? "AI" : "Auto"}
            tone={explain.ai_generated ? undefined : "muted"}
          />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {explain.summary_bullets.length > 0 && (
          <ul className="space-y-1">
            {explain.summary_bullets.map((b, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span className="mt-1 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" />
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}
        {explain.suggested_actions.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              Inspect before trading
            </p>
            {explain.suggested_actions.map((a, i) => (
              <div key={i} className="rounded-md border border-border bg-muted/30 px-3 py-1.5 text-xs">
                <span className="font-medium">{a.title}</span>
                <span className="text-muted-foreground"> — {a.next_step}</span>
              </div>
            ))}
          </div>
        )}
        <p className="text-[11px] text-muted-foreground">{explain.caveats.join(" · ")}</p>
      </CardContent>
    </Card>
  );
}

// ── exposure summary ──────────────────────────────────────────────────────────

function ExposureSummary({ exposure: e, asOf }: { exposure: OptionExposure; asOf: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Portfolio option exposure{" "}
          <span className="font-normal text-muted-foreground">
            ({e.contracts} contract{e.contracts === 1 ? "" : "s"}
            {e.short_contracts ? `, ${e.short_contracts} short` : ""} · as of {asOf})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4 lg:grid-cols-7">
        <Stat label="Net Δ" value={num(e.net_delta, 1)} hint="share-equiv" />
        <Stat label="Gross Δ" value={num(e.gross_delta, 1)} hint="two-sided" />
        <Stat
          label="Net Γ"
          value={num(e.net_gamma, 2)}
          tone={e.net_gamma < 0 ? "down" : undefined}
        />
        <Stat
          label="Θ / day"
          value={usd(e.net_theta)}
          tone={e.net_theta < 0 ? "down" : "up"}
        />
        <Stat label="ν / 1%" value={usd(e.net_vega)} />
        <Stat label="Notional" value={usd(e.option_notional)} hint="|Δ·$|" />
        <Stat
          label="Short collat."
          value={e.short_collateral_estimate ? usd(e.short_collateral_estimate) : "—"}
          hint="est."
        />
      </CardContent>
    </Card>
  );
}

// ── risk flags ────────────────────────────────────────────────────────────────

function RiskFlags({ exposure }: { exposure: OptionExposure }) {
  if (!exposure.flags.length) return null;
  const order = { high: 0, watch: 1, info: 2 } as Record<string, number>;
  const flags = [...exposure.flags].sort((a, b) => (order[a.severity] ?? 9) - (order[b.severity] ?? 9));
  return (
    <div className="space-y-1.5">
      {flags.map((f, i) => (
        <div
          key={i}
          className={`flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${
            f.severity === "high"
              ? "border-red-500/40 bg-red-500/5"
              : f.severity === "watch"
                ? "border-amber-500/40 bg-amber-500/5"
                : "border-border bg-muted/30"
          }`}
        >
          <span
            className={`mt-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
              f.severity === "high"
                ? "bg-red-500/15 text-red-600 dark:text-red-400"
                : f.severity === "watch"
                  ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                  : "bg-muted text-muted-foreground"
            }`}
          >
            {f.severity}
          </span>
          <span className="text-foreground/90">{f.detail}</span>
        </div>
      ))}
    </div>
  );
}

// ── stress grid (underlying × IV reprice) ─────────────────────────────────────

function StressGrid({
  data,
  loading,
}: {
  data: OptionScenarioGrid | undefined;
  loading: boolean;
}) {
  const [horizon, setHorizon] = useState<number | string>(0);
  const horizons = data?.horizons ?? [0, 7, 30, "expiry"];

  const { rows, cols, cell } = useMemo(() => {
    const cols = data?.underlying_shocks ?? [];
    const rows = data?.iv_shocks ?? [];
    const cell = new Map<string, number>();
    for (const c of data?.grid ?? []) {
      if (c.horizon === horizon) cell.set(`${c.underlying_shock}|${c.iv_shock}`, c.total_pnl);
    }
    return { rows, cols, cell };
  }, [data, horizon]);

  if (loading) return <Skeleton className="h-44" />;
  if (!data || data.repriced === 0) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Stress grid</CardTitle>
          <CardDescription className="text-xs">
            No contracts could be repriced (missing live price/IV). Add a market price
            or implied vol to model them.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const mags = Array.from(cell.values()).map((v) => Math.abs(v));
  const maxMag = Math.max(1, ...mags);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm">
            Stress grid{" "}
            <span className="font-normal text-muted-foreground">
              — option P&amp;L by underlying move × IV shock (full reprice)
            </span>
          </CardTitle>
          <div className="flex gap-1">
            {horizons.map((h) => (
              <button
                key={String(h)}
                type="button"
                onClick={() => setHorizon(h)}
                className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                  h === horizon
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/70"
                }`}
              >
                {h === "expiry" ? "Expiry" : h === 0 ? "Today" : `+${h}d`}
              </button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-center text-[11px] tabular-nums">
            <thead>
              <tr>
                <th className="p-1 text-left text-[10px] uppercase tracking-wide text-muted-foreground">
                  IV ↓ / Px →
                </th>
                {cols.map((u) => (
                  <th key={u} className="p-1 font-mono text-muted-foreground">
                    {u >= 0 ? "+" : ""}
                    {Math.round(u * 100)}%
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((iv) => (
                <tr key={iv}>
                  <td className="p-1 text-left font-mono text-muted-foreground">
                    {iv >= 0 ? "+" : ""}
                    {Math.round(iv * 100)}v
                  </td>
                  {cols.map((u) => {
                    const v = cell.get(`${u}|${iv}`) ?? 0;
                    const intensity = Math.min(1, Math.abs(v) / maxMag);
                    const bg =
                      v >= 0
                        ? `rgba(16,185,129,${0.12 + intensity * 0.5})`
                        : `rgba(239,68,68,${0.12 + intensity * 0.5})`;
                    return (
                      <td
                        key={u}
                        className="p-1 font-mono"
                        style={{ background: bg }}
                        title={`${u >= 0 ? "+" : ""}${Math.round(u * 100)}% spot, ${iv >= 0 ? "+" : ""}${Math.round(iv * 100)} vol`}
                      >
                        {usdShort(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data.top_positions.length > 0 && (
          <div>
            <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              Biggest movers at −20% spot · +10 vol (today)
            </p>
            <div className="space-y-1">
              {data.top_positions.map((p, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <TickerBadge ticker={p.underlying ?? "—"} />
                  <span className="font-mono text-muted-foreground">
                    {(p.quantity ?? 0) < 0 ? "−" : ""}
                    {Math.abs(p.quantity ?? 0)}× {(p.option_type ?? "").toUpperCase()} {p.strike}
                  </span>
                  <span
                    className={`ml-auto font-mono tabular-nums ${
                      p.pnl >= 0
                        ? "text-emerald-600 dark:text-emerald-400"
                        : "text-red-600 dark:text-red-400"
                    }`}
                  >
                    {usd(p.pnl)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── expiry ladder + moneyness ─────────────────────────────────────────────────

function ExpiryLadder({ exposure }: { exposure: OptionExposure }) {
  if (!exposure.expiry_ladder.length) return null;
  const maxN = Math.max(1, ...exposure.expiry_ladder.map((b) => Math.abs(b.net_notional)));
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Expiry ladder</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {exposure.expiry_ladder.map((b) => (
          <div key={b.expiry} className="flex items-center gap-2 text-xs">
            <span className="w-20 font-mono text-muted-foreground">{b.expiry}</span>
            <span className="w-8 text-right text-muted-foreground">{b.days_to_expiry}d</span>
            <div className="h-2 flex-1 overflow-hidden rounded bg-muted">
              <div
                className={`h-full ${b.net_notional >= 0 ? "bg-primary" : "bg-red-500/70"}`}
                style={{ width: `${(Math.abs(b.net_notional) / maxN) * 100}%` }}
              />
            </div>
            <span className="w-16 text-right font-mono tabular-nums">{usdShort(b.net_notional)}</span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function MoneynessBar({ results }: { results: OptionAnalytics[] }) {
  const counts = useMemo(() => {
    const c = { ITM: 0, ATM: 0, OTM: 0 } as Record<string, number>;
    for (const r of results) if (r.moneyness && c[r.moneyness] != null) c[r.moneyness] += 1;
    return c;
  }, [results]);
  const total = counts.ITM + counts.ATM + counts.OTM || 1;
  const seg = [
    { k: "ITM", v: counts.ITM, cls: "bg-emerald-500/70" },
    { k: "ATM", v: counts.ATM, cls: "bg-amber-500/70" },
    { k: "OTM", v: counts.OTM, cls: "bg-muted-foreground/40" },
  ];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Moneyness</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex h-3 overflow-hidden rounded">
          {seg.map((s) => (
            <div key={s.k} className={s.cls} style={{ width: `${(s.v / total) * 100}%` }} />
          ))}
        </div>
        <div className="flex gap-4 text-xs text-muted-foreground">
          {seg.map((s) => (
            <span key={s.k}>
              <span className="font-mono text-foreground">{s.v}</span> {s.k}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ── per-contract card ─────────────────────────────────────────────────────────

// ── strategy view (netted multi-leg) ──────────────────────────────────────────

function StrategyList({
  strategies,
  results,
}: {
  strategies: OptionStrategy[];
  results: OptionAnalytics[];
}) {
  // Fallback: if the backend didn't send strategies (older build), show per-leg.
  if (strategies.length === 0) {
    return (
      <div className="grid gap-3 md:grid-cols-2">
        {results.map((r, i) => (
          <ContractCard key={r.contract_symbol ?? `${r.underlying}-${i}`} a={r} />
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-[11px] uppercase tracking-widest text-muted-foreground">
        Your positions, grouped into strategies
      </p>
      {strategies.map((s, i) => (
        <StrategyCard key={`${s.underlying}-${s.expiry}-${i}`} s={s} />
      ))}
    </div>
  );
}

function StrategyCard({ s }: { s: OptionStrategy }) {
  const [open, setOpen] = useState(false);
  const credit = s.net_debit < 0;
  const g = s.net_greeks;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          <Chip label={s.name} tone={credit ? "up" : undefined} />
          <TickerBadge ticker={s.underlying} />
          <span className="text-muted-foreground">{shortExpiry(s.expiry)}</span>
          <span className="text-[11px] text-muted-foreground">
            {s.leg_count} leg{s.leg_count === 1 ? "" : "s"}
          </span>
          {s.net_pnl != null && (
            <span className="ml-auto">
              <Chip label={`P&L ${usd(s.net_pnl)}`} tone={s.net_pnl >= 0 ? "up" : "down"} />
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
          <Stat label={credit ? "Net credit" : "Net debit"} value={usd(Math.abs(s.net_debit))} />
          <Stat
            label="Max loss"
            value={s.max_loss == null ? "Unbounded" : usd(s.max_loss)}
            tone={s.max_loss == null ? "down" : undefined}
          />
          <Stat
            label="Max gain"
            value={s.max_gain == null ? "Unbounded" : usd(s.max_gain)}
            tone={s.max_gain == null ? "up" : undefined}
          />
          <Stat
            label="Break-even"
            value={s.break_evens.length ? s.break_evens.map((b) => usd(b)).join(" / ") : "—"}
          />
        </div>

        {(g.delta != null || g.gamma != null) && (
          <div className="grid grid-cols-4 gap-2 text-xs">
            <Stat label="Net Δ" value={num(g.delta ?? 0, 1)} />
            <Stat label="Net Γ" value={num(g.gamma ?? 0, 2)} />
            <Stat
              label="Net Θ/day"
              value={num(g.theta ?? 0, 1)}
              tone={(g.theta ?? 0) < 0 ? "down" : undefined}
            />
            <Stat label="Net ν/1%" value={num(g.vega ?? 0, 1)} />
          </div>
        )}

        {s.payoff.length > 0 && <StrategyPayoffChart s={s} />}

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="text-xs text-primary hover:underline"
          aria-expanded={open}
        >
          {open ? "Hide legs" : `Show ${s.leg_count} leg${s.leg_count === 1 ? "" : "s"}`}
        </button>
        {open && (
          <div className="grid gap-3 md:grid-cols-2">
            {s.legs.map((leg, i) => (
              <ContractCard key={leg.contract_symbol ?? `${leg.underlying}-${i}`} a={leg} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StrategyPayoffChart({ s }: { s: OptionStrategy }) {
  return (
    <PayoffLineChart
      label="Combined P&L at expiry"
      data={s.payoff}
      breakEvens={s.break_evens}
      height={130}
    />
  );
}

const SOURCE_CHIP: Record<string, { label: string; tone?: "up" | "down" | "muted" }> = {
  market: { label: "Market price", tone: "up" },
  manual: { label: "Manual mark" },
  stale_eod: { label: "Delayed / EOD", tone: "muted" },
  theoretical_fallback: { label: "Theoretical", tone: "muted" },
};

function SourceChip({ source }: { source: string | undefined }) {
  const c = source ? SOURCE_CHIP[source] : undefined;
  if (!c) return null;
  return <Chip label={c.label} tone={c.tone} />;
}

function ContractCard({ a }: { a: OptionAnalytics }) {
  const dir = a.option_type === "call" ? "CALL" : "PUT";
  const isShort = a.quantity < 0;
  const pnl = a.unrealized_pnl;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          <Chip label={isShort ? "SHORT" : "LONG"} tone={isShort ? "muted" : "up"} />
          <TickerBadge ticker={a.underlying} />
          <span className="font-mono">
            {Math.abs(a.quantity)}× {dir} {a.strike}
          </span>
          <span className="text-muted-foreground">{shortExpiry(a.expiry)}</span>
          {a.moneyness && (
            <Chip
              label={a.moneyness}
              tone={a.moneyness === "ITM" ? "up" : a.moneyness === "OTM" ? "muted" : undefined}
            />
          )}
          {a.assignment_risk && (
            <Chip label={`assign ${a.assignment_risk}`} tone="down" />
          )}
          <SourceChip source={a.source} />
          <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
            {a.days_to_expiry}d
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {a.greeks ? (
          <div className="grid grid-cols-4 gap-2 text-xs">
            <Stat label="Δ" value={num(a.greeks.delta, 3)} />
            <Stat label="Γ" value={num(a.greeks.gamma, 4)} />
            <Stat label="Θ/day" value={num(a.greeks.theta, 3)} tone={a.greeks.theta < 0 ? "down" : undefined} />
            <Stat label="ν/1%" value={num(a.greeks.vega, 3)} />
          </div>
        ) : (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            {a.warnings[0] ?? "Greeks unavailable for this contract."}
          </p>
        )}

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
          <Stat label="Spot" value={a.spot == null ? "—" : usd(a.spot)} />
          <Stat label="Mark" value={a.mark == null ? "—" : `$${a.mark.toFixed(2)}`} />
          <Stat label="IV" value={a.iv == null ? "—" : pct(a.iv)} />
          <Stat label="Mkt value" value={a.market_value == null ? "—" : usd(a.market_value)} />
          <Stat label="Max loss" value={a.max_loss == null ? "Unbounded" : usd(a.max_loss)} tone={a.max_loss == null ? "down" : undefined} />
          <Stat label="Max gain" value={a.max_gain == null ? "Unbounded" : usd(a.max_gain)} tone={a.max_gain == null ? "up" : undefined} />
          {a.break_even != null && <Stat label="Break-even" value={usd(a.break_even)} />}
          {pnl != null && <Stat label="P&L" value={usd(pnl)} tone={pnl >= 0 ? "up" : "down"} />}
        </div>

        {a.payoff.length > 0 && <PayoffChart a={a} />}
      </CardContent>
    </Card>
  );
}

function PayoffChart({ a }: { a: OptionAnalytics }) {
  return (
    <PayoffLineChart
      label="P&L at expiry"
      data={a.payoff}
      breakEvens={a.break_even != null ? [a.break_even] : []}
    />
  );
}

/**
 * Shared P&L-at-expiry line chart for a single contract or a netted strategy.
 * Data points are {price, pnl}; break-even reference lines are caller-supplied.
 */
function PayoffLineChart({
  label,
  data,
  breakEvens,
  height = 120,
}: {
  label: string;
  data: { price: number; pnl: number }[];
  breakEvens: number[];
  height?: number;
}) {
  return (
    <div>
      <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="price"
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            tickFormatter={(v: number) => `$${Math.round(v)}`}
            type="number"
            domain={["dataMin", "dataMax"]}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            tickFormatter={(v: number) =>
              Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`
            }
            width={34}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 11,
            }}
            formatter={(v) => [usd(Number(v ?? 0)), "P&L"]}
            labelFormatter={(v) => `Underlying $${Number(v).toFixed(0)}`}
          />
          <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />
          {breakEvens.map((b, i) => (
            <ReferenceLine key={i} x={b} stroke="hsl(var(--primary))" strokeDasharray="3 3" />
          ))}
          <Line type="monotone" dataKey="pnl" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── presentational helpers ────────────────────────────────────────────────────

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={`font-mono tabular-nums ${
          tone === "up"
            ? "text-emerald-600 dark:text-emerald-400"
            : tone === "down"
              ? "text-red-600 dark:text-red-400"
              : ""
        }`}
      >
        {value}
      </p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Chip({ label, tone }: { label: string; tone?: "up" | "down" | "muted" }) {
  return (
    <span
      className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
        tone === "up"
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : tone === "down"
            ? "border-red-500/40 bg-red-500/10 text-red-600 dark:text-red-400"
            : tone === "muted"
              ? "border-border bg-muted/50 text-muted-foreground"
              : "border-primary/40 bg-primary/10 text-primary"
      }`}
    >
      {label}
    </span>
  );
}

function num(v: number, dp: number): string {
  return v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function usd(v: number): string {
  const sign = v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function usdShort(v: number): string {
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (a >= 1000) return `${sign}$${(a / 1000).toFixed(1)}k`;
  return `${sign}$${a.toFixed(0)}`;
}

function pct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

function shortExpiry(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
}
