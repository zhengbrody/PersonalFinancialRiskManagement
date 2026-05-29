"use client";

/**
 * Detailed risk analysis page for a specific portfolio.
 *
 * Phase 7 scope:
 *   * VaR / CVaR KPI tiles
 *   * Sharpe + annual return + vol
 *   * Component VaR table (per-ticker contribution)
 *   * Factor betas table (SPY/QQQ/GLD/TLT/IWM/VTV)
 *   * Stress test summary
 *   * Macro betas
 *   * Liquidity table
 *
 * The backend's /risk/report_from_active resolves the user's *active*
 * portfolio (default-flagged) from JWT. If the user lands here for a
 * non-default portfolio we show a notice — phase 8+ will accept an
 * explicit portfolio_id.
 */

import { useEffect, useMemo } from "react";
import { useParams, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useMyPortfolios,
  useRiskReport,
  type RiskReport,
} from "@/lib/queries";

export default function PortfolioRiskPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const portfolioId = params.id;

  const { user, loading: authLoading, configured } = useAuth();
  const portfoliosQuery = useMyPortfolios();
  const reportMutation = useRiskReport();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  const portfolio = useMemo(
    () => portfoliosQuery.data?.portfolios.find((p) => p.id === portfolioId),
    [portfoliosQuery.data, portfolioId],
  );

  if (!configured || authLoading || !user || portfoliosQuery.isLoading) {
    return <PageSkeleton />;
  }

  if (!portfolio) {
    return (
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle>Portfolio not found</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          This portfolio is not in your account.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            POST /api/v1/risk/report_from_active
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Risk report
          </h1>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium">{portfolio.name}</span>{" "}
            <span className="font-mono text-xs">{portfolio.id}</span>
          </p>
        </div>
        <Button
          type="button"
          size="lg"
          onClick={() => reportMutation.mutate()}
          disabled={reportMutation.isPending}
        >
          {reportMutation.isPending
            ? "Computing…"
            : reportMutation.data
              ? "Re-run"
              : "Run report"}
        </Button>
      </header>

      {!portfolio.is_default && (
        <Card className="border-warning/40">
          <CardHeader>
            <CardTitle className="text-base">Not the active portfolio</CardTitle>
            <CardDescription>
              The risk report uses the portfolio flagged{" "}
              <code className="font-mono">is_default=true</code>. Mark this
              one as default from the edit page if you want to score it here.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {reportMutation.isPending && <ResultSkeleton />}
      {reportMutation.isError && (
        <ErrorPanel error={reportMutation.error as Error} />
      )}
      {reportMutation.data && !reportMutation.isPending && (
        <ReportSections report={reportMutation.data} />
      )}
      {!reportMutation.data && !reportMutation.isPending && !reportMutation.isError && (
        <Card>
          <CardHeader>
            <CardTitle>No report yet</CardTitle>
            <CardDescription>
              Click <span className="font-mono">Run report</span> — first
              run takes a few seconds while the cache warms up.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
}

// ── sections ──────────────────────────────────────────────────────

function ReportSections({ report }: { report: RiskReport }) {
  return (
    <div className="space-y-6">
      <KpiGrid report={report} />
      <FactorBetasTable report={report} />
      <ComponentVarTable report={report} />
      <StressSummary report={report} />
      {Object.keys(report.macro_betas).length > 0 && (
        <MacroBetas report={report} />
      )}
      {report.liquidity.length > 0 && <LiquidityTable report={report} />}
    </div>
  );
}

function KpiGrid({ report }: { report: RiskReport }) {
  return (
    <section className="grid gap-3 md:grid-cols-4">
      <Kpi label="Annual return" value={fmtPct(report.annual_return)} />
      <Kpi label="Annual vol" value={fmtPct(report.annual_volatility)} />
      <Kpi label="Sharpe" value={fmtNum(report.sharpe_ratio, 2)} />
      <Kpi label="Max DD" value={fmtPct(report.max_drawdown)} />
      <Kpi label="VaR 95 (1d)" value={fmtPct(report.var_95)} accent="destructive" />
      <Kpi label="VaR 99 (1d)" value={fmtPct(report.var_99)} accent="destructive" />
      <Kpi label="CVaR 95 (1d)" value={fmtPct(report.cvar_95)} accent="destructive" />
      <Kpi label="Risk-free" value={fmtPct(report.risk_free_rate)} />
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

function FactorBetasTable({ report }: { report: RiskReport }) {
  if (report.factor_betas.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Factor betas</CardTitle>
        <CardDescription>
          Regression of portfolio returns on each factor (SPY / QQQ / GLD /
          TLT / IWM / VTV).
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-4">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 pr-3">Factor</th>
              <th className="px-3 text-right">Beta</th>
              <th className="px-3 text-right">R²</th>
              <th className="px-3 text-right">t-stat</th>
              <th className="pl-3 text-right">p-value</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {report.factor_betas.map((r) => (
              <tr key={r.factor} className="border-b border-border/40">
                <td className="py-2 pr-3 font-sans">{r.factor}</td>
                <td className="px-3 text-right">{fmtNum(r.beta, 3)}</td>
                <td className="px-3 text-right">{fmtNum(r.r_squared, 2)}</td>
                <td className="px-3 text-right">{fmtNum(r.t_stat, 2)}</td>
                <td className="pl-3 text-right">{fmtNum(r.p_value, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function ComponentVarTable({ report }: { report: RiskReport }) {
  if (report.component_var_pct.length === 0) return null;
  const sorted = [...report.component_var_pct].sort((a, b) => b.pct - a.pct);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Component VaR</CardTitle>
        <CardDescription>
          Each holding&apos;s share of total portfolio VaR — the bigger the bar,
          the larger the risk contribution.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 p-4">
        {sorted.map((row) => (
          <div key={row.ticker} className="flex items-center gap-3 text-xs">
            <span className="w-16 font-mono">{row.ticker}</span>
            <div className="h-3 flex-1 overflow-hidden rounded bg-muted/40">
              <div
                className="h-full bg-primary/70"
                style={{ width: `${Math.max(0, Math.min(100, row.pct * 100))}%` }}
              />
            </div>
            <span className="w-16 text-right font-mono">
              {fmtPct(row.pct)}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function StressSummary({ report }: { report: RiskReport }) {
  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle className="text-base">Stress test</CardTitle>
        <CardDescription>
          Portfolio P&amp;L if every holding takes the market shock applied
          to its market beta.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 p-4">
        <div className="flex items-baseline gap-3">
          <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Market shock
          </p>
          <p className="font-mono">{fmtPct(report.stress_market_shock)}</p>
          <p className="ml-6 text-[10px] uppercase tracking-wide text-muted-foreground">
            Portfolio loss
          </p>
          <p className="font-mono text-destructive">
            -{fmtPct(report.stress_loss)}
          </p>
        </div>
        {report.stress_asset_losses.length > 0 && (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border text-left text-muted-foreground">
                <th className="py-2 pr-3">Ticker</th>
                <th className="pl-3 text-right">Loss</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {report.stress_asset_losses.map((r) => (
                <tr key={r.ticker} className="border-b border-border/40">
                  <td className="py-2 pr-3 font-sans">{r.ticker}</td>
                  <td className="pl-3 text-right text-destructive">
                    -{fmtPct(r.loss_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
          <div
            key={factor}
            className="rounded-md border border-border bg-muted/30 p-3"
          >
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

function LiquidityTable({ report }: { report: RiskReport }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Liquidity</CardTitle>
        <CardDescription>
          Days to fully liquidate each position at 10% of 30-day ADV.
        </CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-4">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-muted-foreground">
              <th className="py-2 pr-3">Ticker</th>
              <th className="px-3 text-right">Market value</th>
              <th className="px-3 text-right">30d ADV</th>
              <th className="pl-3 text-right">Days to liq.</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {report.liquidity.map((r) => (
              <tr key={r.ticker} className="border-b border-border/40">
                <td className="py-2 pr-3 font-sans">{r.ticker}</td>
                <td className="px-3 text-right">{fmtUSD(r.market_value)}</td>
                <td className="px-3 text-right">{fmtUSD(r.adv_30d)}</td>
                <td className="pl-3 text-right">
                  {fmtNum(r.days_to_liquidate, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// ── loading / error UI ────────────────────────────────────────────

function PageSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-12 w-64" />
      <div className="grid gap-3 md:grid-cols-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-40" />
      <Skeleton className="h-40" />
    </div>
  );
}

function ResultSkeleton() {
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

function ErrorPanel({ error }: { error: Error }) {
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

// ── format helpers ────────────────────────────────────────────────

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
