"use client";

/**
 * /risk — the active-portfolio risk report (VaR/CVaR, factor betas, component
 * VaR, stress test, macro betas, liquidity). Backend resolves the user's
 * default-flagged portfolio from the JWT (POST /risk/report_from_active), so
 * this is a global page — no portfolio id needed. Rendering is shared with
 * /portfolios/[id]/risk via <ReportSections/>.
 */

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card,
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
import { useAuth } from "@/lib/auth-context";
import { useRiskReport } from "@/lib/queries";

export default function RiskPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const report = useRiskReport();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  // Auto-run once per signed-in user. Keyed on user.id (not the object, which
  // Supabase recreates on token refresh) so a refresh doesn't recompute.
  const ranFor = useRef<string | null>(null);
  useEffect(() => {
    const uid = user?.id ?? null;
    if (uid && ranFor.current !== uid) {
      ranFor.current = uid;
      report.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  if (!configured || authLoading || !user) return <PageSkeleton />;

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-semibold tracking-tight">Risk report</h1>
          <p className="text-sm text-muted-foreground">
            Full VaR / CVaR, factor exposures, stress test, and liquidity for
            your active portfolio.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => report.mutate()}
          disabled={report.isPending}
        >
          {report.isPending ? "Computing…" : report.data ? "Re-run" : "Run report"}
        </Button>
      </header>

      {report.isPending && <ResultSkeleton />}
      {report.isError && <RiskErrorPanel error={report.error as Error} />}
      {report.data && !report.isPending && <ReportSections report={report.data} />}
      {!report.data && !report.isPending && !report.isError && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Crunching your risk…</CardTitle>
            <CardDescription>
              No active portfolio yet?{" "}
              <Link href="/portfolios/new" className="text-primary hover:underline">
                Create one
              </Link>{" "}
              to see your full risk report.
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
    </div>
  );
}
