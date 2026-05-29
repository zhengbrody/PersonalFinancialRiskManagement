"use client";

/**
 * Create a new portfolio. Form lives in <PortfolioForm>; this page is
 * just the auth gate + mutation wiring.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useCreatePortfolio } from "@/lib/queries";
import {
  PortfolioForm,
  valuesToCreateInput,
} from "@/components/portfolio-form";

const BLANK = {
  name: "",
  rows: [
    { ticker: "SPY", shares: "", avg_cost: "" },
    { ticker: "BND", shares: "", avg_cost: "" },
  ],
  margin_loan: "0",
  contributed_capital: "0",
  cash_balance: "0",
  is_default: false,
};

export default function NewPortfolioPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const mutation = useCreatePortfolio();
  const [serverError, setServerError] = useState<string | null>(null);

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  if (!configured || authLoading || !user) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-80" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          POST /api/v1/portfolios
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          New portfolio
        </h1>
        <p className="text-sm text-muted-foreground">
          Rows with empty ticker or zero shares are dropped on save.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Holdings</CardTitle>
          <CardDescription>
            You can add or edit holdings any time after creation.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <PortfolioForm
            initial={BLANK}
            submitLabel="Create portfolio"
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
                      : "Create failed.",
                );
              }
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}
