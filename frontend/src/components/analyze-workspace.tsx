"use client";

/**
 * The unified /analyze workspace — the primary risk-analysis surface for a
 * signed-in user. Five URL-tabbed stages follow the journey: Overview →
 * Drivers → Stress Test → Action Plan → History. Each stage loads its data on
 * FIRST open (visited stages stay mounted+hidden so returning is instant and
 * doesn't refetch); the tab lives in ?view= so browser back/forward works.
 *
 * Everything reuses existing components (ScoreGauge, RiskDiagnosis, the risk
 * ReportSections, HistoricalScenarios, MetricTrend, ScoreChangeReport,
 * ActionSimulate) plus the shared What-if lab + risk-plans panel. No risk math
 * lives here; simulations are clearly marked and never change holdings.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { WorkspaceIcon } from "@/components/ui/workspace-icon";
import { RiskSnapshot } from "@/components/risk-snapshot";
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoreGauge, scoreBand } from "@/components/score-gauge";
import { RiskDiagnosis } from "@/components/risk-diagnosis";
import { DataConfidence } from "@/components/data-confidence";
import {
  ReportSections,
  ResultSkeleton,
  RiskErrorPanel,
} from "@/components/risk-report";
import { HistoricalScenarios } from "@/components/historical-scenarios";
import { MetricTrend } from "@/components/metric-trend";
import { ScoreChangeReport } from "@/components/score-change-report";
import { ActionSimulate } from "@/components/action-simulate";
import { WhatIfLab } from "@/components/whatif-lab";
import { RiskPlansPanel } from "@/components/risk-plans-panel";
import { track } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { authHref } from "@/lib/auth-redirect";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { explainInputFromScore } from "@/lib/risk-explain-input";
import {
  runKeyForActivePortfolio,
  useRunOncePerUser,
} from "@/lib/use-run-once-per-user";
import type { ScoreResponse } from "@/lib/schemas";
import {
  useActiveScore,
  useHistoricalScenarios,
  useLastSnapshot,
  useRecordMilestone,
  useRiskExplain,
  useRiskReport,
} from "@/lib/queries";

const VIEWS = [
  { value: "overview", label: "Overview" },
  { value: "drivers", label: "Drivers" },
  { value: "stress", label: "Stress Test" },
  { value: "plan", label: "Action Plan" },
  { value: "history", label: "History" },
] as const;
type View = (typeof VIEWS)[number]["value"];
const isView = (v: string | null): v is View =>
  VIEWS.some((x) => x.value === v);

const STAGE_GUIDE: Record<
  View,
  { title: string; description: string; next: View; cta: string }
> = {
  overview: {
    title: "Understand your starting point",
    description:
      "Account context, portfolio health, and the risk that deserves your attention first.",
    next: "drivers",
    cta: "Explore risk drivers",
  },
  drivers: {
    title: "See what is driving risk",
    description:
      "Inspect concentrations, exposures, and loss estimates before choosing a scenario.",
    next: "stress",
    cta: "Test a scenario",
  },
  stress: {
    title: "Explore the downside before it happens",
    description:
      "Compare hypothetical changes and historical shocks. Simulations never change your holdings.",
    next: "plan",
    cta: "Review action plans",
  },
  plan: {
    title: "Turn analysis into a reviewable plan",
    description:
      "Compare alternatives, save your assumptions, and decide when to revisit them. No trades are placed.",
    next: "history",
    cta: "Review risk history",
  },
  history: {
    title: "Understand what changed",
    description:
      "Review recorded risk trends and score changes. Tracked history is not a reconstructed broker return.",
    next: "overview",
    cta: "Back to overview",
  },
};

export function AnalyzeWorkspace() {
  const router = useRouter();
  const search = useSearchParams();
  const { user, loading, configured } = useAuth();
  const { current } = usePortfolioContext();
  const recordMilestone = useRecordMilestone();

  const raw = search.get("view");
  const view: View = isView(raw) ? raw : "overview";
  const [visited, setVisited] = useState<Set<View>>(() => new Set([view]));

  useEffect(() => {
    if (!configured) return;
    if (!loading && !user) {
      router.replace(authHref("/login", `/analyze?view=${view}`));
    }
  }, [user, loading, configured, router, view]);

  // Record the workspace visit once per mount (last_workspace_view always).
  const recordedRef = useRef(false);
  useEffect(() => {
    if (user && !recordedRef.current) {
      recordedRef.current = true;
      recordMilestone.mutate("last_workspace_view");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    setVisited((prev) => (prev.has(view) ? prev : new Set(prev).add(view)));
  }, [view]);

  function setView(next: string) {
    if (!isView(next) || next === view) return;
    const params = new URLSearchParams(Array.from(search.entries()));
    params.set("view", next);
    // push (not replace) so browser Back/Forward steps through the stages.
    router.push(`/analyze?${params.toString()}`);
    track("analyze_view_changed", { view: next });
  }

  if (!configured || loading || !user) return <WorkspaceSkeleton />;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Risk workspace
          </p>
          <h1 className="break-words text-3xl font-semibold tracking-tight sm:text-4xl">
            {current ? current.name : "Analyze"}
          </h1>
          <p className="text-sm text-muted-foreground">
            One workspace. From understanding risk to testing your next move.
          </p>
        </div>
        <Link
          href="/portfolios"
          className="workspace-nav-link border border-border bg-card"
        >
          Manage holdings
        </Link>
      </header>

      <div className="overflow-x-auto">
        <Tabs
          items={VIEWS}
          value={view}
          onValueChange={setView}
          idBase={TAB_BASE}
          className="flex w-full rounded-2xl p-1.5 [&>button]:flex-1"
        />
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-5">
        <div className="max-w-2xl space-y-1">
          <h2 className="text-lg font-semibold tracking-tight">
            {STAGE_GUIDE[view].title}
          </h2>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {STAGE_GUIDE[view].description}
          </p>
        </div>
        <span className="rounded-full bg-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
          {VIEWS.findIndex((item) => item.value === view) + 1} / 5 views
        </span>
      </div>

      {/* Visited stages stay mounted (hidden) so returning is instant + no refetch. */}
      {visited.has("overview") && (
        <StagePanel view="overview" active={view === "overview"}>
          <OverviewStage
            onFirstLoad={() => {
              recordMilestone.mutate("first_score_at");
              track("journey_step_completed", { step: "score" });
            }}
          />
        </StagePanel>
      )}
      {visited.has("drivers") && (
        <StagePanel view="drivers" active={view === "drivers"}>
          <DriversStage
            onFirstLoad={() => {
              // The successful report response stamps this milestone on the
              // server.  The browser records analytics only; it cannot claim
              // that a deterministic driver report completed.
              track("journey_step_completed", { step: "drivers" }); // stage enum only
            }}
          />
        </StagePanel>
      )}
      {visited.has("stress") && (
        <StagePanel view="stress" active={view === "stress"}>
          <StressStage
            onFirstRun={() => {
              recordMilestone.mutate("first_stress_test_at");
              track("journey_step_completed", { step: "stress" }); // stage enum only
            }}
          />
        </StagePanel>
      )}
      {visited.has("plan") && (
        <StagePanel view="plan" active={view === "plan"}>
          <PlanStage />
        </StagePanel>
      )}
      {visited.has("history") && (
        <StagePanel view="history" active={view === "history"}>
          <HistoryStage />
        </StagePanel>
      )}
      <footer className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-card p-5">
        <p className="text-sm text-muted-foreground">
          Explore at your own pace. Your holdings stay unchanged.
        </p>
        <Button
          variant="outline"
          onClick={() => setView(STAGE_GUIDE[view].next)}
        >
          {STAGE_GUIDE[view].cta}
          <WorkspaceIcon name="arrow" className="h-4 w-4" />
        </Button>
      </footer>
    </div>
  );
}

const TAB_BASE = "analyze";

function StagePanel({
  view,
  active,
  children,
}: {
  view: View;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      id={tabPanelId(TAB_BASE, view)}
      aria-labelledby={tabId(TAB_BASE, view)}
      hidden={!active}
      className={active ? "" : "hidden"}
    >
      {children}
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────

function OverviewStage({ onFirstLoad }: { onFirstLoad: () => void }) {
  const score = useActiveScore();
  const snapshot = useLastSnapshot();
  const firedRef = useRef(false);
  const explainInput = useMemo(
    () =>
      score.data ? explainInputFromScore(score.data, snapshot.data) : null,
    [score.data, snapshot.data],
  );
  const explain = useRiskExplain(explainInput);

  useEffect(() => {
    if (score.data && !firedRef.current) {
      firedRef.current = true;
      onFirstLoad();
    }
  }, [score.data, onFirstLoad]);

  if (score.isLoading) return <Skeleton className="h-64 w-full" />;
  if (score.isError) return <RiskErrorPanel error={score.error as Error} />;
  const s = score.data;
  if (!s) return <NoPortfolio />;
  const weakest = weakestDimension(s);
  return (
    <div className="space-y-4">
      <RiskSnapshot metrics={s.metrics} />
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          {/* The headline number leads, then the band — same shape as the
              /score hero. ScoreGauge only draws the band + marker, so the
              caller always renders the score itself. */}
          <CardContent className="space-y-3 py-6">
            <p className="text-sm font-medium text-muted-foreground">
              Portfolio health score
            </p>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span
                data-testid="analyze-overall-score"
                className="text-6xl font-semibold tracking-tight text-foreground tabular-nums"
              >
                {Math.round(s.overall_score)}
              </span>
              <span className="text-base text-muted-foreground">/ 1000</span>
              <span
                className={`text-sm font-semibold uppercase tracking-wide ${scoreBand(s.overall_score).text}`}
              >
                {scoreBand(s.overall_score).label}
              </span>
            </div>
            <ScoreGauge score={s.overall_score} />
            <p className="text-xs leading-relaxed text-muted-foreground">
              Higher means healthier on this model. This is a risk assessment,
              not a return forecast.
            </p>
          </CardContent>
        </Card>
        <div className="space-y-3">
          <RiskDiagnosis
            explain={explain.data}
            loading={explain.isLoading}
            source="score"
          />
          {weakest && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Focus first</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{weakest}</span>{" "}
                is the weakest dimension right now. Open <b>Drivers</b> to see
                why.
                <Link
                  href="/analyze?view=drivers"
                  className="mt-3 flex min-h-11 items-center gap-2 font-medium text-primary hover:underline"
                >
                  Inspect this risk{" "}
                  <WorkspaceIcon name="arrow" className="h-4 w-4" />
                </Link>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
      <DataConfidence confidence={s.data_confidence} />
    </div>
  );
}

// ── Drivers (the full risk report) ───────────────────────────────────

function DriversStage({ onFirstLoad }: { onFirstLoad: () => void }) {
  const report = useRiskReport();
  const { user } = useAuth();
  const { activePortfolioId } = usePortfolioContext();
  const firedRef = useRef(false);
  useRunOncePerUser(
    runKeyForActivePortfolio(user?.id, activePortfolioId),
    () => {
      report.reset();
      report.mutate(undefined, {
        onSuccess: () => {
          if (!firedRef.current) {
            firedRef.current = true;
            onFirstLoad();
          }
        },
      });
    },
  );
  if (report.isPending) return <ResultSkeleton />;
  if (report.isError) return <RiskErrorPanel error={report.error as Error} />;
  if (!report.data) return <ResultSkeleton />;
  return <ReportSections report={report.data} />;
}

// ── Stress Test (what-if + historical + save-as-plan) ────────────────

function StressStage({ onFirstRun }: { onFirstRun: () => void }) {
  const score = useActiveScore();
  const { activePortfolioId } = usePortfolioContext();
  const { user } = useAuth();
  const historical = useHistoricalScenarios();
  const firedRef = useRef(false);
  // The journey milestone represents an EXPLICIT user test. Merely opening
  // this stage auto-loads historical context but must not complete the step.
  const fireOnce = () => {
    if (!firedRef.current) {
      firedRef.current = true;
      onFirstRun();
    }
  };

  useRunOncePerUser(
    runKeyForActivePortfolio(user?.id, activePortfolioId),
    () => {
      historical.reset();
      historical.mutate(undefined);
    },
  );

  const baseline = score.data ?? null;
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">What-if lab</CardTitle>
        </CardHeader>
        <CardContent>
          {/* The Save-as-plan form lives INSIDE WhatIfLab, tied to the live
              sandbox — so a portfolio switch (which resets the sandbox) can
              never persist a prior book's what-if. */}
          <WhatIfLab
            baseline={baseline}
            saveContext={{ portfolioId: activePortfolioId, source: "scenario" }}
            onRunSuccess={fireOnce}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">
            Historical crises — replayed on your book
          </CardTitle>
        </CardHeader>
        <CardContent>
          {historical.isError ? (
            <RiskErrorPanel error={historical.error as Error} />
          ) : (
            <HistoricalScenarios
              data={historical.data}
              loading={historical.isPending}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Action Plan (deterministic levers + saved plans) ─────────────────

function PlanStage() {
  const score = useActiveScore();
  const { activePortfolioId } = usePortfolioContext();
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">What to consider</CardTitle>
        </CardHeader>
        <CardContent>
          <ActionSimulate />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Saved risk plans</CardTitle>
        </CardHeader>
        <CardContent>
          <RiskPlansPanel
            portfolioId={activePortfolioId}
            currentScore={score.data ?? null}
          />
        </CardContent>
      </Card>
    </div>
  );
}

// ── History (trends + what changed) ──────────────────────────────────

function HistoryStage() {
  const score = useActiveScore();
  return (
    <div className="space-y-6">
      <MetricTrend
        metric="overall_score"
        title="Health score over time"
        kind="score"
      />
      <MetricTrend
        metric="annual_volatility"
        title="Volatility over time"
        kind="pct"
      />
      {score.data && <ScoreChangeReport score={score.data} />}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────

export function weakestDimension(
  s: Pick<ScoreResponse, "dimensions">,
): string | null {
  // Read the actual public contract, not the obsolete `dimension_scores` field.
  const dimensions = Object.values(s.dimensions ?? {}).filter((dimension) =>
    Number.isFinite(dimension.score),
  );
  const weakest = dimensions.reduce<(typeof dimensions)[number] | null>(
    (worst, dimension) =>
      !worst || dimension.score < worst.score ? dimension : worst,
    null,
  );
  return weakest?.name ?? null;
}

function NoPortfolio() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">No portfolio yet</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Add your holdings to start analyzing your risk.
        <Link
          href="/portfolios/new"
          className="mt-4 block font-medium text-primary hover:underline"
        >
          Create your first portfolio →
        </Link>
      </CardContent>
    </Card>
  );
}

function WorkspaceSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-10 w-48" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
