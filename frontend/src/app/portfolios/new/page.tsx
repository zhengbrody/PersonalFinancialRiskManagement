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
import { track } from "@/lib/analytics";
import { holdingsBand } from "@/lib/analytics-events";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useCreatePortfolio, useMyPortfolios } from "@/lib/queries";
import {
  PortfolioForm,
  valuesToCreateInput,
} from "@/components/portfolio-form";
import { clearAnonHoldings, loadAnonHoldings } from "@/lib/public-risk";

type FormInitial = typeof BLANK;

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
  // Reliable portfolio state (not browser history) decides where Cancel goes:
  // an existing user returns to their list; a zero-portfolio onboarding user
  // has no list to return to (the empty list would just bounce them back here),
  // so they go home — the dashboard's onboarding guide, which never redirects.
  const portfoliosQuery = useMyPortfolios();
  const hasExistingPortfolios =
    (portfoliosQuery.data?.portfolios.length ?? 0) > 0;
  const [serverError, setServerError] = useState<string | null>(null);
  // Handoff from the anonymous risk check: prefill (post-mount, SSR-safe) —
  // nothing is written to the database until the user reviews and saves.
  const [anonPrefill, setAnonPrefill] = useState<FormInitial | null>(null);
  useEffect(() => {
    const anon = loadAnonHoldings();
    if (anon.length > 0) {
      setAnonPrefill({
        ...BLANK,
        rows: anon.map((r) => ({ ticker: r.ticker, shares: r.shares, avg_cost: "" })),
        is_default: true,
      });
    }
  }, []);

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
          Add your holdings
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          New portfolio
        </h1>
        <p className="text-sm text-muted-foreground">
          Add your tickers and shares, or import a broker CSV — you&apos;ll get a
          Health Score the moment you save.
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
          {anonPrefill && (
            <p className="mb-3 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
              Prefilled from your no-signup risk check — review and press Create to
              save it (nothing is stored until you do).
            </p>
          )}
          <PortfolioForm
            key={anonPrefill ? "anon-prefill" : "blank"}
            initial={anonPrefill ?? BLANK}
            emphasizeCsv={!anonPrefill}
            submitLabel="Create portfolio"
            busy={mutation.isPending}
            errorMessage={serverError}
            onCancel={() =>
              router.push(hasExistingPortfolios ? "/portfolios" : "/")
            }
            onSubmit={async (values) => {
              setServerError(null);
              try {
                const created = valuesToCreateInput(values);
                const row = await mutation.mutateAsync(created);
                track("portfolio_created", {
                  // Coarse band, not the exact count (a `holdings` key would be
                  // dropped by the deny-list) — see analytics-funnel.md.
                  holdings_band: holdingsBand(Object.keys(created.holdings).length),
                });
                track("journey_step_completed", { step: "portfolio" }); // stage enum only
                clearAnonHoldings(); // the handoff is complete
                // Navigate from the AUTHORITATIVE create response, never the
                // submitted form. The backend auto-promotes a user's FIRST
                // portfolio to default, so a first/only book (and any book the
                // user explicitly marks default) comes back is_default:true and
                // IS the active book → show its Health Score. An existing user's
                // additional NON-default book must NOT land on /score, which
                // scores their *old* default; send them to the list where the
                // new portfolio is visible. We never flip an existing default.
                if (row.is_default) {
                  router.replace("/score");
                } else {
                  router.replace("/portfolios");
                }
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
