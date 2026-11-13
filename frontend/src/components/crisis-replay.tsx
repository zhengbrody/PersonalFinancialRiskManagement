"use client";

/**
 * Crisis replay — today's stock book placed at the start of a past crisis and
 * held. Every figure comes from `POST /risk/crisis_replay`.
 *
 * The one thing this panel must never blur: a holding's path is either its own
 * observed prices, a reconstruction from factor loadings, or unavailable. Each
 * row says which, and the coverage bar shows the split before any number.
 */

import { useState } from "react";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Kpi } from "@/components/ui/kpi";
import { Skeleton } from "@/components/ui/skeleton";
import { AXIS, GAIN, GRID, INK, LOSS, SHORT, Seg, Tip, dayTick, pct, signedPct } from "@/components/stress-shared";
import { ApiError } from "@/lib/api";
import { useCrisisReplay, type CrisisReplay, type ReplayEpisode } from "@/lib/crisis-replay";
import { usePortfolioContext } from "@/lib/portfolio-context";

const RECON = "hsl(var(--warning))";
const MUTED = "hsl(var(--muted-foreground) / 0.45)";

const KIND_LABEL = { observed: "Observed", reconstructed: "Reconstructed", unavailable: "No data" } as const;
const KIND_TONE = { observed: "success", reconstructed: "warning", unavailable: "neutral" } as const;

function sourceText(source: string | null): string {
  if (!source) return "";
  if (source === "own") return "from its own recent loadings";
  if (source.startsWith("sector_proxy:")) return `from ${source.slice(13)} (sector stand-in)`;
  return source;
}

export function CrisisReplayPanel() {
  const { activePortfolioId } = usePortfolioContext();
  const q = useCrisisReplay(activePortfolioId);
  const [selectedId, setSelectedId] = useState<string>("covid_2020");

  if (q.isPending) {
    return (
      <div className="space-y-6" aria-busy="true" data-testid="crisis-replay-loading">
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-80 w-full" />
      </div>
    );
  }
  if (q.isError || !q.data) return <ReplayError error={q.error} onRetry={() => q.refetch()} />;

  const data = q.data;
  const episode = data.episodes.find((e) => e.id === selectedId) ?? data.episodes[data.episodes.length - 1];

  return (
    <div className="space-y-6" data-testid="crisis-replay">
      <Card>
        <CardHeader>
          <CardTitle>Crisis replay</CardTitle>
          <CardDescription>
            Your current stock holdings and weights, placed at the first day of each past crisis and held.
            Prices as of {data.as_of}. Select an episode.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.warnings.length ? (
            <ul className="space-y-1 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
              {data.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : null}
          <EpisodeTable data={data} selectedId={episode.id} onSelect={setSelectedId} />
        </CardContent>
      </Card>

      <EpisodeDetail e={episode} benchmark={data.benchmark} />

      <details className="rounded-lg border border-border bg-card px-4 py-3 text-sm">
        <summary className="cursor-pointer font-medium">How the replay is built</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-muted-foreground">
          {data.method.map((m) => (
            <li key={m}>{m}</li>
          ))}
          <li>{data.data_source}</li>
          <li>Model version {data.model_version}. Educational analysis, not investment advice.</li>
        </ul>
      </details>
    </div>
  );
}

function EpisodeTable({
  data,
  selectedId,
  onSelect,
}: {
  data: CrisisReplay;
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th className="py-1.5 pr-3 font-medium">Episode</th>
            <th className="py-1.5 pr-3 text-right font-medium">Your book</th>
            <th className="py-1.5 pr-3 text-right font-medium">{data.benchmark}</th>
            <th className="py-1.5 pr-3 text-right font-medium">Worst drawdown</th>
            <th className="py-1.5 font-medium">How much is observed</th>
          </tr>
        </thead>
        <tbody>
          {data.episodes.map((e) => {
            const on = e.id === selectedId;
            return (
              <tr
                key={e.id}
                onClick={() => onSelect(e.id)}
                aria-selected={on}
                className={`cursor-pointer border-t border-border ${on ? "bg-muted" : "hover:bg-muted/50"}`}
              >
                <td className="py-2 pr-3">
                  <button type="button" className="text-left font-medium" aria-pressed={on}>
                    {e.label}
                  </button>
                  <div className="text-xs text-muted-foreground">
                    {e.start} to {e.end}
                  </div>
                </td>
                <td className={`py-2 pr-3 text-right font-mono tabular-nums ${e.portfolio.return_pct < 0 ? "text-destructive" : "text-success"}`}>
                  {signedPct(e.portfolio.return_pct)}
                </td>
                <td className="py-2 pr-3 text-right font-mono tabular-nums text-muted-foreground">
                  {signedPct(e.benchmark.return_pct)}
                </td>
                <td className="py-2 pr-3 text-right font-mono tabular-nums">{signedPct(e.portfolio.max_drawdown)}</td>
                <td className="py-2">
                  <CoverageBar c={e.coverage} compact />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CoverageBar({ c, compact = false }: { c: ReplayEpisode["coverage"]; compact?: boolean }) {
  const parts = [
    { key: "observed", v: c.observed_weight, color: GAIN, label: "observed prices" },
    { key: "reconstructed", v: c.reconstructed_weight, color: RECON, label: "reconstructed" },
    { key: "unavailable", v: c.unavailable_weight, color: MUTED, label: "no data" },
  ];
  const title = parts.map((p) => `${pct(p.v, 0)} ${p.label}`).join(" · ");
  return (
    <div title={title} aria-label={title} role="img">
      <div className={`flex ${compact ? "h-2 w-40" : "h-3 w-full"} gap-0.5 overflow-hidden rounded-sm`}>
        {parts
          .filter((p) => p.v > 0.0005)
          .map((p) => (
            <span key={p.key} style={{ width: `${p.v * 100}%`, backgroundColor: p.color }} />
          ))}
      </div>
      {compact ? (
        <span className="text-[11px] text-muted-foreground">{pct(c.observed_weight, 0)} observed</span>
      ) : (
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {parts.map((p) => (
            <span key={p.key} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: p.color }} />
              {pct(p.v, 0)} {p.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function EpisodeDetail({ e, benchmark }: { e: ReplayEpisode; benchmark: string }) {
  const [view, setView] = useState<"value" | "drawdown">("value");
  const [kind, setKind] = useState<"all" | "observed" | "reconstructed">("all");
  const rows = e.path.map((p) => ({
    date: p.date,
    portfolio: view === "value" ? p.portfolio - 1 : p.drawdown,
    benchmark: view === "value" ? p.benchmark - 1 : null,
  }));
  const holdings = e.holdings.filter((h) => kind === "all" || h.kind === kind);
  const maxContribution = Math.max(...e.holdings.map((h) => Math.abs(h.contribution_pct ?? 0)), 1e-9);
  const factorRows = [
    ...e.by_factor
      .filter((f) => !e.factors_unavailable.includes(f.factor))
      .map((f) => ({ label: SHORT[f.factor] ?? f.factor, v: f.contribution_pct })),
    { label: "Not explained", v: e.unexplained_pct },
  ];
  const maxFactor = Math.max(...factorRows.map((r) => Math.abs(r.v)), 1e-9);
  const c = e.correlation;

  return (
    <Card data-testid="crisis-replay-detail">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {e.label}
          <Badge tone={e.portfolio.return_pct < 0 ? "danger" : "success"}>{signedPct(e.portfolio.return_pct)}</Badge>
        </CardTitle>
        <CardDescription>
          {e.start} to {e.end} · {e.trading_days} trading days
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div>
          <h4 className="mb-2 text-sm font-medium">Where these numbers come from</h4>
          <CoverageBar c={e.coverage} />
          {e.coverage.reconstructed_weight > 0.0005 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Reconstructed holdings did not trade in this period. Their path is an estimate from how they
              move with the market today, applied to what the market did then.
            </p>
          ) : null}
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Kpi label="Your book" value={signedPct(e.portfolio.return_pct)} tone={e.portfolio.return_pct < 0 ? "bad" : "ok"} />
          <Kpi label={`${benchmark} (S&P 500)`} value={signedPct(e.benchmark.return_pct)} />
          <Kpi
            label="Versus benchmark"
            value={signedPct(e.excess_return_pct)}
            tone={e.excess_return_pct < 0 ? "bad" : "ok"}
          />
          <Kpi label="Worst drawdown" value={signedPct(e.portfolio.max_drawdown)} tone="bad" />
        </div>

        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-medium">
              {view === "value" ? `Your book and ${benchmark} through the episode` : "Drawdown from the running peak"}
            </h4>
            <Seg
              label="Show"
              value={view}
              options={[
                { value: "value", label: "Return" },
                { value: "drawdown", label: "Drawdown" },
              ]}
              onChange={setView}
            />
          </div>
          <div style={{ width: "100%", height: 260 }} role="img" aria-label={`${view === "value" ? "Return" : "Drawdown"} through ${e.label}`}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" tickFormatter={dayTick} minTickGap={48} tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={{ stroke: GRID }} />
                <YAxis tickFormatter={(v: number) => pct(v, 0)} tick={{ fontSize: 11, fill: AXIS }} width={48} tickLine={false} axisLine={false} />
                <ReferenceLine y={0} stroke={AXIS} />
                <Tooltip
                  content={({ active, payload, label }) => {
                    const row = active ? (payload?.[0]?.payload as (typeof rows)[number] | undefined) : undefined;
                    if (!row) return null;
                    const out: [string, string][] = [[dayTick(String(label)), ""], ["Your book", signedPct(row.portfolio)]];
                    if (row.benchmark != null) out.push([benchmark, signedPct(row.benchmark)]);
                    return <Tip rows={out} />;
                  }}
                />
                {view === "value" ? (
                  <Line dataKey="benchmark" stroke={AXIS} strokeDasharray="4 4" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                ) : null}
                <Line dataKey="portfolio" stroke={view === "value" ? INK : LOSS} strokeWidth={2} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {view === "value" ? (
            <p className="mt-1 text-xs text-muted-foreground">Solid: your book. Dashed: {benchmark}.</p>
          ) : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-3" data-testid="crisis-peak-stress">
          <Kpi label="Lowest point" value={e.portfolio.trough_date} />
          <Kpi
            label="Worst single day"
            value={e.portfolio.worst_day ? `${signedPct(e.portfolio.worst_day.return_pct)} · ${e.portfolio.worst_day.date}` : "n/a"}
          />
          <Kpi
            label="Worst five days"
            value={e.portfolio.worst_week ? `${signedPct(e.portfolio.worst_week.return_pct)} · from ${e.portfolio.worst_week.start}` : "n/a"}
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <div>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-medium">By holding</h4>
              <Seg
                label="Filter"
                value={kind}
                options={[
                  { value: "all", label: "All" },
                  { value: "observed", label: "Observed" },
                  { value: "reconstructed", label: "Reconstructed" },
                ]}
                onChange={setKind}
              />
            </div>
            <ul className="space-y-1">
              {holdings.map((h) => (
                <li key={h.ticker} className="rounded px-1.5 py-1 text-xs" data-testid={`replay-holding-${h.ticker}`}>
                  <div className="grid grid-cols-[4.5rem_1fr_4rem_4rem] items-center gap-2">
                    <span className="font-mono font-medium">{h.ticker}</span>
                    <span className="relative h-3">
                      {h.contribution_pct != null ? (
                        <span
                          className="absolute inset-y-0 left-0 rounded-sm"
                          style={{
                            width: `${(Math.abs(h.contribution_pct) / maxContribution) * 100}%`,
                            backgroundColor: h.contribution_pct < 0 ? LOSS : GAIN,
                          }}
                        />
                      ) : null}
                    </span>
                    <span className="text-right font-mono tabular-nums">
                      {h.contribution_pct == null ? "—" : signedPct(h.contribution_pct)}
                    </span>
                    <span className="text-right font-mono tabular-nums text-muted-foreground">
                      {h.return_pct == null ? "—" : signedPct(h.return_pct, 0)}
                    </span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <Badge tone={KIND_TONE[h.kind]}>{KIND_LABEL[h.kind]}</Badge>
                    <span>{pct(h.weight, 0)} of the book</span>
                    {h.kind === "reconstructed" ? (
                      <span>
                        · estimated {sourceText(h.loadings_source)}
                        {h.fit_r2 != null ? `, which explain ${pct(h.fit_r2, 0)} of its moves` : ""}
                      </span>
                    ) : null}
                    {h.kind === "reconstructed" && h.fit_r2 != null && h.fit_r2 < 0.3 ? (
                      <Badge tone="warning">rough estimate</Badge>
                    ) : null}
                    {h.kind === "unavailable" ? <span>· no prices then and no loadings; left out</span> : null}
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-muted-foreground">
              Bar and first number: contribution to the book&apos;s return. Second number: the holding&apos;s own return.
            </p>
          </div>

          <div>
            <h4 className="mb-2 text-sm font-medium">By factor</h4>
            <ul className="space-y-1" aria-label="Return explained by each factor">
              {factorRows.map((r) => (
                <li key={r.label} className="grid grid-cols-[6.5rem_1fr_4rem] items-center gap-3 text-sm" title={`${r.label}: ${signedPct(r.v)}`}>
                  <span className="text-muted-foreground">{r.label}</span>
                  <span className="relative h-4">
                    <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
                    <span
                      className="absolute inset-y-0.5 rounded-sm"
                      style={{
                        left: r.v >= 0 ? "50%" : `${50 - (Math.abs(r.v) / maxFactor) * 50}%`,
                        width: `${(Math.abs(r.v) / maxFactor) * 50}%`,
                        backgroundColor: r.label === "Not explained" ? MUTED : r.v < 0 ? LOSS : GAIN,
                      }}
                    />
                  </span>
                  <span className="text-right font-mono tabular-nums">{signedPct(r.v)}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-muted-foreground">
              The factor model applied to what the factors actually did. &quot;Not explained&quot; is the part of
              the replayed return the seven factors do not account for.
              {e.factors_unavailable.length
                ? ` No data then for: ${e.factors_unavailable.map((f) => SHORT[f] ?? f).join(", ")}.`
                : ""}
            </p>

            <h4 className="mb-2 mt-5 text-sm font-medium">How correlations changed</h4>
            <table className="w-full text-left text-sm" data-testid="crisis-correlation">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 pr-3 font-medium" />
                  <th className="py-1 pr-3 text-right font-medium">In the episode</th>
                  <th className="py-1 text-right font-medium">Last 12 months</th>
                </tr>
              </thead>
              <tbody className="font-mono tabular-nums">
                <tr className="border-t border-border">
                  <td className="py-1.5 pr-3 font-sans text-muted-foreground">Between your holdings</td>
                  <td className="py-1.5 pr-3 text-right">{c.episode_avg_pairwise == null ? "n/a" : c.episode_avg_pairwise.toFixed(2)}</td>
                  <td className="py-1.5 text-right">{c.recent_avg_pairwise == null ? "n/a" : c.recent_avg_pairwise.toFixed(2)}</td>
                </tr>
                <tr className="border-t border-border">
                  <td className="py-1.5 pr-3 font-sans text-muted-foreground">Stocks and Treasuries</td>
                  <td className="py-1.5 pr-3 text-right">{c.stock_bond_episode == null ? "n/a" : c.stock_bond_episode.toFixed(2)}</td>
                  <td className="py-1.5 text-right">{c.stock_bond_recent == null ? "n/a" : c.stock_bond_recent.toFixed(2)}</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-2 text-[11px] text-muted-foreground">
              {c.assets_compared >= 2
                ? `Average correlation across the ${c.assets_compared} holdings with their own prices in the episode. Higher means they fell together.`
                : "Fewer than two holdings have their own prices in this episode, so their correlation cannot be measured."}
              {e.beta_to_benchmark != null ? ` Beta to ${benchmark} in the episode: ${e.beta_to_benchmark.toFixed(2)}.` : ""}
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ReplayError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const code = error instanceof ApiError ? error.code : null;
  const message =
    code === "no_active_portfolio" || code === "no_priced_holdings"
      ? "Add stock or fund holdings to a portfolio first, then come back to replay it."
      : code === "no_factor_data" || code === "no_market_data"
        ? "Market data is unavailable right now. Try again in a minute."
        : "The replay hit a snag. Please try again.";
  return (
    <div className="space-y-3 rounded-lg border border-border bg-card px-4 py-4 text-sm" role="alert">
      <p className="font-medium text-foreground">Couldn&apos;t run the crisis replay</p>
      <p className="text-muted-foreground">{message}</p>
      <Button variant="outline" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
