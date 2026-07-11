"use client";

/**
 * Detailed risk analysis for a specific portfolio.
 *
 * The backend's /risk/report_from_active resolves the user's *active*
 * (default-flagged) portfolio from the JWT; if the user opened this for a
 * non-default portfolio we show a notice. The report rendering itself is
 * shared with the global /risk page via <ReportSections/>.
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

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  const portfolio = useMemo(
    () => portfoliosQuery.data?.portfolios.find((p) => p.id === portfolioId),
    [portfoliosQuery.data, portfolioId],
  );

  // report_from_active scores the user's ACTIVE book: the default-flagged
  // portfolio, or — when none is flagged — the most-recent one (the list is
  // sorted is_default DESC, created_at DESC, so portfolios[0]). Only warn when
  // running the report here would actually score a DIFFERENT portfolio; a user
  // with a single (or most-recent) book gets scored as expected, no scary notice.
  const isActivePortfolio = useMemo(() => {
    const list = portfoliosQuery.data?.portfolios ?? [];
    const activeId = list.find((p) => p.is_default)?.id ?? list[0]?.id;
    return !!portfolio && portfolio.id === activeId;
  }, [portfoliosQuery.data, portfolio]);

  // The report is for the DEFAULT portfolio (report_from_active); feed the
  // options cockpit from the same book so they're consistent.
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
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Risk report
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">Risk report</h1>
          <p className="text-sm text-muted-foreground">
            <span className="font-medium">{portfolio.name}</span>
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

      {!isActivePortfolio && (
        <Card className="border-warning/40">
          <CardHeader>
            <CardTitle className="text-base">Heads up — this isn’t your default portfolio</CardTitle>
            <CardDescription>
              Running a report here scores your <strong>default</strong> portfolio,
              not this one. To analyze this portfolio, set it as default from its
              Edit page.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {reportMutation.isPending && <ResultSkeleton />}
      {reportMutation.isError && (
        <RiskErrorPanel error={reportMutation.error as Error} />
      )}
      {reportMutation.data && !reportMutation.isPending && (
        <>
          <ReportSections report={reportMutation.data} />
          <OptionsAnalysis contracts={optionContracts} />
        </>
      )}
      {!reportMutation.data && !reportMutation.isPending && !reportMutation.isError && (
        <Card>
          <CardHeader>
            <CardTitle>No report yet</CardTitle>
            <CardDescription>
              Click <span className="font-mono">Run report</span> — first run takes
              a few seconds while the cache warms up.
            </CardDescription>
          </CardHeader>
        </Card>
      )}
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
