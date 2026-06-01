"use client";

/**
 * Ticker Research — single-name deep dive (Phase B port of legacy
 * `10_Ticker_Research`).
 *
 * Two-stage, Robinhood-skin / Citadel-bone:
 *   1. Search a ticker → the deterministic DOSSIER paints instantly
 *      (profile, market, fundamentals, valuation, technicals). Free,
 *      no quota.
 *   2. The AI VERDICT (rating + 5 dimension scores + catalysts/risks)
 *      streams in after — quota-gated. A skeleton masks its latency so
 *      the page never feels stuck.
 *
 * Auth gate mirrors /copilot (skeleton while Supabase probes → redirect
 * to /login when signed out).
 */

import { useEffect, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useBillingMe,
  useTickerDossier,
  useTickerVerdict,
  type DeepAnalysis,
  type EquityDossier,
} from "@/lib/queries";

export default function ResearchPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const billing = useBillingMe();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  if (!configured) return <ConfigureNotice />;
  if (authLoading || !user) return <PageSkeleton />;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-tight">Research</h1>
          {billing.data?.plan && (
            <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {billing.data.plan}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Look up any stock. The data lands first; the AI analyst&apos;s
          plain-English verdict — rating, the five things that matter, what
          would change its mind — follows a moment later.
        </p>
      </header>

      <ResearchWorkbench />
    </div>
  );
}

function ResearchWorkbench() {
  const [symbol, setSymbol] = useState("");
  const dossierM = useTickerDossier();
  const verdictM = useTickerVerdict();

  async function run(raw: string) {
    const ticker = raw.trim().toUpperCase();
    if (!ticker || dossierM.isPending) return;
    verdictM.reset();
    try {
      const { dossier } = await dossierM.mutateAsync({ ticker });
      verdictM.mutate({ dossier });
    } catch {
      // dossierM.error renders below.
    }
  }

  const dossier = dossierM.data?.dossier;

  return (
    <div className="space-y-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(symbol);
        }}
        className="flex gap-2"
      >
        <Input
          aria-label="Ticker symbol"
          placeholder="Search a ticker — e.g. AAPL, NVDA, SPY"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          autoCapitalize="characters"
          className="uppercase"
        />
        <Button type="submit" disabled={dossierM.isPending || symbol.trim() === ""}>
          {dossierM.isPending ? "Loading…" : "Research"}
        </Button>
      </form>

      {dossierM.isPending && <DossierSkeleton />}

      {dossierM.error && !dossierM.isPending && (
        <ErrorCard error={dossierM.error} />
      )}

      {dossier && !dossierM.isPending && (
        <>
          <VerdictSection
            pending={verdictM.isPending}
            error={verdictM.error}
            analysis={verdictM.data?.analysis}
            dossier={dossier}
          />
          <DossierDashboard dossier={dossier} />
        </>
      )}

      {!dossier && !dossierM.isPending && !dossierM.error && <EmptyState />}
    </div>
  );
}

// ── verdict (AI) ────────────────────────────────────────────────────

const DIMENSION_ORDER = [
  "quality",
  "fundamentals",
  "growth",
  "technicals",
  "sentiment",
] as const;

function VerdictSection({
  pending,
  error,
  analysis,
  dossier,
}: {
  pending: boolean;
  error: Error | null;
  analysis?: DeepAnalysis;
  dossier: EquityDossier;
}) {
  if (pending) return <VerdictSkeleton />;
  if (error) return <VerdictError error={error} />;
  if (!analysis) return null;

  const { verdict } = analysis;
  const tone = ratingTone(verdict.rating);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-xl">
              {dossier.profile?.name || analysis.ticker}{" "}
              <span className="text-muted-foreground">({analysis.ticker})</span>
            </CardTitle>
            <CardDescription>AI analyst verdict</CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`rounded-md px-3 py-1 text-sm font-semibold ${tone.badge}`}
            >
              {humanizeRating(verdict.rating)}
            </span>
            <span className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
              {verdict.confidence} confidence
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {verdict.thesis_one_liner && (
          <p className="text-base leading-relaxed">{verdict.thesis_one_liner}</p>
        )}
        {verdict.target_weight_pct_band && (
          <p className="text-sm text-muted-foreground">
            Suggested position size:{" "}
            <span className="font-medium text-foreground">
              {verdict.target_weight_pct_band}
            </span>{" "}
            of the portfolio.
          </p>
        )}

        {/* 5 dimension bars */}
        <div className="space-y-3">
          {DIMENSION_ORDER.map((key) => {
            const d = analysis.dimensions[key];
            if (!d) return null;
            return (
              <DimensionBar
                key={key}
                label={key}
                score={d.score_0_100}
                points={d.key_points}
              />
            );
          })}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <BulletCard
            title="Catalysts (next 90 days)"
            items={analysis.catalysts_90d}
            empty="No near-term catalysts flagged."
          />
          <BulletCard
            title="Key risks"
            items={analysis.risks}
            empty="No standout risks flagged."
            tone="danger"
          />
        </div>

        {analysis.would_change_mind.length > 0 && (
          <BulletCard
            title="What would change this view"
            items={analysis.would_change_mind}
          />
        )}

        {analysis.data_gaps.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Data gaps: {analysis.data_gaps.join("; ")}.
          </p>
        )}

        <p className="text-xs text-muted-foreground">
          Educational analysis, not investment advice. Confirm the numbers
          before acting.
        </p>
      </CardContent>
    </Card>
  );
}

function DimensionBar({
  label,
  score,
  points,
}: {
  label: string;
  score: number;
  points: string[];
}) {
  const tone = scoreTone(score);
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{label}</span>
        <span className={tone.text}>{score}/100</span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full ${tone.bar}`}
          style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
        />
      </div>
      {points.length > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">{points[0]}</p>
      )}
    </div>
  );
}

function BulletCard({
  title,
  items,
  empty,
  tone,
}: {
  title: string;
  items: string[];
  empty?: string;
  tone?: "danger";
}) {
  return (
    <div className="rounded-lg border border-border p-3">
      <h3 className="text-sm font-semibold">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-1 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-1 space-y-1 text-sm">
          {items.map((it, i) => (
            <li key={i} className="flex gap-2">
              <span className={tone === "danger" ? "text-red-500" : "text-emerald-500"}>
                •
              </span>
              <span>{it}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── dossier (data) ──────────────────────────────────────────────────

function DossierDashboard({ dossier }: { dossier: EquityDossier }) {
  const m = dossier.market ?? {};
  const f = dossier.fundamentals ?? {};
  const v = dossier.valuation ?? {};
  const t = dossier.technicals ?? {};
  const p = dossier.profile ?? {};

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">The numbers</CardTitle>
        <CardDescription>
          {[p.sector, p.industry].filter(Boolean).join(" · ") || "Company data"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <StatGrid
          title="Market"
          stats={[
            ["Price", money(m.current_price)],
            ["Market cap", money(m.market_cap)],
            ["Beta", num(m.beta)],
            ["Implied vol (30d)", num(m.implied_volatility)],
          ]}
        />
        <StatGrid
          title="Valuation multiples"
          stats={[
            ["P/E (TTM)", num(f.pe_ttm)],
            ["P/S (TTM)", num(f.ps_ttm)],
            ["P/B", num(f.pb)],
            ["EV/EBITDA", num(f.ev_ebitda)],
            ["EPS (TTM)", num(f.eps_ttm)],
            ["Dividend yield", num(f.dividend_yield)],
          ]}
        />
        <StatGrid
          title="Quality & growth"
          stats={[
            ["ROE", num(f.roe)],
            ["ROA", num(f.roa)],
            ["Gross margin", num(f.gross_margin)],
            ["Net margin", num(f.net_margin)],
            ["Revenue growth (YoY)", num(f.revenue_growth_yoy)],
            ["Debt / equity", num(f.debt_to_equity)],
          ]}
        />
        {(v.dcf_intrinsic_value != null || v.dcf_upside_pct != null) && (
          <StatGrid
            title="DCF valuation"
            stats={[
              ["Intrinsic value", money(v.dcf_intrinsic_value)],
              ["Upside", num(v.dcf_upside_pct)],
              ["WACC", num(v.wacc)],
            ]}
          />
        )}
        <StatGrid
          title="Technicals"
          stats={[
            ["RSI (14)", num(t.rsi_14)],
            ["SMA 50", num(t.sma_50)],
            ["SMA 200", num(t.sma_200)],
            ["52w high", money(t.fifty_two_week_high)],
            ["52w low", money(t.fifty_two_week_low)],
            ["Max drawdown (1y)", num(t.max_drawdown_1y)],
          ]}
        />
        {p.description && (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {p.description}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function StatGrid({ title, stats }: { title: string; stats: [string, string][] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-md border border-border px-3 py-2">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-0.5 text-sm font-medium tabular-nums">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── states ──────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <Card>
      <CardContent className="py-10 text-center">
        <p className="text-sm text-muted-foreground">
          Search a ticker above to pull its fundamentals, valuation, and a
          fresh AI analyst verdict.
        </p>
      </CardContent>
    </Card>
  );
}

function DossierSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

function VerdictSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-6 w-48" />
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
        <div className="space-y-2 pt-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
        <p className="pt-1 text-xs text-muted-foreground">
          The AI analyst is reading the dossier…
        </p>
      </CardContent>
    </Card>
  );
}

function VerdictError({ error }: { error: Error }) {
  const code = error instanceof ApiError ? error.code : "unknown";
  if (code === "quota_exceeded") {
    return (
      <Card>
        <CardContent className="space-y-3 py-6">
          <p className="text-sm">
            You&apos;ve used your AI analysis quota this month. The data above
            is still all yours — upgrade for more AI verdicts.
          </p>
          <Link href="/pricing">
            <Button variant="outline" size="sm">
              See plans
            </Button>
          </Link>
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="py-6 text-sm text-muted-foreground">
        The AI verdict hit a snag — the data above is still valid. Try again in
        a moment.
      </CardContent>
    </Card>
  );
}

function ErrorCard({ error }: { error: Error }) {
  const msg =
    error instanceof ApiError && error.code === "unprocessable_entity"
      ? "We couldn't find data for that ticker. Check the symbol and try again."
      : error.message || "Something went wrong. Try again.";
  return (
    <Card>
      <CardContent className="py-6 text-sm text-muted-foreground">{msg}</CardContent>
    </Card>
  );
}

function ConfigureNotice() {
  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Supabase not configured</CardTitle>
        <CardDescription>Research needs an authenticated session.</CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        <Link href="/score">
          <Button variant="outline">Try the public /score demo</Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

// ── format helpers ──────────────────────────────────────────────────

function num(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs !== 0 && abs < 0.01) return v.toFixed(4);
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function ratingTone(rating: string): { badge: string } {
  const r = rating.toUpperCase();
  if (r === "STRONG_BUY" || r === "BUY")
    return { badge: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" };
  if (r === "REDUCE" || r === "AVOID" || r === "SELL")
    return { badge: "bg-red-500/15 text-red-600 dark:text-red-400" };
  return { badge: "bg-amber-500/15 text-amber-600 dark:text-amber-400" };
}

function scoreTone(score: number): { bar: string; text: string } {
  if (score >= 67)
    return { bar: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400" };
  if (score >= 40)
    return { bar: "bg-amber-500", text: "text-amber-600 dark:text-amber-400" };
  return { bar: "bg-red-500", text: "text-red-600 dark:text-red-400" };
}

function humanizeRating(rating: string): string {
  return rating
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
