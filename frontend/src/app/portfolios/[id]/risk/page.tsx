"use client";

/**
 * Detailed risk analysis for a SPECIFIC portfolio.
 *
 * The backend's /risk/report_from_active always scores the ACTIVE book. Rather
 * than warn "this isn't the one we'll analyze" (the old behaviour), this page
 * makes [id] the active portfolio first, then runs the report — so what you
 * open is what you analyze, and the switch is reflected everywhere (the global
 * PortfolioContextBar, /score, Copilot…). The report rendering is shared with
 * the global /risk page via <ReportSections/>.
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
import {
  ReportSections,
  ResultSkeleton,
  RiskErrorPanel,
} from "@/components/risk-report";
import { OptionsAnalysis } from "@/components/options-analysis";
import { useAuth } from "@/lib/auth-context";
import { authHref } from "@/lib/auth-redirect";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { runKeyForActivePortfolio, useRunOncePerUser } from "@/lib/use-run-once-per-user";
import {
  activePortfolioOptionContracts,
  useMyPortfolios,
  useRiskReport,
} from "@/lib/queries";

export default function PortfolioRiskPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const portfolioId = params.id;

  const { user, loading: authLoading, configured } = useAuth();
  const portfoliosQuery = useMyPortfolios();
  const reportMutation = useRiskReport();
  const { activePortfolioId, switchPortfolio, switchingId } = usePortfolioContext();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) {
      router.replace(authHref("/login", "/portfolios"));
    }
  }, [user, authLoading, configured, router]);

  const portfolio = useMemo(
    () => portfoliosQuery.data?.portfolios.find((p) => p.id === portfolioId),
    [portfoliosQuery.data, portfolioId],
  );

  // Is THIS the book the backend would analyze? report_from_active always scores
  // the active portfolio, so we only run the report once [id] IS active.
  const isActive = Boolean(portfolio) && portfolio?.id === activePortfolioId;
  const isSwitching = switchingId === portfolioId;

  // Auto-run the report ONLY when this portfolio is the active one — so a
  // freshly-switched book analyzes itself. Keyed on the active id: undefined
  // (skip) while [id] isn't active.
  useRunOncePerUser(
    isActive ? runKeyForActivePortfolio(user?.id, activePortfolioId) : undefined,
    () => {
      reportMutation.reset();
      reportMutation.mutate();
    },
  );

  const optionContracts = useMemo(
    () => activePortfolioOptionContracts(portfoliosQuery.data),
    [portfoliosQuery.data],
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
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Risk report
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">Risk report</h1>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium">{portfolio.name}</span>
          </p>
        </div>
        {isActive ? (
          <Button
            type="button"
            size="lg"
            onClick={() => {
              reportMutation.reset();
              reportMutation.mutate();
            }}
            disabled={reportMutation.isPending}
          >
            {reportMutation.isPending
              ? "Computing…"
              : reportMutation.data
                ? "Re-run"
                : "Run report"}
          </Button>
        ) : (
          <Button
            type="button"
            size="lg"
            onClick={() => void switchPortfolio(portfolioId)}
            disabled={isSwitching}
          >
            {isSwitching ? "Switching…" : `Switch to this portfolio & analyze`}
          </Button>
        )}
      </header>

      {!isActive && (
        <Card className="border-warning/40">
          <CardHeader>
            <CardTitle className="text-base">Analyze this portfolio</CardTitle>
            <CardDescription>
              <span className="font-medium">{portfolio.name}</span> isn’t your active
              portfolio. Switch to it to run the risk report on <strong>this</strong> book —
              it becomes the active portfolio across your dashboard, Copilot and every
              analysis surface.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {isActive && reportMutation.isPending && <ResultSkeleton />}
      {isActive && reportMutation.isError && (
        <RiskErrorPanel error={reportMutation.error as Error} />
      )}
      {isActive && reportMutation.data && !reportMutation.isPending && (
        <>
          <ReportSections report={reportMutation.data} />
          <OptionsAnalysis contracts={optionContracts} />
        </>
      )}
      {isActive &&
        !reportMutation.data &&
        !reportMutation.isPending &&
        !reportMutation.isError && <ResultSkeleton />}
    </div>
  );
}

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
