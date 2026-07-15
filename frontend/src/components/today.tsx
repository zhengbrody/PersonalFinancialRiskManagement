"use client";

/**
 * Today — the signed-in home. NOT a long report: a focused action center that
 * points at the single most useful next step (a DETERMINISTIC priority engine,
 * never the LLM), plus since-last-visit, up to two secondary items, a
 * continue-a-plan nudge, the onboarding journey (next step only), and a compact
 * market brief. Every CTA deep-links into the right Analyze stage / portfolio.
 */

import { useEffect, useRef } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoreGauge } from "@/components/score-gauge";
import { MarketRegime } from "@/components/market-regime";
import { track } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { usePortfolioContext } from "@/lib/portfolio-context";
import {
  computePrimaryAction,
  computeSecondary,
  journeySteps,
  type TodayInputs,
} from "@/lib/today-priority";
import {
  useActiveScore,
  useCopilotInsights,
  useJourney,
  useLastSnapshot,
  useRiskPlans,
} from "@/lib/queries";

const SCORE_DROP_PTS = 25;

function planDue(p: { review_at?: string | null; status: string }): boolean {
  if (!p.review_at || p.status === "resolved" || p.status === "archived") return false;
  const t = new Date(p.review_at).getTime();
  return Number.isFinite(t) && t <= Date.now();
}

export function Today() {
  const { user } = useAuth();
  const { hasPortfolios, current, activePortfolioId, isLoading: pfLoading } = usePortfolioContext();
  const score = useActiveScore();
  const journey = useJourney();
  const plans = useRiskPlans(activePortfolioId);
  const insights = useCopilotInsights();
  const lastSnapshot = useLastSnapshot();

  const greeting = user?.email ? user.email.split("@")[0] : "there";

  // ── deterministic inputs (no LLM) ──────────────────────────────────
  const hasHoldings = current
    ? Object.keys((current as { holdings?: Record<string, unknown> }).holdings ?? {}).length > 0
    : false;
  const conf = score.data?.metrics?.confidence;
  const dataStale =
    conf === "low" || (score.data?.data_confidence as { stale?: boolean } | undefined)?.stale === true;
  const dueReviewCount = (plans.data?.plans ?? []).filter(planDue).length;
  const hasMaterialInsight =
    Boolean(insights.data?.portfolio_available) &&
    (insights.data?.insights ?? []).some((i) => i.severity === "high");
  const prevScore = lastSnapshot.data?.snapshot?.overall_score;
  const curScore = score.data?.overall_score;
  const scoreDropped =
    typeof prevScore === "number" &&
    typeof curScore === "number" &&
    curScore - prevScore <= -SCORE_DROP_PTS;
  const hasStressTest = Boolean(journey.data?.first_stress_test_at);
  const hasPlan = Boolean(journey.data?.first_plan_at);
  const hasScore = Boolean(journey.data?.first_score_at) || Boolean(score.data);
  const hasDriverView = Boolean(journey.data?.first_driver_viewed_at);

  const inputs: TodayInputs = {
    hasPortfolio: hasPortfolios,
    hasHoldings,
    dataStale: Boolean(dataStale),
    dueReviewCount,
    hasMaterialInsight,
    scoreDropped,
    hasStressTest,
    hasPlan,
    activePortfolioId,
  };
  const primary = computePrimaryAction(inputs);
  const secondary = computeSecondary(inputs, primary.kind);
  const journeyState = journeySteps({ hasPortfolio: hasPortfolios, hasScore, hasDriverView, hasStressTest, hasPlan });
  const continuePlan = (plans.data?.plans ?? []).find(
    (p) => p.status === "active" || p.status === "draft",
  );

  // Only emit the analytics event ONCE the inputs have settled — otherwise the
  // primary flips as queries hydrate and we'd fire a premature/duplicate kind.
  const inputsReady =
    !pfLoading &&
    !score.isLoading &&
    !plans.isLoading &&
    !insights.isLoading &&
    !lastSnapshot.isLoading;
  const tracked = useRef<string | null>(null);
  useEffect(() => {
    if (inputsReady && tracked.current !== primary.kind) {
      tracked.current = primary.kind;
      track("today_primary_action", { kind: primary.kind });
    }
  }, [inputsReady, primary.kind]);

  if (pfLoading || (hasPortfolios && score.isLoading)) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">
          Hi, <span className="capitalize">{greeting}</span>
        </h1>
        <p className="text-sm text-muted-foreground">Here&apos;s what to look at today.</p>
      </header>

      {/* Since last visit — a one-line delta, only when we have both points AND
          the primary isn't already the "explain the drop" card (no double message). */}
      {primary.kind !== "explain_change" &&
        typeof prevScore === "number" &&
        typeof curScore === "number" && <SinceLastVisit prev={prevScore} cur={curScore} />}

      {/* The ONE primary action. */}
      <Card className="border-primary/30">
        <CardHeader className="pb-2">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">Do this next</p>
          <CardTitle className="text-lg">{primary.title}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-xl text-sm text-muted-foreground">{primary.description}</p>
          <Link href={primary.href}>
            <Button size="lg">{primary.cta}</Button>
          </Link>
        </CardContent>
      </Card>

      {/* Compact score — hidden when the data is stale (the primary already says
          "metrics can't be trusted yet", so don't headline a number). */}
      {score.data && !inputs.dataStale && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-6 py-4">
            <ScoreGauge score={score.data.overall_score} className="w-40" />
            <div className="space-y-1 text-sm text-muted-foreground">
              <span data-testid="dashboard-active-score" className="block text-2xl font-semibold text-foreground tabular-nums">
                {Math.round(score.data.overall_score)}
              </span>
              <Link href="/analyze?view=overview" className="font-medium text-primary hover:underline">
                Open the full workspace →
              </Link>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Up to two secondary items. */}
      {secondary.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {secondary.map((a) => (
            <Link key={a.kind + a.href} href={a.href} className="block">
              <Card className="h-full transition-colors hover:border-primary/40">
                <CardContent className="py-3">
                  <p className="text-sm font-medium">{a.title}</p>
                  <p className="text-xs text-muted-foreground">{a.description}</p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}

      {/* Continue a plan you left in progress. */}
      {continuePlan && (
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div className="min-w-0">
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Continue where you left off
              </p>
              <p className="truncate text-sm font-medium">{continuePlan.title}</p>
            </div>
            <Link href="/analyze?view=plan">
              <Button variant="outline" size="sm">
                Open plan
              </Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {/* Onboarding journey — only while not complete; highlight the NEXT step,
          collapse the rest. No streaks/points/badges. */}
      {!journeyState.allDone && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Getting started</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="space-y-1.5 text-sm">
              {journeyState.steps.map((s, idx) => {
                const isNext = idx === journeyState.nextIndex;
                return (
                  <li key={s.key} className="flex items-center gap-2">
                    <span
                      aria-hidden
                      className={`inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] ${
                        s.done
                          ? "bg-emerald-500 text-white"
                          : isNext
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {s.done ? "✓" : idx + 1}
                    </span>
                    {isNext ? (
                      <Link href={s.href} className="font-medium text-primary hover:underline">
                        {s.label} →
                      </Link>
                    ) : (
                      <span className={s.done ? "text-muted-foreground line-through" : "text-muted-foreground"}>
                        {s.label}
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </CardContent>
        </Card>
      )}

      {/* Market brief — a summary, not the star of the page. */}
      <MarketRegime />
    </div>
  );
}

function SinceLastVisit({ prev, cur }: { prev: number; cur: number }) {
  const delta = Math.round(cur - prev);
  if (delta === 0) return null;
  const up = delta > 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <Badge tone={up ? "success" : "danger"}>
        {up ? "▲" : "▼"} {Math.abs(delta)} pts
      </Badge>
      <span className="text-muted-foreground">
        Your health score is {up ? "up" : "down"} since your last visit.{" "}
        <Link href="/analyze?view=history" className="font-medium text-primary hover:underline">
          See what changed →
        </Link>
      </span>
    </div>
  );
}
