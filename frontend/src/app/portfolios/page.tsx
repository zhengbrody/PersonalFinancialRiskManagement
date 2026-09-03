"use client";

/**
 * Protected portfolios list.
 *
 * Three branches:
 *   * `authLoading` — initial Supabase session probe; show skeleton.
 *   * `!user`       — redirect to `/login`.
 *   * `user`        — render the query (loading / error / empty / rows).
 *
 * No middleware-based redirect here yet. Doing it client-side keeps
 * the page renderable without a Supabase round-trip in the edge
 * runtime (which would need server-side env wiring). When we add
 * route-level RSC fetching in Phase 4, the redirect moves up.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { exportPortfolio } from "@/lib/portfolio-export";
import { Button } from "@/components/ui/button";
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
import { authHref } from "@/lib/auth-redirect";
import {
  type PortfolioRow,
  useDeletePortfolio,
  useMyPortfolios,
  useScoreActivePortfolio,
} from "@/lib/queries";
import type { ScoreResponse } from "@/lib/schemas";

export default function PortfoliosPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const portfoliosQuery = useMyPortfolios();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) {
      router.replace(authHref("/login", "/portfolios"));
    }
  }, [user, authLoading, configured, router]);

  // No portfolio yet → go straight to guided creation (skip the empty-list
  // click). EmptyState below is only a brief fallback during the redirect.
  const isEmpty =
    portfoliosQuery.data && portfoliosQuery.data.portfolios.length === 0;
  useEffect(() => {
    if (isEmpty) router.replace("/portfolios/new");
  }, [isEmpty, router]);

  if (!configured) {
    return <PreviewBuildNotice />;
  }

  if (authLoading || !user) {
    return <PageSkeleton />;
  }

  return (
    <div className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Portfolios
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Your portfolios
          </h1>
          <p className="text-sm text-muted-foreground">
            Your data is private to your account.
          </p>
        </div>
        <Link href="/portfolios/new">
          <Button>+ New portfolio</Button>
        </Link>
      </header>

      {portfoliosQuery.isLoading && <ListSkeleton />}

      {portfoliosQuery.isError && (
        <ErrorPanel error={portfoliosQuery.error as Error} />
      )}

      {portfoliosQuery.data && portfoliosQuery.data.portfolios.length === 0 && (
        <EmptyState />
      )}

      {portfoliosQuery.data && portfoliosQuery.data.portfolios.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {portfoliosQuery.data.portfolios.map((p) => (
            <PortfolioCard key={p.id} portfolio={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function PortfolioCard({ portfolio }: { portfolio: PortfolioRow }) {
  const tickers = Object.keys(portfolio.holdings ?? {});
  const tickerPreview =
    tickers.length === 0
      ? "No holdings yet"
      : tickers.slice(0, 6).join(", ") +
        (tickers.length > 6 ? `, +${tickers.length - 6}` : "");

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle>{portfolio.name}</CardTitle>
            <CardDescription className="text-xs">
              {tickers.length === 0
                ? "No holdings yet"
                : `${tickers.length} holding${tickers.length === 1 ? "" : "s"}`}
            </CardDescription>
          </div>
          {portfolio.is_default && (
            <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
              default
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex justify-between">
          <span className="text-muted-foreground">Holdings</span>
          <span className="font-mono">{tickers.length}</span>
        </div>
        <div className="font-mono text-xs text-muted-foreground">
          {tickerPreview}
        </div>
        <div className="grid gap-3 pt-2 text-xs sm:grid-cols-3">
          <Stat label="Contributed" value={fmtUSD(portfolio.contributed_capital)} />
          <Stat label="Settled cash" value={fmtUSD(portfolio.cash_balance)} />
          <Stat label="Margin" value={fmtUSD(portfolio.margin_loan)} />
        </div>
        {/* Only the default portfolio is scored inline; non-default cards
            show no score button to avoid a wrong-portfolio result. */}
        {portfolio.is_default && tickers.length > 0 && <ScoreSection />}
        <CardActions portfolio={portfolio} />
      </CardContent>
    </Card>
  );
}

function CardActions({ portfolio }: { portfolio: PortfolioRow }) {
  const router = useRouter();
  const deletion = useDeletePortfolio();
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="space-y-2 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs">
        <p className="text-destructive">
          Delete <span className="font-mono">{portfolio.name}</span>?
          Holdings will be lost.
        </p>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="destructive"
            onClick={() =>
              deletion.mutate(portfolio.id, {
                onSuccess: () => setConfirming(false),
              })
            }
            disabled={deletion.isPending}
          >
            {deletion.isPending ? "Deleting…" : "Delete forever"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setConfirming(false)}
            disabled={deletion.isPending}
          >
            Cancel
          </Button>
        </div>
        {deletion.isError && (
          <p className="text-destructive">
            {(deletion.error as Error)?.message ?? "Delete failed."}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex gap-2 pt-1">
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => router.push(`/portfolios/${portfolio.id}/risk`)}
      >
        Risk report
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => router.push(`/portfolios/${portfolio.id}/edit`)}
      >
        Edit
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => exportPortfolio(portfolio, "csv")}
        aria-label={`Export ${portfolio.name} as CSV`}
      >
        Export CSV
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => exportPortfolio(portfolio, "json")}
        aria-label={`Export ${portfolio.name} as JSON`}
      >
        Export JSON
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        onClick={() => setConfirming(true)}
        aria-label={`Delete ${portfolio.name}`}
      >
        Delete
      </Button>
    </div>
  );
}

/**
 * Score the active portfolio in-line. Lives inside the default
 * portfolio's card. Idle → Loading → Result | Error.
 */
function ScoreSection() {
  const mutation = useScoreActivePortfolio();

  return (
    <div className="space-y-3 border-t border-border pt-3">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-primary">
            Real-data score
          </p>
          <p className="text-xs text-muted-foreground">
            Uses cached adjusted-close prices via the backend.
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
        >
          {mutation.isPending
            ? "Scoring…"
            : mutation.data
              ? "Re-score"
              : "Score"}
        </Button>
      </div>

      {mutation.isPending && <ScoreLoadingSkeleton />}

      {mutation.isError && (
        <ScoreErrorPanel error={mutation.error as Error} />
      )}

      {mutation.data && !mutation.isPending && (
        <ScoreResult result={mutation.data} />
      )}
    </div>
  );
}

function ScoreResult({ result }: { result: ScoreResponse }) {
  const dims = Object.values(result.dimensions);
  return (
    <div className="space-y-3 rounded-md border border-border bg-muted/30 p-3">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-4xl font-semibold tracking-tight text-primary">
          {result.overall_score}
        </span>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          / 1000 · pref {result.risk_preference}
        </span>
      </div>
      <div className="grid gap-2 text-xs sm:grid-cols-3">
        {dims.map((d) => (
          <div
            key={d.name}
            className="rounded-md border border-border bg-card p-2"
          >
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
              {d.name}
            </div>
            <div className="font-mono text-lg">{Math.round(d.score)}</div>
            <div className="text-[10px] text-muted-foreground">{d.status}</div>
          </div>
        ))}
      </div>
      {result.metrics.data_quality_notes.length > 0 && (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
          {result.metrics.data_quality_notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ScoreLoadingSkeleton() {
  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/30 p-3">
      <Skeleton className="h-10 w-32" />
      <div className="grid gap-2 sm:grid-cols-3">
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
        <Skeleton className="h-14" />
      </div>
    </div>
  );
}

function ScoreErrorPanel({ error }: { error: Error }) {
  const isApi = error instanceof ApiError;
  const code = isApi ? error.code : "unknown";

  // Specific copy for the two structural failures the backend can emit.
  let headline = "Could not score";
  let body = error.message;
  if (code === "no_active_portfolio") {
    headline = "No active portfolio";
    body =
      "Create a portfolio here, or mark one as the default portfolio before scoring.";
  } else if (code === "no_market_data") {
    headline = "Market data unavailable";
    body = "Could not fetch prices for any holding. Try again in a minute.";
  } else if (code === "no_priced_holdings") {
    headline = "Nothing to score";
    body = "Every holding has zero shares or no quote.";
  }

  return (
    <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs">
      <p className="font-medium text-destructive">{headline}</p>
      <p className="mt-1 text-muted-foreground">{body}</p>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

function EmptyState() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>No portfolios yet</CardTitle>
        <CardDescription>
          Add your holdings to get a Health Score and a full risk report —
          calculated from adjusted market prices, private to your account.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Link href="/portfolios/new">
          <Button variant="outline">Create portfolio</Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function PreviewBuildNotice() {
  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Sign-in isn&apos;t available on this build</CardTitle>
        <CardDescription>
          This preview build isn&apos;t configured for accounts yet.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {/* Dev-only: this build lacks the NEXT_PUBLIC_SUPABASE_* env vars.
            Real deployments always set them, so end users never see this. */}
        <p className="text-muted-foreground">
          Accounts aren&apos;t available on this preview build. You can still try
          the public demo below.
        </p>
        <Link href="/score">
          <Button variant="outline">Try the public /score demo</Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function ErrorPanel({ error }: { error: Error }) {
  const isApi = error instanceof ApiError;
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">
          Could not load portfolios
        </CardTitle>
        {isApi && (
          <CardDescription className="font-mono text-xs">
            {error.status} · {error.code}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <p className="text-sm">{error.message}</p>
      </CardContent>
    </Card>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40" />
        <Skeleton className="h-40" />
      </div>
    </div>
  );
}

function ListSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Skeleton className="h-40" />
      <Skeleton className="h-40" />
    </div>
  );
}

function fmtUSD(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
