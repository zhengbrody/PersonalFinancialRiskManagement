"use client";

/**
 * Shared renderer for the active-portfolio risk report
 * (POST /api/v1/risk/report_from_active). Used by both the global `/risk`
 * page and `/portfolios/[id]/risk` so the report UI lives in one place.
 *
 * Sections: VaR/CVaR KPI tiles · factor betas · component VaR · stress test ·
 * macro betas · liquidity.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { HorizontalBarChart, type BarDatum } from "@/components/ui/bar-chart";
import { DataTable, type Column } from "@/components/ui/data-table";
import { RiskDiagnosis } from "@/components/risk-diagnosis";
import { PortfolioValueSummary } from "@/components/portfolio-value-summary";
import { BenchmarkContext } from "@/components/benchmark-context";
import { DataProvenance } from "@/components/data-provenance";
import { VarBacktest } from "@/components/var-backtest";
import { MetricTrend } from "@/components/metric-trend";
import { track } from "@/lib/analytics";
import { ApiError } from "@/lib/api";
import {
  useRiskExplain,
  useScenarios,
  useVarBacktest,
  type ComponentVarRow,
  type FactorBetaRow,
  type LiquidityRow,
  type RiskReport,
  type Scenarios,
  type StressAssetLoss,
} from "@/lib/queries";
import { explainInputFromReport } from "@/lib/risk-explain-input";

/**
 * The guided risk cockpit. Hierarchy: executive summary (AI, loads second) →
 * deterministic KPIs → ranked risk drivers → scenario explorer → detailed
 * sortable/filterable tables. The scenario sweep is fetched once alongside the
 * report so the shock selector switches with zero refetch.
 */
export function ReportSections({ report }: { report: RiskReport }) {
  const explainInput = useMemo(() => explainInputFromReport(report), [report]);
  const explain = useRiskExplain(explainInput);

  // Fire the −30%…+30% sweep once so the Scenario Explorer has data without a
  // click. Holdings don't change within a mount, so a re-run of the report
  // doesn't need a re-sweep.
  const scenarios = useScenarios();
  const varBacktest = useVarBacktest();
  const fired = useRef(false);
  useEffect(() => {
    if (!fired.current) {
      fired.current = true;
      scenarios.mutate();
      varBacktest.mutate();
    }
  }, [scenarios, varBacktest]);

  return (
    <div className="space-y-6">
      <RiskDiagnosis
        explain={explain.data}
        loading={explain.isLoading}
        source="risk"
        title="Executive summary"
      />
      <PortfolioValueSummary metrics={report} />
      <KpiGrid report={report} />
      <BenchmarkContext mine={report} />
      <MetricTrend
        metric="net_equity"
        title="Total value over time"
        description="Net equity snapshots saved from your Health Score runs."
        kind="usd"
      />
      <MetricTrend
        metric="annual_volatility"
        title="Your volatility over time"
        description="From the snapshots saved each time you score."
        kind="pct"
      />
      <RiskDrivers report={report} />
      {report.concentration && (
        <ConcentrationCard concentration={report.concentration} />
      )}
      <ScenarioExplorer
        scenarios={scenarios.data}
        loading={scenarios.isPending}
        fallbackTotal={report.annual_volatility}
      />
      <VarBacktest data={varBacktest.data} loading={varBacktest.isPending} />
      <FactorBetasTable report={report} />
      <ComponentVarTable report={report} />
      <StressSummary report={report} />
      {Object.keys(report.macro_betas).length > 0 && <MacroBetas report={report} />}
      {report.liquidity.length > 0 && <LiquidityTable report={report} />}
    </div>
  );
}

function KpiGrid({ report }: { report: RiskReport }) {
  return (
    <section className="space-y-2">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Annual return" value={fmtPct(report.annual_return)} />
        <Kpi label="Annual vol" value={fmtPct(report.annual_volatility)} />
        <Kpi label="Sharpe" value={fmtNum(report.sharpe_ratio, 2)} />
        <Kpi label="Max DD" value={fmtPct(report.max_drawdown)} />
        <Kpi label="VaR 95 (1d)" value={fmtPct(report.var_95)} accent="destructive" />
        <Kpi label="VaR 99 (1d)" value={fmtPct(report.var_99)} accent="destructive" />
        <Kpi label="CVaR 95 (1d)" value={fmtPct(report.cvar_95)} accent="destructive" />
        <Kpi label="Risk-free" value={fmtPct(report.risk_free_rate)} />
      </div>
      <DataProvenance
        source="Monte-Carlo VaR + factor regression on yfinance history"
        priceProvenance={report.price_provenance}
      />
      {report.data_quality_notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
          {report.data_quality_notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Kpi({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: "destructive";
}) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p
          className={`font-mono text-2xl ${
            accent === "destructive" ? "text-destructive" : ""
          }`}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

function ConcentrationCard({
  concentration,
}: {
  concentration: NonNullable<RiskReport["concentration"]>;
}) {
  const c = concentration;
  const topWeight = c.top_holding_weight ?? null;
  const highSingleName = topWeight != null && topWeight > 0.25;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Concentration</CardTitle>
        <CardDescription>
          How much of the book rides on a few names. &ldquo;Effective
          holdings&rdquo; is the equally-weighted equivalent — 10 positions
          that behave like 3 are 3.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi
            label="Top holding"
            value={
              c.top_holding_ticker
                ? `${c.top_holding_ticker} ${fmtPct(topWeight)}`
                : "—"
            }
            accent={highSingleName ? "destructive" : undefined}
          />
          <Kpi label="Top 5 weight" value={fmtPct(c.top5_weight)} />
          <Kpi
            label="Effective holdings"
            value={fmtNum(c.effective_holdings, 1)}
          />
          <Kpi label="Positions" value={String(c.num_holdings)} />
        </div>
        {highSingleName && (
          <p className="text-xs text-muted-foreground">
            One position is over 25% of the invested book — single-name news
            moves your whole portfolio.
          </p>
        )}
        {c.sectors.length > 0 && (
          <div className="space-y-1 pt-1">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              By sector
            </p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {c.sectors.slice(0, 6).map((s) => (
                <span key={s.sector} className="text-muted-foreground">
                  {s.sector}{" "}
                  <span className="font-mono text-foreground">{fmtPct(s.weight)}</span>
                </span>
              ))}
            </div>
            {c.top_sector_weight != null && c.top_sector_weight > 0.5 && (
              <p className="text-xs text-muted-foreground">
                Over half the book is {c.top_sector} — a sector-wide drawdown
                hits most of your positions at once.
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RiskDrivers({ report }: { report: RiskReport }) {
  const sorted = useMemo(
    () => [...report.component_var_pct].sort((a, b) => b.pct - a.pct),
    [report.component_var_pct],
  );
  if (sorted.length === 0) return null;

  const top = sorted.slice(0, 6);
  const bars: BarDatum[] = top.map((r) => ({
    label: r.ticker,
    value: Math.round(r.pct * 1000) / 10,
    color: "hsl(var(--primary))",
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Risk drivers</CardTitle>
        <CardDescription>
          Where your portfolio risk actually comes from — ranked by share of
          total VaR.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 md:grid-cols-2">
        <ol className="space-y-2 text-sm">
          {top.map((r, i) => (
            <li
              key={r.ticker}
              className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2"
            >
              <span className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">#{i + 1}</span>
                <span className="font-mono font-medium">{r.ticker}</span>
              </span>
              <span className="flex items-center gap-3">
                <span className="text-xs text-muted-foreground">{driverNote(r.pct)}</span>
                <span className="font-mono">{fmtPct(r.pct)}</span>
              </span>
            </li>
          ))}
        </ol>
        <HorizontalBarChart
          data={bars}
          valueFormatter={(v) => `${v.toFixed(1)}%`}
          ariaLabel="Component VaR contribution by holding"
        />
      </CardContent>
    </Card>
  );
}

function driverNote(pct: number): string {
  if (pct >= 0.4) return "largest single risk";
  if (pct >= 0.25) return "major contributor";
  if (pct >= 0.15) return "meaningful share";
  return "modest contributor";
}

const SCENARIO_SHOCKS = [-0.05, -0.1, -0.2, -0.3];

function ScenarioExplorer({
  scenarios,
  loading,
}: {
  scenarios: Scenarios | undefined;
  loading: boolean;
  fallbackTotal: number | null;
}) {
  const [shock, setShock] = useState(-0.1);

  const point = useMemo(() => {
    if (!scenarios) return undefined;
    return scenarios.scenarios.find((p) => Math.abs(p.shock_pct - shock) < 1e-6);
  }, [scenarios, shock]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Scenario explorer</CardTitle>
        <CardDescription>
          What a broad market move would do to your portfolio — and which
          holdings get hit hardest.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap gap-2">
          {SCENARIO_SHOCKS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                setShock(s);
                track("scenario_shock_selected", { shock_pct: s });
              }}
              className={
                shock === s
                  ? "rounded-md border border-primary bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                  : "rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
              }
            >
              {fmtPct(s)}
            </button>
          ))}
        </div>

        {loading && !scenarios ? (
          <Skeleton className="h-28" />
        ) : !point ? (
          <p className="text-sm text-muted-foreground">
            Scenario data unavailable for this portfolio.
          </p>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Kpi label="Market move" value={fmtPct(point.shock_pct)} />
              <Kpi
                label="Portfolio P&L"
                value={fmtPct(point.pnl_pct)}
                accent={point.pnl_pct < 0 ? "destructive" : undefined}
              />
              <Kpi label="Projected value" value={fmtUSD(point.portfolio_value)} />
            </div>

            {point.pnl_pct <= -0.15 && (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
                A move like this would cut your portfolio by{" "}
                <span className="font-semibold text-destructive">
                  {fmtPct(Math.abs(point.pnl_pct))}
                </span>
                . Make sure your cash cushion and time horizon can ride it out.
              </div>
            )}

            {point.asset_losses.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  Top impacted holdings
                </p>
                <ul className="space-y-1 text-sm">
                  {point.asset_losses.slice(0, 5).map((a) => (
                    <li key={a.ticker} className="flex justify-between gap-2">
                      <span className="font-mono">{a.ticker}</span>
                      <span className="font-mono text-destructive">{fmtPct(a.loss_pct)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FactorBetasTable({ report }: { report: RiskReport }) {
  if (report.factor_betas.length === 0) return null;
  const bars: BarDatum[] = report.factor_betas
    .filter((r) => r.beta != null)
    .map((r) => ({
      label: r.factor,
      value: Math.round((r.beta as number) * 1000) / 1000,
      color: (r.beta as number) >= 0 ? "hsl(var(--primary))" : "hsl(var(--muted-foreground))",
    }));

  const columns: Column<FactorBetaRow>[] = [
    { key: "factor", header: "Factor", render: (r) => <span className="font-sans">{r.factor}</span>, sortValue: (r) => r.factor },
    { key: "beta", header: "Beta", align: "right", render: (r) => fmtNum(r.beta, 3), sortValue: (r) => r.beta ?? 0 },
    { key: "r2", header: "R²", align: "right", render: (r) => fmtNum(r.r_squared, 2), sortValue: (r) => r.r_squared ?? 0 },
    { key: "t", header: "t-stat", align: "right", render: (r) => fmtNum(r.t_stat, 2), sortValue: (r) => r.t_stat ?? 0 },
    { key: "p", header: "p-value", align: "right", render: (r) => fmtNum(r.p_value, 3), sortValue: (r) => r.p_value ?? 0 },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Factor betas</CardTitle>
        <CardDescription>
          Regression of portfolio returns on each factor (SPY / QQQ / GLD / TLT /
          IWM / VTV). Sort any column; the bars show beta magnitude.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 md:grid-cols-2">
        <HorizontalBarChart data={bars} valueFormatter={(v) => v.toFixed(2)} ariaLabel="Factor betas" />
        <DataTable
          rows={report.factor_betas}
          columns={columns}
          rowKey={(r) => r.factor}
          initialSort={{ key: "beta", dir: "desc" }}
          minWidth={360}
        />
      </CardContent>
    </Card>
  );
}

type RiskReturnRow = ComponentVarRow & { contribution: number | null };

function ComponentVarTable({ report }: { report: RiskReport }) {
  if (report.component_var_pct.length === 0) return null;
  // Merge the return-side contribution (when the backend ships it) so each
  // holding shows "who risks you" next to "who pays you".
  const contribByTicker = new Map(
    report.component_return.map((r) => [r.ticker, r.contribution]),
  );
  const rows: RiskReturnRow[] = report.component_var_pct.map((r) => ({
    ...r,
    contribution: contribByTicker.get(r.ticker) ?? null,
  }));
  const hasReturns = report.component_return.length > 0;
  const columns: Column<RiskReturnRow>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-sans">{r.ticker}</span>, sortValue: (r) => r.ticker },
    { key: "pct", header: "Share of VaR", align: "right", render: (r) => fmtPct(r.pct), sortValue: (r) => r.pct },
    ...(hasReturns
      ? [
          {
            key: "contribution",
            header: "Return contribution",
            align: "right",
            render: (r) => fmtPct(r.contribution),
            sortValue: (r) => r.contribution ?? -Infinity,
          } satisfies Column<RiskReturnRow>,
        ]
      : []),
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {hasReturns ? "Risk vs return per holding" : "Component VaR — full table"}
        </CardTitle>
        <CardDescription>
          {hasReturns
            ? "Each holding's share of portfolio VaR next to its contribution to annualized return — a big risk share with a small return contribution is a position to question."
            : "Every holding's share of total portfolio VaR."}
        </CardDescription>
      </CardHeader>
      <CardContent className="p-4">
        <DataTable
          rows={rows}
          columns={columns}
          rowKey={(r) => r.ticker}
          filterKey="ticker"
          initialSort={{ key: "pct", dir: "desc" }}
          minWidth={hasReturns ? 380 : 280}
        />
      </CardContent>
    </Card>
  );
}

function StressSummary({ report }: { report: RiskReport }) {
  const bars: BarDatum[] = [...report.stress_asset_losses]
    .sort((a, b) => a.loss_pct - b.loss_pct)
    .slice(0, 10)
    .map((r) => ({
      label: r.ticker,
      value: Math.round(r.loss_pct * 1000) / 10,
      color: "hsl(var(--destructive))",
    }));

  const columns: Column<StressAssetLoss>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-sans">{r.ticker}</span>, sortValue: (r) => r.ticker },
    {
      key: "loss",
      header: "Loss",
      align: "right",
      render: (r) => <span className="text-destructive">{fmtPct(r.loss_pct)}</span>,
      sortValue: (r) => r.loss_pct,
    },
  ];

  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle className="text-base">Stress test</CardTitle>
        <CardDescription>
          Portfolio P&amp;L if every holding takes the market shock applied to its
          market beta.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-4">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Market shock</p>
          <p className="font-mono">{fmtPct(report.stress_market_shock)}</p>
          <p className="ml-6 text-[10px] uppercase tracking-wide text-muted-foreground">Portfolio loss</p>
          <p className="font-mono text-destructive">{fmtPct(report.stress_loss)}</p>
        </div>
        {report.stress_asset_losses.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            <HorizontalBarChart data={bars} valueFormatter={(v) => `${v.toFixed(1)}%`} ariaLabel="Stress loss by holding" />
            <DataTable
              rows={report.stress_asset_losses}
              columns={columns}
              rowKey={(r) => r.ticker}
              filterKey="ticker"
              initialSort={{ key: "loss", dir: "asc" }}
              minWidth={260}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MacroBetas({ report }: { report: RiskReport }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Macro sensitivities</CardTitle>
        <CardDescription>
          Portfolio regression coefficients against rates, USD, and oil.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-3 gap-3 p-4">
        {Object.entries(report.macro_betas).map(([factor, beta]) => (
          <div key={factor} className="rounded-md border border-border bg-muted/30 p-3">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {factor}
            </p>
            <p className="font-mono text-lg">{fmtNum(beta, 3)}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/** Cell heat: green (fast to exit) → amber → red (slow / illiquid). */
function liquidityHeat(days: number | null): string {
  if (days == null) return "";
  if (days >= 5) return "bg-red-500/15 text-red-600 dark:text-red-400";
  if (days >= 2) return "bg-amber-500/15 text-amber-600 dark:text-amber-400";
  if (days >= 1) return "bg-yellow-500/10";
  return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
}

function LiquidityTable({ report }: { report: RiskReport }) {
  const columns: Column<LiquidityRow>[] = [
    { key: "ticker", header: "Ticker", render: (r) => <span className="font-sans">{r.ticker}</span>, sortValue: (r) => r.ticker },
    { key: "mv", header: "Market value", align: "right", render: (r) => fmtUSD(r.market_value), sortValue: (r) => r.market_value ?? 0 },
    { key: "adv", header: "30d ADV", align: "right", render: (r) => fmtUSD(r.adv_30d), sortValue: (r) => r.adv_30d ?? 0 },
    {
      key: "days",
      header: "Days to liq.",
      align: "right",
      render: (r) => fmtNum(r.days_to_liquidate, 1),
      sortValue: (r) => r.days_to_liquidate ?? 0,
      cellClassName: (r) => liquidityHeat(r.days_to_liquidate),
    },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Liquidity</CardTitle>
        <CardDescription>
          Days to fully liquidate each position at 10% of 30-day ADV — redder =
          harder to exit in a hurry.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-4">
        <DataTable
          rows={report.liquidity}
          columns={columns}
          rowKey={(r) => r.ticker}
          filterKey="ticker"
          initialSort={{ key: "days", dir: "desc" }}
          minWidth={420}
        />
      </CardContent>
    </Card>
  );
}

export function ResultSkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-32" />
    </div>
  );
}

export function RiskErrorPanel({ error }: { error: Error }) {
  const isApi = error instanceof ApiError;
  const code = isApi ? error.code : "unknown";
  let headline = "Could not run report";
  let body = error.message;
  if (code === "no_active_portfolio") {
    headline = "No active portfolio";
    body = "Mark a portfolio as default to score it here.";
  } else if (code === "no_market_data") {
    headline = "Market data unavailable";
    body = "Try again in a minute — yfinance may be rate-limited.";
  }
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">{headline}</CardTitle>
        {isApi && (
          <CardDescription className="font-mono text-xs">
            {error.status} · {code}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <p className="text-sm">{body}</p>
      </CardContent>
    </Card>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function fmtNum(v: number | null | undefined, dp = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(dp);
}

function fmtUSD(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
