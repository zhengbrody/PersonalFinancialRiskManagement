"use client";

/**
 * Today — the signed-in home. NOT a long report: a focused action center that
 * points at the single most useful next step (a DETERMINISTIC priority engine,
 * never the LLM), plus since-last-visit, up to two secondary items, a
 * continue-a-plan nudge, the onboarding journey (next step only), and a compact
 * market brief. Every CTA deep-links into the right Analyze stage / portfolio.
 */

import { useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoreGauge } from "@/components/score-gauge";
import { WorkspaceIcon } from "@/components/ui/workspace-icon";
import { MarketRegime } from "@/components/market-regime";
import { track } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { currentUsername } from "@/lib/user-display";
import {
  computePrimaryAction,
  computeSecondary,
  journeySteps,
  type TodayInputs,
} from "@/lib/today-priority";
import {
  useActiveScore,
  useCopilotPreferences,
  useCopilotInsights,
  useJourney,
  useRiskPlans,
  useScoreChanges,
} from "@/lib/queries";
import type { ScoreChangeReport } from "@/lib/queries";
import { scoreChangeInput } from "@/lib/score-change-input";

const SCORE_DROP_PTS = 25;

function planDue(p: { review_at?: string | null; status: string }): boolean {
  if (!p.review_at || p.status === "resolved" || p.status === "archived")
    return false;
  const t = new Date(p.review_at).getTime();
  return Number.isFinite(t) && t <= Date.now();
}

export function Today() {
  const { user } = useAuth();
  const {
    hasPortfolios,
    current,
    activePortfolioId,
    isLoading: pfLoading,
  } = usePortfolioContext();
  const score = useActiveScore();
  const journey = useJourney();
  const plans = useRiskPlans(activePortfolioId);
  const insights = useCopilotInsights();
  const riskFit = useCopilotPreferences();
  const changeBody = useMemo(
    () => (score.data ? scoreChangeInput(score.data, "previous") : null),
    [score.data],
  );
  const scoreChanges = useScoreChanges(changeBody);

  // Never derive the greeting from the email address — the whole point of
  // `displayName`/`currentUsername` is that the chrome shows the name the user
  // chose on /settings, and nothing at all when they haven't chosen one.
  const greeting = (user ? currentUsername(user) : "") || "there";

  // ── deterministic inputs (no LLM) ──────────────────────────────────
  const hasHoldings = current
    ? Object.keys(
        (current as { holdings?: Record<string, unknown> }).holdings ?? {},
      ).length > 0
    : false;
  const conf = score.data?.metrics?.confidence;
  const dataStale =
    conf === "low" ||
    (score.data?.data_confidence as { stale?: boolean } | undefined)?.stale ===
      true;
  const dueReviewCount = (plans.data?.plans ?? []).filter(planDue).length;
  const hasMaterialInsight =
    Boolean(insights.data?.portfolio_available) &&
    (insights.data?.insights ?? []).some((i) => i.severity === "high");
  const changeReport = scoreChanges.data;
  const scoreDropped =
    changeReport?.available === true &&
    changeReport.comparable !== false &&
    typeof changeReport.score_delta === "number" &&
    changeReport.score_delta <= -SCORE_DROP_PTS;
  const hasStressTest = Boolean(journey.data?.first_stress_test_at);
  // Milestones are stamped server-side at the product event; the live plans
  // list is the fallback for plans saved before stamping existed.
  const hasPlan =
    Boolean(journey.data?.first_plan_at) ||
    (plans.data?.plans ?? []).length > 0;
  // A calculated score is not the same as a score the user has reviewed.
  // The Overview stage records this milestone only after it renders a real
  // active-book score; Today's background query must not advance the journey.
  const hasScore = Boolean(journey.data?.first_score_at);
  const hasDriverView = Boolean(journey.data?.first_driver_viewed_at);
  const hasPlanReviewed = Boolean(journey.data?.first_plan_reviewed_at);
  const hasRiskFit =
    Boolean(riskFit.data?.confirmed) && riskFit.data?.risk_tolerance != null;

  const inputs: TodayInputs = {
    hasPortfolio: hasPortfolios,
    hasHoldings,
    dataStale: Boolean(dataStale),
    dueReviewCount,
    hasMaterialInsight,
    scoreDropped,
    hasRiskFit,
    hasScore,
    hasDriverView,
    hasStressTest,
    hasPlan,
    activePortfolioId,
  };
  const primary = computePrimaryAction(inputs);
  const secondary = computeSecondary(inputs, primary.kind);
  const journeyState = journeySteps({
    hasPortfolio: hasPortfolios,
    hasRiskFit,
    hasScore,
    hasDriverView,
    hasStressTest,
    hasPlan,
    hasPlanReviewed,
  });
  const continuePlan = (plans.data?.plans ?? []).find(
    (p) => p.status === "active" || p.status === "draft",
  );

  // Only emit the analytics event ONCE the inputs have settled — otherwise the
  // primary flips as queries hydrate and we'd fire a premature/duplicate kind.
  const inputsReady =
    !pfLoading &&
    !score.isLoading &&
    !journey.isLoading &&
    !riskFit.isLoading &&
    !plans.isLoading &&
    !insights.isLoading &&
    !scoreChanges.isLoading;
  const tracked = useRef<string | null>(null);
  useEffect(() => {
    if (inputsReady && tracked.current !== primary.kind) {
      tracked.current = primary.kind;
      track("today_primary_action", { kind: primary.kind });
    }
  }, [inputsReady, primary.kind]);

  if (pfLoading || (hasPortfolios && !inputsReady)) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  // A score failure is blocking: without the current score, Today cannot
  // truthfully prioritize data quality, changes or the next analysis step.
  // Do not reinterpret it as an empty portfolio or manufacture a CTA.
  if (hasPortfolios && score.isError) {
    return (
      <div className="space-y-6">
        <TodayHeader greeting={greeting} />
        <Card className="border-destructive/50" role="alert">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              Today could not load your current score
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-muted-foreground">
              Nothing was changed in your portfolio, but we can&apos;t assess
              today&apos;s risk until the score loads.
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => void score.refetch()}
            >
              Retry score
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const loadIssues: LoadIssue[] = [
    ...(journey.isError
      ? [
          {
            label: "setup progress",
            retry: () => {
              void journey.refetch();
            },
          },
        ]
      : []),
    ...(riskFit.isError
      ? [
          {
            label: "Risk Fit status",
            retry: () => {
              void riskFit.refetch();
            },
          },
        ]
      : []),
    ...(plans.isError
      ? [
          {
            label: "saved plans",
            retry: () => {
              void plans.refetch();
            },
          },
        ]
      : []),
    ...(insights.isError
      ? [
          {
            label: "portfolio insights",
            retry: () => {
              void insights.refetch();
            },
          },
        ]
      : []),
    ...(scoreChanges.isError
      ? [
          {
            label: "score changes",
            retry: () => {
              void scoreChanges.refetch();
            },
          },
        ]
      : []),
  ];

  // Every one of these queries participates in the deterministic priority
  // order. If any is unavailable, fail closed instead of treating unknown as
  // empty and manufacturing a normal-looking recommendation.
  if (hasPortfolios && loadIssues.length > 0) {
    return (
      <div className="space-y-6">
        <TodayHeader greeting={greeting} />
        <LoadStatus issues={loadIssues} blocking />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <TodayHeader greeting={greeting} />

      {loadIssues.length > 0 && <LoadStatus issues={loadIssues} />}

      {/* Since last visit — a one-line delta, only when we have both points AND
          the primary isn't already the "explain the drop" card (no double message). */}
      {primary.kind !== "explain_change" &&
        changeReport?.available === true && (
          <SinceLastVisit report={changeReport} />
        )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        {/* The ONE primary action; retain the deterministic priority engine. */}
        <Card className="flex flex-col justify-between border-primary/20 bg-primary/[0.04]">
          <CardHeader className="pb-3 sm:p-8">
            <p className="text-xs font-medium uppercase tracking-widest text-primary">
              Do this next
            </p>
            <CardTitle className="max-w-lg text-2xl leading-tight sm:text-3xl">
              {primary.title}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5 sm:px-8 sm:pb-8">
            <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
              {primary.description}
            </p>
            <Link
              href={primary.href}
              className="inline-flex min-h-11 items-center justify-center gap-3 rounded-full bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              {primary.cta}
              <WorkspaceIcon name="arrow" className="h-4 w-4" />
            </Link>
          </CardContent>
        </Card>

        {/* Compact score — hidden when the data is stale (the primary already says
          "metrics can't be trusted yet", so don't headline a number). */}
        {score.data && !inputs.dataStale && (
          <Card>
            <CardContent className="space-y-5 py-6 sm:p-8">
              <p className="text-sm font-medium text-muted-foreground">
                Portfolio health · {current?.name ?? "Active portfolio"}
              </p>
              <div className="flex items-baseline gap-2">
                <span
                  data-testid="dashboard-active-score"
                  className="text-6xl font-semibold tracking-tight text-foreground tabular-nums"
                >
                  {Math.round(score.data.overall_score)}
                </span>
                <span className="text-sm text-muted-foreground">/ 1,000</span>
              </div>
              <ScoreGauge score={score.data.overall_score} />
              <div className="text-sm text-muted-foreground">
                <Link
                  href="/analyze?view=overview"
                  className="font-medium text-primary hover:underline"
                >
                  Open the full workspace →
                </Link>
              </div>
            </CardContent>
          </Card>
        )}
        {(!score.data || inputs.dataStale) && (
          <Card className="flex items-center">
            <CardContent className="space-y-3 py-6 sm:p-8">
              <p className="text-sm font-medium">
                A clear picture starts with your holdings.
              </p>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {inputs.dataStale
                  ? "Current data needs attention. Review coverage before relying on a headline risk score."
                  : "Add a portfolio, review its risk, then test a change without changing your actual positions."}
              </p>
              <Link
                href="/portfolios"
                className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-primary"
              >
                Review holdings{" "}
                <WorkspaceIcon name="arrow" className="h-4 w-4" />
              </Link>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Up to two secondary items. */}
      {secondary.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {secondary.map((a) => (
            <Link key={a.kind + a.href} href={a.href} className="block">
              <Card className="h-full transition-colors hover:border-primary/40">
                <CardContent className="flex items-start justify-between gap-4 py-5">
                  <div className="space-y-1">
                    <p className="text-sm font-medium">{a.title}</p>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {a.description}
                    </p>
                  </div>
                  <WorkspaceIcon
                    name="arrow"
                    className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                  />
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
              <p className="truncate text-sm font-medium">
                {continuePlan.title}
              </p>
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
      {!journey.isError && !riskFit.isError && !journeyState.allDone && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Getting started</CardTitle>
            <p className="text-xs text-muted-foreground">
              Account-level milestones — the &quot;do this next&quot; card above
              always applies to your active portfolio.
            </p>
          </CardHeader>
          <CardContent>
            <details>
              <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">
                View setup checklist{" "}
                <span className="ml-2 font-normal text-muted-foreground">
                  {journeyState.steps.filter((step) => step.done).length} /{" "}
                  {journeyState.steps.length} completed
                </span>
              </summary>
              <ol
                className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-3"
                aria-label="Getting started progress"
              >
                {journeyState.steps.map((s, idx) => {
                  const isNext = idx === journeyState.nextIndex;
                  return (
                    <li
                      key={s.key}
                      className={`flex min-h-12 items-center gap-3 rounded-xl p-3 ${isNext ? "bg-primary/5 ring-1 ring-primary/20" : "bg-muted/30"}`}
                    >
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
                      <span className="sr-only">
                        {s.done
                          ? "Completed: "
                          : isNext
                            ? "Next: "
                            : "Not completed: "}
                      </span>
                      {isNext ? (
                        <Link
                          href={s.href}
                          className="font-medium text-primary hover:underline"
                        >
                          {s.label} →
                        </Link>
                      ) : (
                        <span
                          className={
                            s.done
                              ? "text-muted-foreground line-through"
                              : "text-muted-foreground"
                          }
                        >
                          {s.label}
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </details>
          </CardContent>
        </Card>
      )}

      {/* Market context is secondary to the user's portfolio, available on demand. */}
      <details className="group rounded-2xl border border-border bg-card p-5">
        <summary className="cursor-pointer text-sm font-medium">
          Market context{" "}
          <span className="ml-2 font-normal text-muted-foreground">
            VIX, sentiment &amp; rates
          </span>
        </summary>
        <div className="pt-5">
          <MarketRegime />
        </div>
      </details>
    </div>
  );
}

function TodayHeader({ greeting }: { greeting: string }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          Your daily risk check
        </p>
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Hi, <span className="capitalize">{greeting}</span>
        </h1>
        <p className="text-sm text-muted-foreground">
          Here&apos;s what to look at today.
        </p>
      </div>
      <Link
        href="/analyze?view=overview"
        className="workspace-nav-link gap-2 border border-border bg-card"
      >
        Analyze portfolio <WorkspaceIcon name="arrow" className="h-4 w-4" />
      </Link>
    </header>
  );
}

type LoadIssue = { label: string; retry: () => void };

function LoadStatus({
  issues,
  blocking = false,
}: {
  issues: LoadIssue[];
  blocking?: boolean;
}) {
  return (
    <Card
      className="border-amber-400/40"
      role={blocking ? "alert" : "status"}
      aria-live="polite"
    >
      <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
        <p className="text-sm text-muted-foreground">
          Today can&apos;t rank your next action because some context is
          unavailable ({issues.map((i) => i.label).join(", ")}). Reload it
          before relying on a suggestion.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => issues.forEach((issue) => issue.retry())}
        >
          Reload Today context
        </Button>
      </CardContent>
    </Card>
  );
}

function SinceLastVisit({ report }: { report: ScoreChangeReport }) {
  const delta =
    report.score_delta == null ? null : Math.round(report.score_delta);
  const driver =
    delta != null && delta >= 0
      ? report.top_positive_contributor
      : report.top_negative_contributor;
  if (!report.summary) return null;
  if (report.comparable === false || delta == null) {
    return (
      <div className="text-sm text-muted-foreground" role="status">
        {report.summary}{" "}
        <Link
          href="/analyze?view=history"
          className="font-medium text-primary hover:underline"
        >
          Review history →
        </Link>
      </div>
    );
  }
  if (delta === 0 && !driver) return null;
  const up = delta > 0;
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm" role="status">
      <Badge tone={up ? "success" : "danger"}>
        {up ? "▲" : "▼"} {Math.abs(delta)} pts
      </Badge>
      <span className="text-muted-foreground">
        {report.summary}
        {driver ? ` Top driver: ${driver.label}.` : ""}{" "}
        <Link
          href="/analyze?view=history"
          className="font-medium text-primary hover:underline"
        >
          See what changed →
        </Link>
      </span>
    </div>
  );
}
