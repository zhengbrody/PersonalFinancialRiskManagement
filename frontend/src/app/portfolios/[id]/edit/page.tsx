"use client";

/**
 * Edit an existing portfolio.
 *
 * We don't fetch a per-id GET — the row is already in the
 * /portfolios/me query cache from when the list page loaded. If the
 * user deep-links here without that cache (cold open), we refetch
 * /portfolios/me on mount and pick the matching row.
 */

import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useMyPortfolios,
  useUpdatePortfolio,
  type PortfolioRow,
} from "@/lib/queries";
import {
  PortfolioForm,
  rowsFromHoldings,
  valuesToCreateInput,
} from "@/components/portfolio-form";

export default function EditPortfolioPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const portfolioId = params.id;

  const { user, loading: authLoading, configured } = useAuth();
  const portfoliosQuery = useMyPortfolios();
  const mutation = useUpdatePortfolio(portfolioId);
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  const portfolio: PortfolioRow | undefined = useMemo(
    () => portfoliosQuery.data?.portfolios.find((p) => p.id === portfolioId),
    [portfoliosQuery.data, portfolioId],
  );

  if (!configured || authLoading || !user || portfoliosQuery.isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (!portfolio) {
    return (
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle>Portfolio not found</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          This portfolio is not in your account. It may have been deleted, or
          you may have followed a stale link.
        </CardContent>
      </Card>
    );
  }

  const initial = {
    name: portfolio.name,
    rows: rowsFromHoldings(portfolio.holdings),
    margin_loan: String(portfolio.margin_loan ?? 0),
    contributed_capital: String(portfolio.contributed_capital ?? 0),
    cash_balance: String(portfolio.cash_balance ?? 0),
    is_default: portfolio.is_default,
  };

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          PATCH /api/v1/portfolios/{portfolio.id}
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          Edit portfolio
        </h1>
        <p className="font-mono text-xs text-muted-foreground">
          {portfolio.id}
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>{portfolio.name}</CardTitle>
        </CardHeader>
        <CardContent>
          <PortfolioForm
            initial={initial}
            submitLabel="Save changes"
            busy={mutation.isPending}
            errorMessage={serverError}
            onCancel={() => router.push("/portfolios")}
            onSubmit={async (values) => {
              setServerError(null);
              try {
                await mutation.mutateAsync(valuesToCreateInput(values));
                router.replace("/portfolios");
              } catch (err) {
                setServerError(
                  err instanceof ApiError
                    ? err.message
                    : err instanceof Error
                      ? err.message
                      : "Update failed.",
                );
              }
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}
