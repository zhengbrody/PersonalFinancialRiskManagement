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

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
import {
  type PortfolioRow,
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
      router.replace("/login");
    }
  }, [user, authLoading, configured, router]);

  if (!configured) {
    return <ConfigureSupabaseNotice />;
  }

  if (authLoading || !user) {
    return <PageSkeleton />;
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          GET /api/v1/portfolios/me
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">
          Your portfolios
        </h1>
        <p className="text-sm text-muted-foreground">
          Signed in as{" "}
          <span className="font-mono">{user.email ?? user.id}</span>. Rows
          here are filtered by Supabase Row-Level Security.
        </p>
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
            <CardDescription className="font-mono text-xs">
              {portfolio.id}
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
        <div className="grid grid-cols-3 gap-3 pt-2 text-xs">
          <Stat label="Contributed" value={fmtUSD(portfolio.contributed_capital)} />
          <Stat label="Cash" value={fmtUSD(portfolio.cash_balance)} />
          <Stat label="Margin" value={fmtUSD(portfolio.margin_loan)} />
        </div>
        {/* Only the default portfolio is scoreable from the API today —
            the backend resolves the active row from RLS. Non-default
            cards show no button to avoid a wrong-portfolio result. */}
        {portfolio.is_default && tickers.length > 0 && <ScoreSection />}
      </CardContent>
    </Card>
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
      <div className="grid grid-cols-3 gap-2 text-xs">
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
        <ul className="list-disc space-y-0.5 pl-4 text-[11px] text-muted-foreground">
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
      <div className="grid grid-cols-3 gap-2">
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
      "Create or activate a portfolio in the Streamlit app before scoring.";
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
      {isApi && (
        <p className="mt-1 font-mono text-[10px] text-muted-foreground">
          {error.status} · {code}
        </p>
      )}
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
          Create one in the Streamlit app — the new shell pulls from the
          same Supabase backend.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <a href="https://mindmarket.app" target="_blank" rel="noreferrer">
          <Button variant="outline">Open mindmarket.app →</Button>
        </a>
      </CardContent>
    </Card>
  );
}

function ConfigureSupabaseNotice() {
  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Supabase not configured</CardTitle>
        <CardDescription>
          The portfolios page needs an authenticated Supabase session.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>
          Set <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code className="font-mono">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in{" "}
          <code className="font-mono">.env.local</code>, then restart the dev
          server.
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
