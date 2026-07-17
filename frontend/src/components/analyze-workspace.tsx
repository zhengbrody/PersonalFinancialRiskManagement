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
import { Tabs, tabId, tabPanelId } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoreGauge } from "@/components/score-gauge";
import { RiskDiagnosis } from "@/components/risk-diagnosis";
import { DataConfidence } from "@/components/data-confidence";
import { ReportSections, ResultSkeleton, RiskErrorPanel } from "@/components/risk-report";
import { HistoricalScenarios } from "@/components/historical-scenarios";
import { MetricTrend } from "@/components/metric-trend";
import { ScoreChangeReport } from "@/components/score-change-report";
import { ActionSimulate } from "@/components/action-simulate";
import { WhatIfLab } from "@/components/whatif-lab";
import { RiskPlansPanel } from "@/components/risk-plans-panel";
import { track } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { explainInputFromScore } from "@/lib/risk-explain-input";
import { runKeyForActivePortfolio, useRunOncePerUser } from "@/lib/use-run-once-per-user";
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
const isView = (v: string | null): v is View => VIEWS.some((x) => x.value === v);

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
    if (!loading && !user) router.replace("/login");
  }, [user, loading, configured, router]);

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
    <div className="space-y-4">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          Risk workspace
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">
          {current ? current.name : "Analyze"}
        </h1>
      </header>

      <div className="overflow-x-auto">
        <Tabs
          items={VIEWS as unknown as { value: string; label: string }[]}
          value={view}
          onValueChange={setView}
          idBase={TAB_BASE}
        />
      </div>

      {/* Visited stages stay mounted (hidden) so returning is instant + no refetch. */}
      {visited.has("overview") && (
        <StagePanel view="overview" active={view === "overview"}>
          <OverviewStage />
        </StagePanel>
      )}
      {visited.has("drivers") && (
        <StagePanel view="drivers" active={view === "drivers"}>
          <DriversStage
            onFirstLoad={() => {
              recordMilestone.mutate("first_driver_viewed_at");
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

function OverviewStage() {
  const score = useActiveScore();
  const snapshot = useLastSnapshot();
  const explainInput = useMemo(
    () => (score.data ? explainInputFromScore(score.data, snapshot.data) : null),
    [score.data, snapshot.data],
  );
  const explain = useRiskExplain(explainInput);

  if (score.isLoading) return <Skeleton className="h-64 w-full" />;
  if (score.isError) return <RiskErrorPanel error={score.error as Error} />;
  const s = score.data;
  if (!s) return <NoPortfolio />;
  const weakest = weakestDimension(s);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardContent className="flex items-center justify-center py-6">
            <ScoreGauge score={s.overall_score} />
          </CardContent>
        </Card>
        <div className="space-y-3">
          <RiskDiagnosis explain={explain.data} loading={explain.isLoading} source="score" />
          {weakest && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Focus first</CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{weakest}</span> is the weakest
                dimension right now. Open <b>Drivers</b> to see why.
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
  useRunOncePerUser(runKeyForActivePortfolio(user?.id, activePortfolioId), () => {
    report.reset();
    report.mutate(undefined, {
      onSuccess: () => {
        if (!firedRef.current) {
          firedRef.current = true;
          onFirstLoad();
        }
      },
    });
  });
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
  // ONE first-run signal, whichever real stress computation completes first —
  // the auto-run historical replay OR an explicit what-if re-score.
  const fireOnce = () => {
    if (!firedRef.current) {
      firedRef.current = true;
      onFirstRun();
    }
  };

  useRunOncePerUser(runKeyForActivePortfolio(user?.id, activePortfolioId), () => {
    track("stress_test_started", {});
    historical.reset();
    historical.mutate(undefined, {
      onSuccess: () => {
        fireOnce();
        track("stress_test_completed", {});
      },
    });
  });

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
          <CardTitle className="text-base">Historical crises — replayed on your book</CardTitle>
        </CardHeader>
        <CardContent>
          {historical.isError ? (
            <RiskErrorPanel error={historical.error as Error} />
          ) : (
            <HistoricalScenarios data={historical.data} loading={historical.isPending} />
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
          <RiskPlansPanel portfolioId={activePortfolioId} currentScore={score.data ?? null} />
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
      <MetricTrend metric="overall_score" title="Health score over time" kind="score" />
      <MetricTrend metric="annual_volatility" title="Volatility over time" kind="pct" />
      {score.data && <ScoreChangeReport score={score.data} />}
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────

function weakestDimension(s: ScoreResponse): string | null {
  const dims = (s as { dimension_scores?: Record<string, number> }).dimension_scores;
  if (!dims) return null;
  let worst: string | null = null;
  let worstV = Infinity;
  for (const [k, v] of Object.entries(dims)) {
    if (typeof v === "number" && v < worstV) {
      worstV = v;
      worst = k;
    }
  }
  return worst ? worst.replace(/_/g, " ") : null;
}

function NoPortfolio() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">No portfolio yet</CardTitle>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        Add your holdings to start analyzing your risk.
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
