"use client";

/**
 * Signed-in home — the "why come back" dashboard.
 *
 * Surfaces the active portfolio's health score + the single biggest risk,
 * the live market regime, AI credits remaining, and a one-tap Copilot prompt,
 * with quick links into the rest of the app. Reuses existing hooks/components
 * (no new backend). Anonymous visitors get the marketing landing instead
 * (see app/page.tsx).
 */

import { useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Icon, type IconName } from "@/components/ui/icon";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketRegime } from "@/components/market-regime";
import { PortfolioValueSummary } from "@/components/portfolio-value-summary";
import dynamic from "next/dynamic";
import { ScoreGauge } from "@/components/score-gauge";
import { RiskDiagnosis } from "@/components/risk-diagnosis";
// Lazy-loaded: keeps recharts OUT of the `/` route bundle, which the anonymous
// SEO landing (also `/`) shares — only the signed-in dashboard pulls the chunk.
const AllocationDonut = dynamic(
  () => import("@/components/ui/allocation-donut").then((m) => m.AllocationDonut),
  { ssr: false },
);
const MiniSparkline = dynamic(
  () => import("@/components/ui/mini-sparkline").then((m) => m.MiniSparkline),
  { ssr: false },
);
import { track } from "@/lib/analytics";
import { isNoPortfolioError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useBillingMe,
  useLastSnapshot,
  useRiskExplain,
  useActiveScore,
  useSnapshotHistory,
} from "@/lib/queries";
import type { LastSnapshot } from "@/lib/queries";
import { explainInputFromScore } from "@/lib/risk-explain-input";
import type { ScoreResponse } from "@/lib/schemas";

const COPILOT_PROMPTS = [
  "Is my portfolio too risky?",
  "What's my biggest risk right now?",
  "How do I protect against a crash?",
];

export function Dashboard() {
  const { user } = useAuth();
  // Cached query: shared with /score, so navigating between them is instant
  // (no recompute / skeleton flash). Auto-fires when signed in.
  const score = useActiveScore();
  const billing = useBillingMe();
  const lastSnapshot = useLastSnapshot();
  const history = useSnapshotHistory();
  const scoreTrend = (history.data?.snapshots ?? [])
    .map((s) => s.overall_score)
    .filter((n): n is number => typeof n === "number");

  // Fire the funnel event once per score result (not on every render).
  const trackedScore = useRef<number | null>(null);
  useEffect(() => {
    if (score.data && trackedScore.current !== score.data.overall_score) {
      trackedScore.current = score.data.overall_score;
      track("score_viewed", { overall_score: Math.round(score.data.overall_score) });
    }
  }, [score.data]);

  // AI diagnosis from numbers we already have (auth-gated, cached per-input).
  const snapshot = lastSnapshot.data?.snapshot ?? null;
  const explainInput = useMemo(
    () => (score.data ? explainInputFromScore(score.data, snapshot) : null),
    [score.data, snapshot],
  );
  const explain = useRiskExplain(explainInput);

  const greeting = user?.email ? user.email.split("@")[0] : "there";

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">
          Welcome back, <span className="capitalize">{greeting}</span>
        </h1>
        <p className="text-sm text-muted-foreground">
          Your portfolio at a glance — and what to look at today.
        </p>
      </header>

      {score.isLoading && <HeroSkeleton />}

      {score.isError && <ScoreError error={score.error as Error} />}

      {score.data && (
        <>
          <ChangeSinceLastVisit current={score.data} prev={lastSnapshot.data?.snapshot} />
          <ScoreHero score={score.data} scoreTrend={scoreTrend} />
          <PortfolioValueSummary metrics={score.data.metrics} />
          <RiskDiagnosis explain={explain.data} loading={explain.isLoading} source="score" />
        </>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <MarketRegime />
        <CopilotCard credits={billing.data?.credits} />
      </div>

      <QuickLinks />
    </div>
  );
}

function ChangeSinceLastVisit({
  current,
  prev,
}: {
  current: ScoreResponse;
  prev: LastSnapshot["snapshot"] | undefined;
}) {
  if (!prev || prev.overall_score == null) return null;

  const now = Math.round(current.overall_score);
  const was = Math.round(prev.overall_score);
  const dScore = now - was;
  const curVol = current.metrics.annual_volatility;
  const prevVol = prev.annual_volatility;
  const curValue = current.metrics.net_equity ?? current.metrics.total_value;
  const prevValue = prev.net_equity;

  // No meaningful change to report.
  if (dScore === 0 && (curVol == null || prevVol == null)) return null;

  // A higher health score is good (green); a lower one is a heads-up (amber).
  const tone =
    dScore > 0
      ? "text-emerald-600 dark:text-emerald-400"
      : dScore < 0
        ? "text-amber-600 dark:text-amber-400"
        : "text-muted-foreground";
  const sign = dScore > 0 ? "+" : "";
  const since = prev.as_of ? fmtDate(prev.as_of) : "your last visit";

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-muted/30 px-4 py-2 text-sm">
      <span className="text-muted-foreground">Since {since}:</span>
      <span>
        Health <span className="font-medium">{was}</span> →{" "}
        <span className="font-medium">{now}</span>{" "}
        <span className={`font-medium ${tone}`}>
          ({sign}
          {dScore})
        </span>
      </span>
      {curVol != null && prevVol != null && (
        <span className="text-muted-foreground">
          · Volatility {(prevVol * 100).toFixed(1)}% → {(curVol * 100).toFixed(1)}%
        </span>
      )}
      {curValue != null && prevValue != null && (
        <span className="text-muted-foreground">
          · Value {fmtUSD(prevValue)} → {fmtUSD(curValue)}
        </span>
      )}
    </div>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "your last visit";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function ScoreHero({ score, scoreTrend }: { score: ScoreResponse; scoreTrend?: number[] }) {
  const tone = scoreTone(score.overall_score);
  const sectors = score.concentration?.sectors ?? [];
  const dims = Object.values(score.dimensions);
  const weakest = dims.length
    ? dims.reduce((a, b) => (b.score < a.score ? b : a))
    : null;

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 py-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-xs uppercase tracking-widest text-muted-foreground">
                Portfolio Health Score
              </p>
              <div className="flex items-baseline gap-2">
                <span
                  data-testid="dashboard-active-score"
                  className={`text-5xl font-semibold tabular-nums ${tone.text}`}
                >
                  {Math.round(score.overall_score)}
                </span>
                <span className="text-lg text-muted-foreground">/ 1000</span>
              </div>
              {scoreTrend && scoreTrend.length >= 2 && (
                <div className="mt-1 flex items-center gap-1.5">
                  <MiniSparkline data={scoreTrend} width={72} height={22} />
                  <span className="text-[10px] text-muted-foreground">score trend</span>
                </div>
              )}
            </div>
            <div className="flex gap-2">
              <Link href="/risk">
                <Button variant="outline" size="sm">
                  Full risk report
                </Button>
              </Link>
              <Link href="/scenarios">
                <Button variant="outline" size="sm">
                  Run scenarios
                </Button>
              </Link>
            </div>
          </div>
          <ScoreGauge score={score.overall_score} />
          {sectors.length > 0 && (
            <div className="border-t border-border pt-4">
              <p className="mb-2 text-xs uppercase tracking-widest text-muted-foreground">
                Sector allocation
              </p>
              <AllocationDonut
                slices={sectors.map((s) => ({ label: s.sector, weight: s.weight }))}
                centerTop={String(score.concentration?.num_holdings ?? "")}
                centerSub="holdings"
              />
            </div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-3">
        {dims.map((d) => (
          <Card key={d.name}>
            <CardHeader className="pb-2">
              <CardDescription>{d.name}</CardDescription>
              <CardTitle className="flex items-baseline gap-2 text-2xl">
                {d.score.toFixed(1)}
                <span className="text-sm font-normal text-muted-foreground">/ 10</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <span className={`text-xs font-medium ${statusTone(d.status)}`}>
                {d.status}
              </span>
            </CardContent>
          </Card>
        ))}
      </div>

      {weakest && (
        <Card className="border-amber-500/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              Focus first: {weakest.name}
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {weakest.detail}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function CopilotCard({ credits }: { credits?: { unlimited?: boolean; credits_remaining?: number | null } | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Ask your Copilot</CardTitle>
        <CardDescription>
          Plain-English answers grounded in your real numbers.
          {credits && !credits.unlimited && credits.credits_remaining != null && (
            <> {credits.credits_remaining} AI credits left this month.</>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {COPILOT_PROMPTS.map((q) => (
          <Link
            key={q}
            href={`/copilot?q=${encodeURIComponent(q)}`}
            className="block rounded-md border border-border px-3 py-2 text-sm hover:bg-accent hover:text-accent-foreground"
          >
            {q}
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

function QuickLinks() {
  const links: { href: string; label: string; desc: string; icon: IconName }[] = [
    { href: "/portfolios", label: "Holdings", desc: "Edit your positions", icon: "holdings" },
    { href: "/research", label: "Stock research", desc: "Any-ticker deep dive", icon: "research" },
    { href: "/quant", label: "Backtest", desc: "How a strategy held up", icon: "scenarios" },
    { href: "/markets", label: "Markets", desc: "The risk climate today", icon: "trend-up" },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {links.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className="rounded-lg border border-border p-4 transition hover:border-primary/40 hover:bg-accent/40"
        >
          <Icon name={l.icon} className="h-5 w-5 text-primary" />
          <div className="mt-2 text-sm font-medium">{l.label}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{l.desc}</div>
        </Link>
      ))}
    </div>
  );
}

function ScoreError({ error }: { error: Error }) {
  // New users (no portfolio yet) get a guided 3-step start — the activation
  // hook. A genuine error (not "no portfolio") shows a calm retry message.
  if (isNoPortfolioError(error)) return <OnboardingGuide />;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Couldn&apos;t load your score</CardTitle>
        <CardDescription>Your data is safe — try refreshing in a moment.</CardDescription>
      </CardHeader>
    </Card>
  );
}

function OnboardingGuide() {
  const steps = [
    {
      n: 1,
      title: "Add your holdings",
      body: "Tickers + shares (avg cost optional). Takes about a minute.",
      cta: { href: "/portfolios/new", label: "Add holdings" },
      active: true,
    },
    {
      n: 2,
      title: "See your Health Score",
      body: "A 0–1000 score + your biggest risk, the moment your holdings are in.",
    },
    {
      n: 3,
      title: "Ask your Copilot",
      body: "Plain-English answers about your risk — grounded in your real numbers.",
    },
  ];
  return (
    <Card className="border-primary/30">
      <CardHeader>
        <CardTitle>Welcome — let&apos;s get your first score</CardTitle>
        <CardDescription>Three quick steps to your institutional-grade risk view.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {steps.map((s) => (
          <div
            key={s.n}
            className={`flex items-start gap-3 rounded-lg border p-3 ${
              s.active ? "border-primary/40 bg-primary/5" : "border-border"
            }`}
          >
            <div
              className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-sm font-semibold ${
                s.active
                  ? "bg-primary text-primary-foreground"
                  : "border border-border text-muted-foreground"
              }`}
            >
              {s.n}
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{s.title}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">{s.body}</div>
            </div>
            {s.cta && (
              <Link href={s.cta.href}>
                <Button size="sm">{s.cta.label}</Button>
              </Link>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function HeroSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-28 w-full" />
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    </div>
  );
}

function scoreTone(v: number): { text: string } {
  if (v >= 700) return { text: "text-emerald-600 dark:text-emerald-400" };
  if (v >= 400) return { text: "text-amber-600 dark:text-amber-400" };
  return { text: "text-red-600 dark:text-red-400" };
}

function statusTone(status: string): string {
  const s = status.toLowerCase();
  if (s.includes("strong") || s.includes("good") || s.includes("healthy"))
    return "text-emerald-600 dark:text-emerald-400";
  if (s.includes("weak") || s.includes("poor") || s.includes("high risk"))
    return "text-red-600 dark:text-red-400";
  return "text-amber-600 dark:text-amber-400";
}

function fmtUSD(v: number): string {
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
