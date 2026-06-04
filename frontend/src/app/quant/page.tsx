"use client";

/**
 * `/quant` — Backtest (Quant Lab MVP).
 *
 * Product philosophy ("Robinhood skin"): the user is a brand-new
 * retail investor. We lead with a plain-language outcome — a beautiful
 * equity-curve line chart ("how your portfolio would have grown") and
 * a few friendly KPI cards — NOT quant jargon. The hard ratio names
 * (Sharpe, etc.) are translated to human labels with a one-line
 * "what this means". Drawdown gets its own calm area chart below.
 *
 * Latency: a real backtest pulls prices and replays the strategy over
 * years of history — a few seconds — so the wait is masked with a
 * chart-shaped skeleton hero rather than a spinner.
 *
 * Auth: same client-side gate as /copilot — skeleton while Supabase
 * probes, redirect to /login when signed out.
 *
 * Theming: every color is a semantic Tailwind token or a CSS variable
 * passed into recharts, so the page adapts to the market-synced
 * light/dark theme in both modes.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { TimeSeriesChart } from "@/components/ui/chart-line";
import { QuantAttribution } from "@/components/quant-attribution";
import { QuantRegime } from "@/components/quant-regime";
import { track } from "@/lib/analytics";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useRunBacktest,
  type BacktestRequest,
  type BacktestResponse,
} from "@/lib/queries";

const QUANT_TABS = [
  { value: "backtest", label: "Backtest" },
  { value: "attribution", label: "Attribution" },
  { value: "regime", label: "Regime" },
];

// ── control options ────────────────────────────────────────────────

const STRATEGIES: { value: BacktestRequest["strategy"]; label: string }[] = [
  { value: "static", label: "Your weights" },
  { value: "equal_weight", label: "Equal weight" },
  { value: "momentum", label: "Momentum" },
];

const PERIODS: { years: number; label: string }[] = [
  { years: 1, label: "1Y" },
  { years: 3, label: "3Y" },
  { years: 5, label: "5Y" },
];

const REBALANCE: { value: NonNullable<BacktestRequest["rebalance_freq"]>; label: string }[] =
  [
    { value: "W", label: "Weekly" },
    { value: "M", label: "Monthly" },
    { value: "Q", label: "Quarterly" },
  ];

const DEFAULT_BENCHMARK = "SPY";

export default function QuantPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const backtest = useRunBacktest();

  const [tab, setTab] = useState("backtest");
  const [strategy, setStrategy] =
    useState<BacktestRequest["strategy"]>("static");
  const [years, setYears] = useState(3);
  const [rebalanceFreq, setRebalanceFreq] =
    useState<NonNullable<BacktestRequest["rebalance_freq"]>>("M");
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, configured, router]);

  if (!configured) {
    return <ConfigureSupabaseNotice />;
  }

  if (authLoading || !user) {
    return <PageSkeleton />;
  }

  function run() {
    if (backtest.isPending) return;
    setError(null);
    backtest.mutate(
      {
        strategy,
        years,
        rebalance_freq: rebalanceFreq,
        benchmark: DEFAULT_BENCHMARK,
      },
      {
        onError: (err) => {
          setError(
            err instanceof ApiError
              ? err
              : new ApiError(0, "unknown", String(err)),
          );
        },
      },
    );
  }

  const result = backtest.data;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Quant Lab</h1>
        <p className="text-sm text-muted-foreground">
          Backtest your portfolio, see where your return came from, and read the
          market&apos;s regime — in plain English.
        </p>
      </header>

      <Tabs
        items={QUANT_TABS}
        value={tab}
        onValueChange={(v) => {
          setTab(v);
          track("quant_tab_changed", { tab: v });
        }}
      />

      {tab === "backtest" && (
        <>
          <Controls
            strategy={strategy}
            years={years}
            rebalanceFreq={rebalanceFreq}
            onStrategy={setStrategy}
            onYears={setYears}
            onRebalance={setRebalanceFreq}
            onRun={run}
            running={backtest.isPending}
          />

          {error && <ErrorNotice error={error} />}
          {backtest.isPending && <ResultSkeleton />}
          {!backtest.isPending && result && <Results result={result} />}
          {!backtest.isPending && !result && !error && <EmptyState />}
        </>
      )}

      {tab === "attribution" && <QuantAttribution />}
      {tab === "regime" && <QuantRegime />}
    </div>
  );
}

// ── controls ────────────────────────────────────────────────────────

function Controls({
  strategy,
  years,
  rebalanceFreq,
  onStrategy,
  onYears,
  onRebalance,
  onRun,
  running,
}: {
  strategy: BacktestRequest["strategy"];
  years: number;
  rebalanceFreq: NonNullable<BacktestRequest["rebalance_freq"]>;
  onStrategy: (s: BacktestRequest["strategy"]) => void;
  onYears: (y: number) => void;
  onRebalance: (r: NonNullable<BacktestRequest["rebalance_freq"]>) => void;
  onRun: () => void;
  running: boolean;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-5 p-5">
        <div className="grid gap-5 sm:grid-cols-3">
          <Field label="Strategy">
            <SelectInput
              aria-label="Strategy"
              value={strategy}
              onChange={(e) =>
                onStrategy(e.target.value as BacktestRequest["strategy"])
              }
            >
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </SelectInput>
          </Field>

          <Field label="Time period">
            <SelectInput
              aria-label="Time period"
              value={String(years)}
              onChange={(e) => onYears(Number(e.target.value))}
            >
              {PERIODS.map((p) => (
                <option key={p.years} value={p.years}>
                  {p.label}
                </option>
              ))}
            </SelectInput>
          </Field>

          <Field label="Rebalance">
            <SelectInput
              aria-label="Rebalance"
              value={rebalanceFreq}
              onChange={(e) =>
                onRebalance(
                  e.target
                    .value as NonNullable<BacktestRequest["rebalance_freq"]>,
                )
              }
            >
              {REBALANCE.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </SelectInput>
          </Field>
        </div>

        <div className="flex items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            Compared against the S&amp;P 500 ({DEFAULT_BENCHMARK}).
          </p>
          <Button type="button" onClick={onRun} disabled={running}>
            {running ? "Running…" : "Run backtest"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium text-foreground">{label}</span>
      {children}
    </label>
  );
}

function SelectInput({
  className,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  // Native <select> styled with theme tokens — accessible by default
  // and keeps the page free of an extra primitive for the MVP.
  return (
    <select
      className={
        "h-10 w-full rounded-md border border-border bg-background px-3 text-sm text-foreground ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50" +
        (className ? ` ${className}` : "")
      }
      {...props}
    />
  );
}

// ── results ─────────────────────────────────────────────────────────

function Results({ result }: { result: BacktestResponse }) {
  const { stats, equity_curve, drawdown_series, benchmark_total_return } =
    result;

  return (
    <div className="space-y-6">
      <KpiRow stats={stats} />

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div className="space-y-1">
            <CardTitle>How your portfolio would have grown</CardTitle>
            <CardDescription>
              Starting from $1.00 · {fmtDate(result.start_date)} →{" "}
              {fmtDate(result.end_date)}
            </CardDescription>
          </div>
          <VsBenchmark
            portfolioReturn={stats.total_return}
            benchmarkReturn={benchmark_total_return}
            benchmark={result.benchmark}
          />
        </CardHeader>
        <CardContent>
          {equity_curve.length > 0 ? (
            <TimeSeriesChart
              data={equity_curve}
              variant="line"
              color="hsl(var(--primary))"
              valueFormatter={fmtMultiple}
              ariaLabel="Portfolio value over time"
            />
          ) : (
            <EmptyChartNote />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="space-y-1">
          <CardTitle>The bumps along the way</CardTitle>
          <CardDescription>
            How far your portfolio dropped below its previous high at each point
            — smaller dips are calmer.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {drawdown_series.length > 0 ? (
            <TimeSeriesChart
              data={drawdown_series}
              variant="area"
              color="hsl(var(--destructive))"
              valueFormatter={fmtPercent}
              ariaLabel="Drawdown over time"
            />
          ) : (
            <EmptyChartNote />
          )}
        </CardContent>
      </Card>

      <p className="text-center text-xs text-muted-foreground">
        Past performance doesn&apos;t predict future results. This is a
        simulation, not financial advice.
      </p>
    </div>
  );
}

function VsBenchmark({
  portfolioReturn,
  benchmarkReturn,
  benchmark,
}: {
  portfolioReturn: number | null;
  benchmarkReturn: number | null;
  benchmark: string;
}) {
  if (portfolioReturn == null || benchmarkReturn == null) return null;
  const diff = portfolioReturn - benchmarkReturn;
  const beat = diff >= 0;
  return (
    <span
      className={
        "shrink-0 rounded-full border px-2.5 py-1 text-xs font-medium " +
        (beat
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
          : "border-rose-500/40 bg-rose-500/10 text-rose-500")
      }
    >
      vs {benchmark} {beat ? "+" : ""}
      {fmtPercent(diff)}
    </span>
  );
}

// ── KPI cards ────────────────────────────────────────────────────────

function KpiRow({ stats }: { stats: BacktestResponse["stats"] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <KpiCard
        label="Total return"
        hint="How much your money would have grown overall."
        value={stats.total_return}
        format={fmtPercent}
        tone="signed"
      />
      <KpiCard
        label="Worst drop"
        hint="The biggest fall from a previous high along the way."
        value={stats.max_drawdown}
        format={fmtPercent}
        tone="bad"
      />
      <KpiCard
        label="Risk-adjusted return"
        hint="Return earned for the risk taken (Sharpe). Higher is better."
        value={stats.sharpe_ratio}
        format={fmtRatio}
        tone="signed"
      />
      <KpiCard
        label="Volatility"
        hint="How bumpy the ride was. Lower means steadier."
        value={stats.annual_volatility}
        format={fmtPercent}
        tone="neutral"
      />
    </div>
  );
}

function KpiCard({
  label,
  hint,
  value,
  format,
  tone,
}: {
  label: string;
  hint: string;
  value: number | null;
  format: (v: number) => string;
  /** signed = green/red by sign; bad = always red; neutral = plain. */
  tone: "signed" | "bad" | "neutral";
}) {
  let valueClass = "text-foreground";
  if (value != null) {
    if (tone === "bad") {
      valueClass = "text-rose-500";
    } else if (tone === "signed") {
      valueClass = value >= 0 ? "text-emerald-500" : "text-rose-500";
    }
  }

  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={"text-2xl font-semibold tabular-nums " + valueClass}>
          {value == null ? "—" : format(value)}
        </p>
        <p className="text-[11px] leading-snug text-muted-foreground">{hint}</p>
      </CardContent>
    </Card>
  );
}

// ── empty / loading / error states ───────────────────────────────────

function EmptyState() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ready when you are</CardTitle>
        <CardDescription>
          Pick a strategy and a time period, then hit Run backtest to see how
          your portfolio would have performed.
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

function EmptyChartNote() {
  return (
    <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
      Not enough history to chart this period.
    </div>
  );
}

function ResultSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="Running backtest">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i}>
            <CardContent className="space-y-2 p-4">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-7 w-24" />
              <Skeleton className="h-3 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader className="space-y-2">
          <Skeleton className="h-5 w-64" />
          <Skeleton className="h-3 w-40" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[280px] w-full" />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="space-y-2">
          <Skeleton className="h-5 w-48" />
          <Skeleton className="h-3 w-56" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-[280px] w-full" />
        </CardContent>
      </Card>
    </div>
  );
}

function ErrorNotice({ error }: { error: ApiError }) {
  if (error.code === "no_active_portfolio") {
    return (
      <NoticeCard
        title="Create a portfolio first"
        body="We need to know what you're holding before we can replay its history."
      >
        <Link href="/portfolios/new">
          <Button variant="outline" size="sm">
            Create a portfolio
          </Button>
        </Link>
      </NoticeCard>
    );
  }

  if (error.code === "no_priced_holdings") {
    return (
      <NoticeCard
        title="We couldn't price your holdings"
        body="None of your holdings have enough market-price history to backtest. Double-check the tickers in your portfolio, then try again."
      >
        <Link href="/portfolios">
          <Button variant="outline" size="sm">
            Review portfolio
          </Button>
        </Link>
      </NoticeCard>
    );
  }

  if (error.code === "unauthorized") {
    return (
      <NoticeCard
        title="Please sign in again"
        body="Your session expired. Sign back in to run a backtest."
      >
        <Link href="/login">
          <Button variant="outline" size="sm">
            Sign in
          </Button>
        </Link>
      </NoticeCard>
    );
  }

  return (
    <NoticeCard
      title="Something went wrong"
      body={
        error.code === "network_error"
          ? "Couldn't reach the backtester. Check your connection and try again."
          : "The backtest hit a snag. Please try again in a moment."
      }
    />
  );
}

function NoticeCard({
  title,
  body,
  children,
}: {
  title: string;
  body: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-card px-4 py-3 text-sm">
      <p className="font-medium text-foreground">{title}</p>
      <p className="text-muted-foreground">{body}</p>
      {children}
    </div>
  );
}

function ConfigureSupabaseNotice() {
  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Supabase not configured</CardTitle>
        <CardDescription>
          The backtester needs an authenticated Supabase session.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Set <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code className="font-mono">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in{" "}
          <code className="font-mono">.env.local</code>, then restart the dev
          server.
        </p>
        <Link href="/score">
          <Button variant="outline">Try the public /score demo</Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-28 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

// ── formatting helpers ───────────────────────────────────────────────

/** A fractional return (0.18) → "+18.0%". */
function fmtPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** A growth multiple (1.42) → "1.42×" for the equity-curve axis/tooltip. */
function fmtMultiple(value: number): string {
  return `${value.toFixed(2)}×`;
}

/** A unitless ratio (Sharpe 1.3) → "1.30". */
function fmtRatio(value: number): string {
  return value.toFixed(2);
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
