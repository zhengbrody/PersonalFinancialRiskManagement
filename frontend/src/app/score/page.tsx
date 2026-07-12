"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { ScoreGauge, scoreBand } from "@/components/score-gauge";
import { RiskDiagnosis, ActionCards } from "@/components/risk-diagnosis";
import { ActionSimulate } from "@/components/action-simulate";
import { OptionScoreModule } from "@/components/option-score-module";
import { ScoreDrivers } from "@/components/score-drivers";
import { ScoreConcentration } from "@/components/score-concentration";
import { ImproveScore } from "@/components/improve-score";
import { ScoreMiniScenario } from "@/components/score-mini-scenario";
import { RiskAlertsCard } from "@/components/risk-alerts-card";
import { PortfolioValueSummary } from "@/components/portfolio-value-summary";
import { BenchmarkContext } from "@/components/benchmark-context";
import { DataProvenance } from "@/components/data-provenance";
import { DataConfidence } from "@/components/data-confidence";
import { MetricTrend } from "@/components/metric-trend";
import { ScoreChangeReport, ReasonCodes } from "@/components/score-change-report";
import { RegimeContextLine } from "@/components/regime-context";
import { track } from "@/lib/analytics";
import { ApiError, apiFetch, isNoPortfolioError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useActiveScore,
  useLastSnapshot,
  useMarketPrices,
  useMyPortfolios,
  useRiskExplain,
} from "@/lib/queries";
import { WhatIfCompare } from "@/components/whatif-compare";
import {
  equityTickersFromHoldings,
  rowsFromHoldingsAndPrices,
  scaleValue,
} from "@/lib/whatif";
import { explainInputFromScore } from "@/lib/risk-explain-input";
import { scoreResponseSchema } from "@/lib/schemas";
import type { Holding, ScoreRequest, ScoreResponse } from "@/lib/schemas";

const COCKPIT_TABS = [
  { value: "overview", label: "Overview" },
  { value: "drivers", label: "Drivers" },
  { value: "changed", label: "What Changed" },
  { value: "actions", label: "Actions" },
];

type HoldingRow = { ticker: string; market_value: string };

const DEFAULT_ROWS: HoldingRow[] = [
  { ticker: "SPY", market_value: "60000" },
  { ticker: "BND", market_value: "40000" },
];

export default function ScorePage() {
  const [rows, setRows] = useState<HoldingRow[]>(DEFAULT_ROWS);
  const [riskPref, setRiskPref] = useState(3);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  // Signed-in users get their SAVED portfolio scored automatically (no need
  // to re-type holdings) — the manual form below is an optional what-if.
  const { user, configured } = useAuth();
  const signedIn = Boolean(configured && user);
  // Cached query (shared with the dashboard) — auto-scores the saved portfolio
  // and is served from cache on revisit, so it no longer recomputes + blanks
  // every time. Disabled for anon (no token).
  const active = useActiveScore();

  // What-if lab plumbing (signed-in only): the saved book + latest closes so
  // "load my holdings" can prefill the sandbox with shares × price. Both are
  // cached queries; anon passes an empty ticker set (query disabled).
  const myPortfolios = useMyPortfolios();
  const activeBook = signedIn
    ? (myPortfolios.data?.portfolios.find((p) => p.is_default) ??
      myPortfolios.data?.portfolios[0])
    : undefined;
  const equityTickers = useMemo(
    () => (activeBook ? equityTickersFromHoldings(activeBook.holdings) : []),
    [activeBook],
  );
  const bookPrices = useMarketPrices(equityTickers);
  const canLoadBook = equityTickers.length > 0 && Boolean(bookPrices.data);

  function loadMyHoldings() {
    const loaded = rowsFromHoldingsAndPrices(activeBook?.holdings, bookPrices.data);
    if (loaded.length === 0) return;
    setRows(loaded);
    track("whatif_loaded_holdings"); // safe: no tickers/$ in props
  }

  // What the result panel shows: a manual run takes precedence; otherwise the
  // signed-in user's auto-scored saved portfolio.
  const shown = result ?? (signedIn ? active.data ?? null : null);
  const showLoading = loading || (signedIn && !result && active.isLoading);
  const showError =
    error ?? (signedIn && !result ? (active.error as ApiError | null) : null);

  function updateRow(i: number, patch: Partial<HoldingRow>) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { ticker: "", market_value: "" }]);
  }

  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setResult(null);

    const holdings: Holding[] = rows
      .filter((r) => r.ticker.trim() !== "")
      .map((r) => ({
        ticker: r.ticker.trim().toUpperCase(),
        market_value: Number(r.market_value) || 0,
        asset_type: "public_security",
      }));

    const body: ScoreRequest = {
      holdings,
      risk_preference: riskPref,
    };

    try {
      const data = await apiFetch<ScoreResponse>("/api/v1/risk/score", {
        method: "POST",
        body,
        schema: scoreResponseSchema,
      });
      setResult(data);
      if (signedIn) track("whatif_run"); // safe: no portfolio data in props
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)));
    } finally {
      setLoading(false);
    }
  }

  const whatIfForm = (
    <form onSubmit={onSubmit} className="space-y-4">
      {signedIn && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!canLoadBook}
            onClick={loadMyHoldings}
          >
            Start from my holdings
          </Button>
          <span className="text-xs text-muted-foreground">
            {canLoadBook
              ? "Load your real book (valued at the latest close), then adjust the mix."
              : "Waiting for holdings and latest prices to load…"}
          </span>
        </div>
      )}
      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex gap-2">
            <Input
              aria-label="Ticker"
              placeholder="SPY"
              value={row.ticker}
              onChange={(e) => updateRow(i, { ticker: e.target.value })}
              className="font-mono"
            />
            <Input
              aria-label="Market value"
              type="number"
              inputMode="decimal"
              placeholder="60000"
              value={row.market_value}
              onChange={(e) => updateRow(i, { market_value: e.target.value })}
              className="font-mono"
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="px-2 font-mono text-xs"
              onClick={() => updateRow(i, { market_value: scaleValue(row.market_value, 0.9) })}
              aria-label={`Trim ${row.ticker || "row"} 10%`}
            >
              −10%
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="px-2 font-mono text-xs"
              onClick={() => updateRow(i, { market_value: scaleValue(row.market_value, 1.1) })}
              aria-label={`Add ${row.ticker || "row"} 10%`}
            >
              +10%
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeRow(i)}
              aria-label="Remove row"
            >
              ×
            </Button>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={addRow}>
          + add holding
        </Button>
      </div>

      <div className="flex items-center gap-3">
        <label htmlFor="risk-pref" className="text-sm text-muted-foreground">
          Risk preference (1–5)
        </label>
        <Input
          id="risk-pref"
          type="number"
          min={1}
          max={5}
          value={riskPref}
          onChange={(e) => setRiskPref(Number(e.target.value) || 3)}
          className="w-20 font-mono"
        />
        {signedIn && riskPref !== 3 && (
          <span className="text-xs text-muted-foreground">
            The baseline is scored at preference 3 — changing this value will itself show up in the comparison.
          </span>
        )}
      </div>

      <Button type="submit" disabled={loading} className="w-full">
        {loading ? "Scoring…" : "Run score"}
      </Button>
    </form>
  );

  const resultArea = (
    <div className="space-y-4">
      {signedIn && result && active.data && (
        <WhatIfCompare
          baseline={active.data}
          sandbox={result}
          onReset={() => setResult(null)}
        />
      )}
      {signedIn && !result && active.data && (
        <p className="text-xs text-muted-foreground">
          Scored from your saved Holdings.{" "}
          <Link href="/portfolios" className="text-primary hover:underline">
            Edit holdings →
          </Link>
        </p>
      )}
      {showLoading && <ResultSkeleton />}
      {showError && !showLoading && <ScoreError error={showError} />}
      {shown && !showLoading && <ResultPanel result={shown} />}
      {!showLoading && !showError && !shown && (
        <Card>
          <CardHeader>
            <CardTitle>No score yet</CardTitle>
            <CardDescription>
              {signedIn
                ? "Add holdings to your portfolio, or run a what-if below."
                : "Hit Run score — this public sandbox uses the same scoring engine as the signed-in workflow."}
            </CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          Portfolio Health Score
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          {signedIn ? "Your portfolio health" : "Score any portfolio"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {signedIn
            ? "A 0–1000 score across risk match, risk-adjusted return, and downside protection — with the drivers, what changed, and what to do."
            : "A 0–1000 health score from the same deterministic risk engine signed-in members use. Edit the holdings and run it."}
        </p>
      </header>

      {signedIn ? (
        // Full-width cockpit — the saved book is the primary surface; the
        // what-if form is demoted to a collapsible panel so it no longer
        // dominates like a data-entry sandbox.
        <div className="space-y-6">
          {resultArea}
          <details id="whatif" className="group scroll-mt-24 rounded-xl border border-border bg-card">
            <summary className="flex cursor-pointer items-center gap-2 px-5 py-3 text-sm font-medium">
              <span>What-if lab</span>
              <span className="text-xs font-normal text-muted-foreground">
                — load your holdings, change a few numbers, and see how the score and risk move (your real book stays untouched)
              </span>
            </summary>
            <div className="border-t border-border p-5">{whatIfForm}</div>
          </details>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <Card>
            <CardHeader>
              <CardTitle>Holdings</CardTitle>
              <CardDescription>Edit, then run.</CardDescription>
            </CardHeader>
            <CardContent>{whatIfForm}</CardContent>
          </Card>
          <div>{resultArea}</div>
        </div>
      )}
    </div>
  );
}

function ResultSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-32" />
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-16 w-40" />
        <div className="grid gap-3 sm:grid-cols-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
        <Skeleton className="h-32" />
      </CardContent>
    </Card>
  );
}

/** Error renderer that turns the no-portfolio codes into a create-CTA. */
function ScoreError({ error }: { error: ApiError }) {
  if (isNoPortfolioError(error)) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Set up your portfolio</CardTitle>
          <CardDescription>
            Add your holdings and we&apos;ll score the risk automatically.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/portfolios/new">
            <Button>Create a portfolio</Button>
          </Link>
        </CardContent>
      </Card>
    );
  }
  return <ErrorPanel error={error} />;
}

function ErrorPanel({ error }: { error: ApiError }) {
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">
          {error.code === "network_error"
            ? "We couldn't reach the scoring service"
            : "Something went wrong"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">
          {error.code === "network_error"
            ? "Check your connection and try again in a moment."
            : error.message}
        </p>
      </CardContent>
    </Card>
  );
}

function ResultPanel({ result }: { result: ScoreResponse }) {
  const [tab, setTab] = useState("overview");
  const lastSnapshot = useLastSnapshot();
  const snapshot = lastSnapshot.data?.snapshot ?? null;

  // Build the explain input from numbers we ALREADY have — memoised so the
  // query key is stable across tab switches (no re-call). The diagnosis query
  // is auth-gated, so it's a no-op for the anonymous public sandbox.
  const explainInput = useMemo(
    () => explainInputFromScore(result, snapshot),
    [result, snapshot],
  );
  const explain = useRiskExplain(explainInput);

  // Proactive risk-alert input from the score we already have (score-level
  // fields + option flags). The report-level fields fill in on /risk.
  const alertsInput = useMemo(() => {
    const m = result.metrics;
    return {
      annual_volatility: m.annual_volatility,
      var_95_daily: m.var_95_daily,
      max_drawdown: m.max_drawdown,
      sharpe_ratio: m.sharpe_ratio,
      beta_to_benchmark: m.beta_to_benchmark,
      leverage: m.leverage,
      margin_cost_annual: m.margin_cost_annual,
      option_flags: (result.options?.flags ?? []).map((f) => f.code),
    };
  }, [result]);

  const band = scoreBand(result.overall_score);

  return (
    <div className="space-y-4">
      {/* ── hero: score + gauge (deterministic, paints first) ───────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle>Portfolio Health Score</CardTitle>
          <CardDescription>0–1000 · MindMarket Portfolio Health</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex items-baseline gap-3">
            <span
              data-testid="score-page-overall"
              className="font-mono text-6xl font-semibold tracking-tight text-primary"
            >
              {result.overall_score}
            </span>
            <span className="text-lg text-muted-foreground">/ 1000</span>
            <span className={`text-sm font-semibold uppercase tracking-wide ${band.text}`}>
              {band.label}
            </span>
          </div>
          <ScoreGauge score={result.overall_score} />
          <HeroMeta metrics={result.metrics} />
          <DataConfidence confidence={result.data_confidence} className="mt-1" />
          <RegimeContextLine />
        </CardContent>
      </Card>

      <Tabs
        items={COCKPIT_TABS}
        value={tab}
        onValueChange={(v) => {
          setTab(v);
          track("risk_tab_changed", { tab: v, source: "score" });
        }}
      />

      {tab === "overview" && (
        <div className="space-y-4">
          <RiskDiagnosis explain={explain.data} loading={explain.isLoading} source="score" />
          <ReasonCodes score={result} />
          <RiskAlertsCard input={alertsInput} source="score" />
          <ScoreConcentration concentration={result.concentration} />
          <ImproveScore score={result} />
          <ScoreMiniScenario metrics={result.metrics} />
          <OptionScoreModule impact={result.options} />
          <PortfolioValueSummary metrics={result.metrics} />
          <BenchmarkContext mine={result.metrics} />
          <MetricsCard result={result} />
        </div>
      )}
      {tab === "drivers" && (
        <div className="space-y-4">
          <ScoreDrivers score={result} />
          <ImproveScore score={result} />
        </div>
      )}
      {tab === "changed" && (
        <div className="space-y-4">
          <MetricTrend
            metric="net_equity"
            title="Total value over time"
            description="Net equity snapshots from each saved score."
            kind="usd"
          />
          <MetricTrend
            metric="overall_score"
            title="Health score over time"
            description="Each visit you score, we save a snapshot — here's your trend."
            kind="score"
          />
          <ScoreChangeReport score={result} />
        </div>
      )}
      {tab === "actions" && (
        <ActionSimulate
          fallback={<ActionCards explain={explain.data} loading={explain.isLoading} />}
        />
      )}

      <p className="pt-1 text-sm">
        <Link href="/risk" className="text-primary hover:underline">
          See the full Risk Report → factor exposures, per-holding VaR, stress &amp; liquidity
        </Link>
      </p>
    </div>
  );
}

/** Small hero meta — surfaces margin (hidden risk) + a cash note up top, not
 * buried in the metrics table. Renders nothing for an unlevered, cash-light book. */
function HeroMeta({ metrics }: { metrics: ScoreResponse["metrics"] }) {
  const lev = typeof metrics.leverage === "number" ? metrics.leverage : 1;
  const cashW = typeof metrics.cash_weight === "number" ? metrics.cash_weight : 0;
  const levered = lev > 1.0001;
  const cash = cashW > 0.05;
  if (!levered && !cash) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      {levered && (
        <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-medium text-amber-700 dark:text-amber-300">
          {lev.toFixed(2)}× margin — amplifies gains and losses
        </span>
      )}
      {cash && (
        <span className="rounded-full border border-border bg-muted/50 px-2 py-0.5 text-muted-foreground">
          {(cashW * 100).toFixed(0)}% cash
        </span>
      )}
    </div>
  );
}

function MetricsCard({ result }: { result: ScoreResponse }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Metrics</CardTitle>
        <CardDescription>The figures behind the score</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-3">
          <MetricRow label="Annual return" value={fmtPct(result.metrics.annual_return)} />
          <MetricRow label="Annual vol" value={fmtPct(result.metrics.annual_volatility)} />
          <MetricRow
            label="Sharpe (asset-mix quality)"
            value={fmtNum(result.metrics.sharpe_ratio, 2)}
          />
          <MetricRow label="Max DD" value={fmtPct(result.metrics.max_drawdown)} />
          <MetricRow
            label="Drawdown now"
            value={drawdownNowLabel(
              result.metrics.current_drawdown,
              result.metrics.max_drawdown,
            )}
          />
          <MetricRow label="VaR 95 (daily)" value={fmtPct(result.metrics.var_95_daily)} />
          <MetricRow label="CVaR 95 (daily)" value={fmtPct(result.metrics.cvar_95_daily)} />
          <MetricRow label="Beta" value={fmtNum(result.metrics.beta_to_benchmark, 2)} />
          <MetricRow label="Gross value" value={fmtUSD(result.metrics.total_value)} />
          <MetricRow
            label="Net equity"
            value={fmtUSD(result.metrics.net_equity ?? result.metrics.total_value)}
          />
          <MetricRow
            label="Today"
            value={fmtMoneyPct(result.metrics.daily_pnl, result.metrics.daily_return)}
          />
          <MetricRow
            label="Total return"
            value={fmtMoneyPct(result.metrics.total_pnl, result.metrics.total_return)}
          />
          <MetricRow label="Observations" value={String(result.metrics.observations ?? "—")} />
        </div>

        <MarginImpact metrics={result.metrics} />

        {result.metrics.data_quality_notes.length > 0 && (
          <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-xs text-muted-foreground">
            <div className="font-medium text-warning">Data quality notes</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {result.metrics.data_quality_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}

        <DataProvenance
          source="Computed from yfinance history"
          observations={result.metrics.observations}
          coverage={result.metrics.data_coverage}
          priceProvenance={result.price_provenance}
          scoreVersion={result.score_version}
        />
      </CardContent>
    </Card>
  );
}

/**
 * Margin & cash impact — shown only for a leveraged book. Keeps the borrow
 * drag visible (transparency) so the leverage-invariant asset-mix Sharpe above
 * isn't mistaken for "no leverage risk".
 */
function MarginImpact({ metrics }: { metrics: ScoreResponse["metrics"] }) {
  const lev = metrics.leverage ?? 1;
  if (!lev || lev <= 1.0001) return null;
  return (
    <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
      <div className="font-medium text-amber-600 dark:text-amber-400">
        Margin &amp; cash impact
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-6 gap-y-1 text-muted-foreground sm:grid-cols-3">
        <MetricRow label="Leverage" value={`${lev.toFixed(2)}×`} />
        <MetricRow label="Margin cost / yr" value={fmtPct(-(metrics.margin_cost_annual ?? 0))} />
        <MetricRow label="Asset-mix return" value={fmtPct(metrics.gross_annual_return)} />
        <MetricRow label="Equity return" value={fmtPct(metrics.annual_return)} />
      </div>
      <p className="mt-1.5 text-muted-foreground">
        Sharpe above is the leverage-invariant asset-mix Sharpe (portfolio
        quality). Margin amplifies vol/VaR and the borrow cost drags your
        equity-level return — shown here so the leverage risk stays visible.
      </p>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-border/40 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

/** "Drawdown now" — distinguishes a stale (recovered) worst drawdown from one
 * the book is currently sitting in. At/near a fresh high we say "recovered". */
function drawdownNowLabel(
  current: number | null | undefined,
  max: number | null | undefined,
): string {
  if (current === null || current === undefined || Number.isNaN(current)) return "—";
  if (current < 0.01 && (max ?? 0) > 0.05) return "≈ at high";
  return fmtPct(current);
}

function fmtNum(v: number | null | undefined, dp = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(dp);
}

function fmtUSD(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function fmtSignedUSD(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v < 0 ? "-" : ""}$${Math.abs(v).toLocaleString(undefined, {
    maximumFractionDigits: 0,
  })}`;
}

function fmtSignedPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(2)}%`;
}

function fmtMoneyPct(
  money: number | null | undefined,
  pct: number | null | undefined,
): string {
  const a = fmtSignedUSD(money);
  const b = fmtSignedPct(pct);
  if (a === "—" && b === "—") return "—";
  if (b === "—") return a;
  if (a === "—") return b;
  return `${a} (${b})`;
}
