"use client";

/**
 * Ticker Research 2.0 — single-name FactPack cockpit.
 *
 * Two-stage — plain-English surface over a rigorous data engine:
 *   1. Search a ticker → the deterministic FACT PACK paints instantly
 *      (header + valuation/quality/growth/analyst cards + peers + news +
 *      pre-written drivers/risk-flags). Authed, no credit.
 *   2. The AI VERDICT (rating + 5 dimension scores + catalysts/risks/what-
 *      would-change-my-mind) is PHRASING over those same numbers — credit-
 *      gated. A 429 keeps the data and swaps in the "see plans" CTA.
 *
 * The LLM never invents a number: every figure on the page comes from the
 * FactPack; the verdict only re-phrases them.
 *
 * Auth gate mirrors /copilot (skeleton while Supabase probes → redirect to
 * /login when signed out).
 */

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { DataConfidence } from "@/components/data-confidence";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { DataTable, type Column } from "@/components/ui/data-table";
import { CreditsBadge } from "@/components/credits-badge";
import { TickerNews } from "@/components/ticker-news";
import { ResearchCoverageCard } from "@/components/research-coverage";
import { LearnHint } from "@/components/learn-hint";
import { ReportExportButton } from "@/components/report-export-button";
import { ResearchTestDrawer } from "@/components/research-test-drawer";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { ResearchFinancials } from "@/components/research-financials";
import { ResearchCharts } from "@/components/research-charts";
import { ValuationDcf } from "@/components/valuation-dcf";
import { PeersComparison } from "@/components/peers-comparison";
import { EarningsComparison } from "@/components/earnings-comparison";
import { ResearchThesis } from "@/components/research-thesis";
import { AnalystReportView } from "@/components/analyst-report";
import { ApiError } from "@/lib/api";
import { BETA_LIMIT_MESSAGE, isBillingEnabled } from "@/lib/billing-flag";
import { useAuth } from "@/lib/auth-context";
import { authHref } from "@/lib/auth-redirect";
import { useSessionState } from "@/lib/use-session-state";
import { track } from "@/lib/analytics";
import {
  useBillingMe,
  useResearchBundle,
  useResearchCoverage,
  useResearchVerdict,
  type FactPack,
  type ResearchVerdict,
  type ResearchBundle,
} from "@/lib/queries";

export default function ResearchPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const billing = useBillingMe();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) {
      router.replace(authHref("/login", "/research"));
    }
  }, [user, authLoading, configured, router]);

  if (!configured) return <ConfigureNotice />;
  if (authLoading || !user) return <PageSkeleton />;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-tight">Research</h1>
          {isBillingEnabled() && billing.data?.plan && (
            <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {billing.data.plan}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Look up any stock. The fact pack lands first — valuation, quality,
          growth, the Street&apos;s view, peers and news, each tagged with its
          source. The AI analyst&apos;s plain-English verdict follows a moment
          later, phrasing those numbers, never inventing them.
        </p>
      </header>

      {/* useSearchParams (inside the workbench) requires a Suspense boundary
          when the route is statically prerendered — same pattern as /copilot. */}
      <Suspense fallback={<PageSkeleton />}>
        <ResearchWorkbench />
      </Suspense>
    </div>
  );
}

function ResearchWorkbench() {
  // The search box stays plain useState (no need to persist every keystroke);
  // only the ACTIVE ticker is persisted to sessionStorage, so switching
  // screens/tabs and coming back restores the loaded cockpit (the bundle reloads
  // from the React Query cache instantly) instead of an empty search box.
  const [symbol, setSymbol] = useState("");
  const [activeTicker, setActiveTicker] = useSessionState<string | null>(
    "mm:research:ticker",
    null,
  );
  const bundle = useResearchBundle(activeTicker);
  const verdictM = useResearchVerdict();

  const b = bundle.data?.bundle;
  const fp = b?.fact_pack ?? undefined;

  // Auto-fire the AI verdict once per ticker, as soon as the bundle's FactPack
  // lands — the prominent AI summary fills in a moment after the data.
  const firedFor = useRef<string | null>(null);
  const { mutate: fireVerdict } = verdictM;
  useEffect(() => {
    if (fp && firedFor.current !== fp.ticker) {
      firedFor.current = fp.ticker;
      fireVerdict({ fact_pack: fp });
    }
  }, [fp, fireVerdict]);

  function run(raw: string) {
    const ticker = raw.trim().toUpperCase();
    if (!ticker) return;
    verdictM.reset();
    firedFor.current = null;
    // Privacy: never send the ticker itself to analytics — searching a symbol
    // can reveal what the user holds.
    track("research_started");
    setActiveTicker(ticker);
  }

  // Honor a `?ticker=` deep-link (e.g. the Copilot "Research NVDA" action) —
  // REACTIVELY: a query change on the already-mounted page (Copilot navigating
  // to a second ticker, browser back/forward between two deep-links) must
  // update the loaded ticker too, not just the first mount. Guards:
  //   * seededParam dedupes per URL VALUE — the same param never re-fires;
  //   * norm === activeTicker skips run() — no duplicate bundle fetch and,
  //     critically, no duplicate credit-gated verdict fire;
  //   * an empty/absent param never clears the persisted ticker;
  //   * input is normalized (trim/uppercase) and length-bounded to match the
  //     backend's Path(max_length=20) — anything else flows through the same
  //     run() path and surfaces the normal "couldn't find data" state.
  const searchParams = useSearchParams();
  const seededParam = useRef<string | null>(null);
  useEffect(() => {
    const raw = searchParams.get("ticker");
    const norm = (raw ?? "").trim().toUpperCase();
    if (!norm || norm.length > 20) return;
    if (seededParam.current === norm) return; // this URL value was already honored
    seededParam.current = norm;
    if (norm === activeTicker) return; // already loaded — don't refire the verdict
    run(norm);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, activeTicker]);

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
        <Button type="submit" disabled={bundle.isFetching || symbol.trim() === ""}>
          {bundle.isFetching ? "Loading…" : "Research"}
        </Button>
      </form>
      <CreditsBadge />

      {bundle.isLoading && <FactPackSkeleton />}
      {bundle.isError && !bundle.isLoading && <ErrorCard error={bundle.error} />}

      {b && fp && <ResearchReport b={b} fp={fp} verdictM={verdictM} />}
      {b && !fp && (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            We couldn&apos;t find data for that ticker. Check the symbol and try again.
          </CardContent>
        </Card>
      )}

      {!activeTicker && <EmptyState />}
    </div>
  );
}

/**
 * The consolidated single-page report. One bundle fetch feeds every section —
 * the pure FactPack cards, the trust strip, the AI summary (auto-fired verdict),
 * the deterministic investment debate, the charts, and the reused financials /
 * DCF / peers / earnings / news components (passed their bundle slice so they
 * don't re-fetch). No tabs; nothing here fans out to the providers a second time.
 */
function ResearchReport({
  b,
  fp,
  verdictM,
}: {
  b: ResearchBundle;
  fp: FactPack;
  verdictM: ReturnType<typeof useResearchVerdict>;
}) {
  const { hasPortfolios } = usePortfolioContext();
  const [testOpen, setTestOpen] = useState(false);
  return (
    <div className="space-y-6">
      <FactPackHeader fp={fp} />
      <ResearchTrustSummary ticker={fp.ticker} />
      <div className="flex flex-wrap items-center justify-end gap-2">
        {hasPortfolios && (
          <Button
            type="button"
            size="sm"
            onClick={() => {
              setTestOpen(true);
              track("research_test_started", {}); // value-free
            }}
          >
            Test {fp.ticker} in my portfolio
          </Button>
        )}
        <ReportExportButton
          kind="ticker"
          payload={{ fact_pack: fp, verdict: verdictM.data?.verdict ?? null }}
          label="Export research report"
        />
      </div>
      <ResearchTestDrawer ticker={fp.ticker} open={testOpen} onClose={() => setTestOpen(false)} />


      {/* AI summary (loads a beat after the data) + the deterministic debate */}
      <VerdictSection
        pending={verdictM.isPending}
        error={verdictM.error}
        verdict={verdictM.data?.verdict}
      />
      {verdictM.data?.verdict && <VerdictCasework verdict={verdictM.data.verdict} />}
      <ResearchThesis ticker={fp.ticker} initial={b.thesis ?? undefined} />

      {/* Charts: the trend chart is unique here; the earnings timeline, peer
          scatter and DCF scenarios render inside their reused sections below. */}
      <ResearchCharts financials={b.financials ?? undefined} />

      <SignalsCard fp={fp} />

      {/* Valuation */}
      <ValuationCard fp={fp} />
      <ValuationDcf ticker={fp.ticker} data={b.dcf ?? undefined} />

      {/* Quality + growth */}
      <div className="grid gap-4 lg:grid-cols-2">
        <QualityCard fp={fp} />
        <GrowthCard fp={fp} />
      </div>

      {/* Financials */}
      <ResearchFinancials ticker={fp.ticker} data={b.financials ?? undefined} />

      {/* Peers */}
      {fp.peers.length > 0 && <PeersCard fp={fp} />}
      <PeersComparison ticker={fp.ticker} data={b.peers ?? undefined} />

      {/* Earnings */}
      <EarningsComparison ticker={fp.ticker} data={b.earnings ?? undefined} />

      {/* Analyst + technicals + ownership */}
      <AnalystCard fp={fp} />
      <div className="grid gap-4 lg:grid-cols-2">
        <MomentumCard fp={fp} />
        <OwnershipInsiderCard fp={fp} />
      </div>

      {/* News + provenance */}
      <TickerNews ticker={fp.ticker} data={b.news ?? undefined} />
      <ResearchCoverageCard ticker={fp.ticker} />
      <SourcesCard fp={fp} />

      {/* Full HTML report (on demand) + Copilot handoff */}
      <AnalystReportView ticker={fp.ticker} />
      <CopilotHandoff fp={fp} />
    </div>
  );
}

/**
 * The ONE research-level trust summary — the unified <DataConfidence> block fed
 * by the coverage endpoint (confidence label + coverage + freshness + fallback
 * + cross-source agreement + critical-missing + conviction cap). Replaces the
 * old hand-rolled TrustStrip AND the header DataQualityBadge, which repeated
 * the same information in two more vocabularies. Uses the SAME query the
 * coverage matrix uses (React Query dedupes it — one request per ticker).
 */
function ResearchTrustSummary({ ticker }: { ticker: string }) {
  const coverage = useResearchCoverage(ticker);
  if (coverage.isLoading) {
    return <Skeleton className="h-16 w-full" data-testid="trust-summary-skeleton" />;
  }
  const dc = coverage.data?.data_confidence;
  if (!dc) return null; // the per-figure SourcesCard still discloses provenance
  return <DataConfidence confidence={dc} title="Data confidence" />;
}

/** Per-field provenance table — every FactPack figure with its source + coverage. */
function SourcesCard({ fp }: { fp: FactPack }) {
  const sources = fp.data_quality?.sources ?? [];
  const warnings = fp.data_quality?.warnings ?? [];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Data sources & provenance</CardTitle>
        <CardDescription>
          Every figure above carries its source. {fp.as_of ? `As of ${formatAsOf(fp.as_of)}.` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {warnings.length > 0 && (
          <ul className="space-y-1 text-xs">
            {warnings.map((w, i) => (
              <li key={i} className="text-amber-600 dark:text-amber-400">
                {humanizeWarning(w)}
              </li>
            ))}
          </ul>
        )}
        {sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">No per-field source detail available.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th className="py-1 font-medium">Field</th>
                <th className="py-1 font-medium">Source</th>
                <th className="py-1 text-right font-medium">Coverage</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.field} className="border-t border-border/40">
                  <td className="py-1.5 text-muted-foreground">{s.field}</td>
                  <td className="py-1.5">
                    <SourceBadge source={s.source} />
                  </td>
                  <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                    {s.coverage != null ? `${Math.round(s.coverage * 100)}%` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-xs text-muted-foreground">
          Sources: Massive · FMP · Yahoo Finance (free fallback) · SEC. Missing or
          stale fields are flagged, never faked.
        </p>
      </CardContent>
    </Card>
  );
}

/**
 * Cross-feature handoff: take the ticker into the Copilot with a pre-filled,
 * risk-first question. Deep-links to /copilot?q=… (the box is prefilled, not
 * auto-run, so no credit is spent by navigating). Pure frontend.
 */
function CopilotHandoff({ fp }: { fp: FactPack }) {
  const t = fp.ticker;
  const prompts = [
    `What are the key risks of holding ${t}?`,
    `How would ${t} affect my portfolio's risk?`,
    `Compare ${t} to its peers`,
  ];
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Dig deeper with Copilot</CardTitle>
        <CardDescription>
          Take {t} into your Copilot for a portfolio-aware, source-grounded
          answer. <LearnHint topic="stock-research" label="How to research a stock" />
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {prompts.map((q) => (
          <Link
            key={q}
            href={`/copilot?q=${encodeURIComponent(q)}`}
            onClick={() => track("copilot_handoff_clicked", { source: "research" })}
            className="rounded-full border border-border bg-muted px-3 py-1.5 text-xs text-muted-foreground transition hover:bg-accent hover:text-accent-foreground"
          >
            {q}
          </Link>
        ))}
      </CardContent>
    </Card>
  );
}

// ── source-quality helpers ──────────────────────────────────────────

/** Find the data-quality source row matching any of the given field names. */
function sourceFor(fp: FactPack, ...fields: string[]): string | null {
  const rows = fp.data_quality?.sources ?? [];
  for (const f of fields) {
    const row = rows.find((s) => s.field === f);
    if (row) return row.source;
  }
  return null;
}

function SourceBadge({ source }: { source: string | null }) {
  if (!source || source === "unavailable") return null;
  const label =
    source === "fmp"
      ? "FMP"
      : source === "yfinance"
        ? "Yahoo (free)"
        : source === "derived"
          ? "derived"
          : source;
  const tone =
    source === "fmp"
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-muted-foreground";
  return (
    <span
      className={`rounded border border-border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${tone}`}
      title={`Source: ${label}`}
    >
      {label}
    </span>
  );
}

// ── header (identity + freshness + data quality) ────────────────────

function FactPackHeader({ fp }: { fp: FactPack }) {
  const sectorLine = [fp.sector, fp.industry].filter(Boolean).join(" · ");
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-2xl">
              {fp.name || fp.ticker}{" "}
              <span className="text-muted-foreground">({fp.ticker})</span>
            </CardTitle>
            {sectorLine && <CardDescription>{sectorLine}</CardDescription>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {fp.as_of && (
              <span
                className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                title={`Data as of ${formatAsOf(fp.as_of)}`}
              >
                as of {formatAsOf(fp.as_of)}
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Price" value={money(fp.price)} />
          <Stat label="Market cap" value={money(fp.market_cap)} />
          <Stat label="Beta" value={num(fp.beta)} />
        </div>
      </CardContent>
    </Card>
  );
}

// ── verdict (AI) ────────────────────────────────────────────────────

function VerdictSection({
  pending,
  error,
  verdict,
}: {
  pending: boolean;
  error: Error | null;
  verdict?: ResearchVerdict;
}) {
  if (pending) return <VerdictSkeleton />;
  if (error) return <VerdictError error={error} />;
  if (!verdict) return null;

  const tone = ratingTone(verdict.rating);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-xl">AI analyst verdict</CardTitle>
            <CardDescription>
              {verdict.data_only
                ? "Data-driven (no AI key) — the deterministic floor"
                : "Plain-English read of the numbers above"}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded-md px-3 py-1 text-sm font-semibold ${tone.badge}`}>
              {verdict.rating}
            </span>
            <span className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
              {verdict.conviction} conviction
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {verdict.summary && (
          <p className="text-base leading-relaxed">{verdict.summary}</p>
        )}

        {/* Verdict-scoped confidence (the AI verdict's directional gate) —
            titled differently from the page-level ResearchTrustSummary so the
            two blocks are distinguishable to screen readers and users. */}
        <DataConfidence confidence={verdict.data_confidence} title="Verdict confidence" />

        {verdict.dimensions.length > 0 && (
          <div className="space-y-3">
            {verdict.dimensions.map((d) => (
              <DimensionBar
                key={d.name}
                label={d.name}
                score={d.score}
                note={d.note ?? undefined}
              />
            ))}
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          Educational analysis, not investment advice. Confirm the numbers
          before acting. The bull/bear case is in the Risks tab below.
        </p>
      </CardContent>
    </Card>
  );
}

/** Catalysts / key risks / what-would-change — the verdict's casework, shown in
 * the Risks tab (the headline rating + dimensions stay above the tabs). */
function VerdictCasework({ verdict }: { verdict: ResearchVerdict }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <BulletCard title="Catalysts" items={verdict.catalysts} empty="No near-term catalysts flagged." />
        <BulletCard
          title="Key risks"
          items={verdict.risks}
          empty="No standout risks flagged."
          tone="danger"
        />
      </div>
      {verdict.what_would_change_my_mind.length > 0 && (
        <BulletCard title="What would change my mind" items={verdict.what_would_change_my_mind} />
      )}
    </div>
  );
}

function DimensionBar({
  label,
  score,
  note,
}: {
  label: string;
  score: number;
  note?: string;
}) {
  const tone = scoreTone(score);
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium capitalize">{label}</span>
        <span className={tone.text}>{Math.round(score)}/100</span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full ${tone.bar}`}
          style={{ width: `${Math.max(0, Math.min(100, score))}%` }}
        />
      </div>
      {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
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

// ── valuation / quality / growth / analyst cards ────────────────────

function MomentumCard({ fp }: { fp: FactPack }) {
  const m = fp.momentum;
  if (!m) return null;
  const has =
    m.rsi_14 != null ||
    m.sma_50 != null ||
    m.fifty_two_week_high != null ||
    m.price_vs_sma200_pct != null;
  if (!has) return null;

  return (
    <SectionCard
      title="Price momentum"
      source={sourceFor(fp, "momentum")}
      headerExtra={<TrendBadge trend={m.trend ?? null} />}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="RSI (14)" value={num(m.rsi_14)} />
        <Stat label="vs 50-day" value={signedPct(m.price_vs_sma50_pct)} />
        <Stat label="vs 200-day" value={signedPct(m.price_vs_sma200_pct)} />
        <Stat label="From 52w high" value={signedPct(m.pct_from_52w_high)} />
        <Stat label="Off 52w low" value={signedPct(m.pct_off_52w_low)} />
        <Stat label="50-day avg" value={money(m.sma_50)} />
        <Stat label="200-day avg" value={money(m.sma_200)} />
        <Stat label="52w range" value={range52w(m.fifty_two_week_low, m.fifty_two_week_high)} />
        <Stat label="Realized vol 20d" value={pct(m.realized_vol_20d)} />
        <Stat label="Realized vol 60d" value={pct(m.realized_vol_60d)} />
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        Where price sits versus its own history + how much it has been moving
        (annualized realized volatility) — descriptive, not a buy/sell signal.
      </p>
    </SectionCard>
  );
}

function TrendBadge({ trend }: { trend: string | null }) {
  if (!trend) return null;
  const tone =
    trend === "uptrend"
      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
      : trend === "downtrend"
        ? "bg-red-500/15 text-red-600 dark:text-red-400"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={`rounded-md px-2.5 py-1 text-xs font-semibold capitalize ${tone}`}
      title="Price relative to its 50- and 200-day moving averages"
    >
      {trend}
    </span>
  );
}

function OwnershipInsiderCard({ fp }: { fp: FactPack }) {
  const own = fp.ownership;
  const ins = fp.insider;
  const hasOwn = own?.institutional_pct != null;
  const hasIns = ins != null && ((ins.buys_90d ?? 0) > 0 || (ins.sells_90d ?? 0) > 0);
  if (!hasOwn && !hasIns) return null;

  return (
    <SectionCard
      title="Ownership & insiders"
      source={sourceFor(fp, "ownership", "insider")}
      headerExtra={ins?.signal ? <InsiderSignalBadge signal={ins.signal} /> : null}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Institutional held" value={pct(own?.institutional_pct)} />
        <Stat label="Insider buys (90d)" value={hasIns ? String(ins!.buys_90d ?? 0) : "—"} />
        <Stat label="Insider sells (90d)" value={hasIns ? String(ins!.sells_90d ?? 0) : "—"} />
        <Stat label="Net shares (90d)" value={num(ins?.net_shares_90d)} />
      </div>
    </SectionCard>
  );
}

function InsiderSignalBadge({ signal }: { signal: string }) {
  const tone =
    signal === "net buying"
      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
      : signal === "net selling"
        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
        : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-md px-2.5 py-1 text-xs font-semibold capitalize ${tone}`}>
      {signal}
    </span>
  );
}

function signedPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function range52w(lo: number | null | undefined, hi: number | null | undefined): string {
  if (lo == null && hi == null) return "—";
  return `${money(lo)} – ${money(hi)}`;
}

function ValuationCard({ fp }: { fp: FactPack }) {
  const v = fp.valuation;
  return (
    <SectionCard
      title="Valuation"
      source={sourceFor(fp, "pe", "valuation", "forward_pe")}
      headerExtra={<ValuationBand band={v.band ?? null} median={v.peer_median_pe} />}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="P/E" value={num(v.pe)} />
        <Stat label="Forward P/E" value={num(v.forward_pe)} />
        <Stat label="P/S" value={num(v.ps)} />
        <Stat label="P/B" value={num(v.pb)} />
        <Stat label="EV/EBITDA" value={num(v.ev_ebitda)} />
        <Stat label="FCF yield" value={pct(v.fcf_yield)} />
        <Stat label="Dividend yield" value={pct(v.dividend_yield)} />
        <Stat label="Peer median P/E" value={num(v.peer_median_pe)} />
      </div>
    </SectionCard>
  );
}

function ValuationBand({
  band,
  median,
}: {
  band: string | null;
  median: number | null | undefined;
}) {
  if (!band) return null;
  const tone =
    band === "cheap"
      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
      : band === "rich"
        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
        : "bg-muted text-muted-foreground";
  return (
    <span
      className={`rounded-md px-2.5 py-1 text-xs font-semibold capitalize ${tone}`}
      title={median != null ? `vs peer median P/E ${num(median)}` : undefined}
    >
      {band}
    </span>
  );
}

function QualityCard({ fp }: { fp: FactPack }) {
  const q = fp.quality;
  return (
    <SectionCard
      title="Quality"
      source={sourceFor(fp, "quality", "net_margin", "roe")}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Gross margin" value={pct(q.gross_margin)} />
        <Stat label="Operating margin" value={pct(q.operating_margin)} />
        <Stat label="Net margin" value={pct(q.net_margin)} />
        <Stat label="ROE" value={pct(q.roe)} />
        <Stat label="ROA" value={pct(q.roa)} />
        <Stat label="ROIC" value={pct(q.roic)} />
        <Stat label="Current ratio" value={num(q.current_ratio)} />
        <Stat label="Debt / equity (×)" value={num(q.debt_to_equity)} />
        <Stat label="Interest coverage" value={num(q.interest_coverage)} />
      </div>
    </SectionCard>
  );
}

function GrowthCard({ fp }: { fp: FactPack }) {
  const g = fp.growth;
  return (
    <SectionCard
      title="Growth"
      source={sourceFor(fp, "growth", "revenue_cagr", "revenue_growth_yoy")}
      headerExtra={
        g.periods != null ? (
          <span className="text-xs text-muted-foreground">
            over {g.periods} periods
          </span>
        ) : null
      }
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Revenue CAGR" value={pct(g.revenue_cagr)} />
        <Stat label="EPS CAGR" value={pct(g.eps_cagr)} />
        <Stat label="FCF CAGR" value={pct(g.fcf_cagr)} />
        <Stat label="Revenue (YoY)" value={pct(g.revenue_growth_yoy)} />
        <Stat label="Earnings (YoY)" value={pct(g.earnings_growth_yoy)} />
      </div>
    </SectionCard>
  );
}

function AnalystCard({ fp }: { fp: FactPack }) {
  const a = fp.analyst;
  const hasTargets =
    a.target_low != null || a.target_consensus != null || a.target_high != null;
  if (!a.rating && !hasTargets && a.num_analysts == null) return null;

  return (
    <SectionCard
      title="Analyst consensus"
      source={sourceFor(fp, "analyst", "rating", "target_consensus")}
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          {a.rating && (
            <span className={`rounded-md px-3 py-1 font-semibold ${ratingTone(a.rating).badge}`}>
              {humanizeRating(a.rating)}
            </span>
          )}
          {a.num_analysts != null && (
            <span className="text-muted-foreground">
              {num(a.num_analysts)} analysts
            </span>
          )}
          {a.implied_upside_pct != null && (
            <span className="text-muted-foreground">
              Avg target implies{" "}
              <span
                className={
                  a.implied_upside_pct >= 0
                    ? "font-medium text-emerald-600 dark:text-emerald-400"
                    : "font-medium text-red-600 dark:text-red-400"
                }
              >
                {a.implied_upside_pct >= 0 ? "+" : ""}
                {(a.implied_upside_pct * 100).toFixed(1)}%
              </span>
            </span>
          )}
        </div>
        {hasTargets && (
          <PriceTargetBar
            low={a.target_low}
            mean={a.target_consensus}
            high={a.target_high}
            current={fp.price}
          />
        )}
      </div>
    </SectionCard>
  );
}

function PriceTargetBar({
  low,
  mean,
  high,
  current,
}: {
  low: number | null | undefined;
  mean: number | null | undefined;
  high: number | null | undefined;
  current: number | null | undefined;
}) {
  if (low == null || high == null || high <= low) {
    return (
      <div className="flex gap-5 text-sm">
        {low != null && (
          <span className="text-muted-foreground">
            Low <span className="font-medium text-foreground">{money(low)}</span>
          </span>
        )}
        {mean != null && (
          <span className="text-muted-foreground">
            Avg <span className="font-medium text-foreground">{money(mean)}</span>
          </span>
        )}
        {high != null && (
          <span className="text-muted-foreground">
            High <span className="font-medium text-foreground">{money(high)}</span>
          </span>
        )}
      </div>
    );
  }
  const span = high - low;
  const posPct = (val: number) =>
    Math.max(0, Math.min(100, ((val - low) / span) * 100));
  return (
    <div>
      <div className="relative h-2 w-full rounded-full bg-gradient-to-r from-red-500/30 via-amber-500/30 to-emerald-500/40">
        {current != null && (
          <div
            className="absolute top-1/2 h-4 w-0.5 -translate-y-1/2 bg-foreground"
            style={{ left: `${posPct(current)}%` }}
            title={`Current ${money(current)}`}
          />
        )}
      </div>
      <div className="mt-2 flex justify-between text-xs">
        <span className="text-muted-foreground">
          Low <span className="font-medium text-foreground">{money(low)}</span>
        </span>
        {mean != null && (
          <span className="text-muted-foreground">
            Avg <span className="font-medium text-foreground">{money(mean)}</span>
          </span>
        )}
        <span className="text-muted-foreground">
          High <span className="font-medium text-foreground">{money(high)}</span>
        </span>
      </div>
    </div>
  );
}

// ── drivers + risk flags ────────────────────────────────────────────

function SignalsCard({ fp }: { fp: FactPack }) {
  if (fp.drivers.length === 0 && fp.risk_flags.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">What stands out</CardTitle>
        <CardDescription>
          Plain-language reads straight from the numbers.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-border p-3">
          <h3 className="text-sm font-semibold">Drivers</h3>
          {fp.drivers.length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">None flagged.</p>
          ) : (
            <ul className="mt-1 space-y-1 text-sm">
              {fp.drivers.map((d, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-emerald-500">✓</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="rounded-lg border border-border p-3">
          <h3 className="text-sm font-semibold">Risk flags</h3>
          {fp.risk_flags.length === 0 ? (
            <p className="mt-1 text-sm text-muted-foreground">None flagged.</p>
          ) : (
            <ul className="mt-1 space-y-1 text-sm">
              {fp.risk_flags.map((r, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-amber-500">⚠</span>
                  <span>{r}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── peer comparison ─────────────────────────────────────────────────

type PeerRow = FactPack["peers"][number] & { isSubject: boolean };

function PeersCard({ fp }: { fp: FactPack }) {
  const subject: PeerRow = {
    ticker: fp.ticker,
    name: fp.name,
    market_cap: fp.market_cap,
    pe: fp.valuation.pe,
    ps: fp.valuation.ps,
    net_margin: fp.quality.net_margin,
    roe: fp.quality.roe,
    isSubject: true,
  };
  const peers: PeerRow[] = fp.peers
    .filter((p) => p.ticker.toUpperCase() !== fp.ticker.toUpperCase())
    .map((p) => ({ ...p, isSubject: false }));
  const rows = [subject, ...peers];

  const columns: Column<PeerRow>[] = [
    {
      key: "ticker",
      header: "Ticker",
      align: "left",
      render: (r) => (
        <span className={r.isSubject ? "font-semibold text-primary" : ""}>
          {r.ticker}
        </span>
      ),
      sortValue: (r) => r.ticker,
    },
    {
      key: "name",
      header: "Name",
      align: "left",
      render: (r) => <span className="font-sans">{r.name || "—"}</span>,
      sortValue: (r) => r.name ?? "",
    },
    {
      key: "market_cap",
      header: "Market cap",
      align: "right",
      render: (r) => money(r.market_cap),
      sortValue: (r) => r.market_cap ?? -Infinity,
    },
    {
      key: "pe",
      header: "P/E",
      align: "right",
      render: (r) => num(r.pe),
      sortValue: (r) => r.pe ?? -Infinity,
    },
    {
      key: "ps",
      header: "P/S",
      align: "right",
      render: (r) => num(r.ps),
      sortValue: (r) => r.ps ?? -Infinity,
    },
    {
      key: "net_margin",
      header: "Net margin",
      align: "right",
      render: (r) => pct(r.net_margin),
      sortValue: (r) => r.net_margin ?? -Infinity,
    },
    {
      key: "roe",
      header: "ROE",
      align: "right",
      render: (r) => pct(r.roe),
      sortValue: (r) => r.roe ?? -Infinity,
    },
  ];

  return (
    <SectionCard title="Peer comparison" source={sourceFor(fp, "peers")}>
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(r) => r.ticker}
        initialSort={{ key: "market_cap", dir: "desc" }}
        topN={12}
        minWidth={560}
      />
    </SectionCard>
  );
}

// ── shared building blocks ──────────────────────────────────────────

function SectionCard({
  title,
  source,
  headerExtra,
  children,
}: {
  title: string;
  source?: string | null;
  headerExtra?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          <div className="flex items-center gap-2">
            {headerExtra}
            <SourceBadge source={source ?? null} />
          </div>
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-medium tabular-nums">{value}</div>
    </div>
  );
}

// ── states ──────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <Card>
      <CardContent className="py-10 text-center">
        <p className="text-sm text-muted-foreground">
          Search a ticker above to pull its fact pack — valuation, quality,
          growth, the Street&apos;s view, peers and news — plus a fresh AI
          analyst verdict.
        </p>
      </CardContent>
    </Card>
  );
}

function FactPackSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-32 w-full" />
      <Skeleton className="h-48 w-full" />
      <Skeleton className="h-48 w-full" />
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
          The AI analyst is reading the fact pack…
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
          {isBillingEnabled() ? (
            <>
              <p className="text-sm">
                You&apos;ve used your AI analysis quota this month. The fact pack
                below is still all yours — upgrade for more AI verdicts.
              </p>
              <Link href="/pricing">
                <Button variant="outline" size="sm">
                  See plans
                </Button>
              </Link>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">
              {BETA_LIMIT_MESSAGE} The fact pack below is still all yours.
            </p>
          )}
        </CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardContent className="py-6 text-sm text-muted-foreground">
        The AI verdict hit a snag — the fact pack below is still valid. Try
        again in a moment.
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
        <CardTitle>Sign in to research a stock</CardTitle>
        <CardDescription>Sign in to save research to your account.</CardDescription>
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

function pct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

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

function formatAsOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function humanizeWarning(w: string): string {
  if (w === "fmp_key_missing")
    return "Provider fields unavailable — built from public fallback sources.";
  return w.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function ratingTone(rating: string): { badge: string } {
  const r = rating.toUpperCase().replace(/\s+/g, "_");
  // Verdict vocabulary (non-transactional data screen: Strong … Very Weak);
  // the BUY/SELL keys remain only for the third-party ANALYST-consensus card
  // (factual reporting of Wall Street ratings, not the platform's verdict).
  if (r === "STRONG" || r === "FAVORABLE" || r === "STRONG_BUY" || r === "BUY")
    return { badge: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" };
  if (
    r === "WEAK" ||
    r === "VERY_WEAK" ||
    r === "STRONG_SELL" ||
    r === "SELL" ||
    r === "REDUCE" ||
    r === "AVOID"
  )
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
