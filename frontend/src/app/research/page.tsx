"use client";

/**
 * Ticker Research 2.0 — single-name FactPack cockpit.
 *
 * Two-stage, Robinhood-skin / Citadel-bone:
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
import { DataTable, type Column } from "@/components/ui/data-table";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { track } from "@/lib/analytics";
import {
  useBillingMe,
  useFactPack,
  useResearchVerdict,
  type FactPack,
  type ResearchVerdict,
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
          Look up any stock. The fact pack lands first — valuation, quality,
          growth, the Street&apos;s view, peers and news, each tagged with its
          source. The AI analyst&apos;s plain-English verdict follows a moment
          later, phrasing those numbers, never inventing them.
        </p>
      </header>

      <ResearchWorkbench />
    </div>
  );
}

function ResearchWorkbench() {
  const [symbol, setSymbol] = useState("");
  const factM = useFactPack();
  const verdictM = useResearchVerdict();

  async function run(raw: string) {
    const ticker = raw.trim().toUpperCase();
    if (!ticker || factM.isPending) return;
    verdictM.reset();
    // Privacy: never send the ticker itself to analytics — searching a
    // symbol can reveal what the user holds.
    track("research_searched");
    try {
      const { fact_pack } = await factM.mutateAsync({ ticker });
      verdictM.mutate({ fact_pack });
    } catch {
      // factM.error renders below.
    }
  }

  const fp = factM.data?.fact_pack;

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
        <Button type="submit" disabled={factM.isPending || symbol.trim() === ""}>
          {factM.isPending ? "Loading…" : "Research"}
        </Button>
      </form>

      {factM.isPending && <FactPackSkeleton />}

      {factM.error && !factM.isPending && <ErrorCard error={factM.error} />}

      {fp && !factM.isPending && (
        <>
          <FactPackHeader fp={fp} />
          <VerdictSection
            pending={verdictM.isPending}
            error={verdictM.error}
            verdict={verdictM.data?.verdict}
          />
          <ValuationCard fp={fp} />
          <QualityCard fp={fp} />
          <GrowthCard fp={fp} />
          <AnalystCard fp={fp} />
          <SignalsCard fp={fp} />
          {fp.peers.length > 0 && <PeersCard fp={fp} />}
          {fp.news.length > 0 && <NewsCard news={fp.news} />}
        </>
      )}

      {!fp && !factM.isPending && !factM.error && <EmptyState />}
    </div>
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
            <DataQualityBadge fp={fp} />
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

function DataQualityBadge({ fp }: { fp: FactPack }) {
  const [open, setOpen] = useState(false);
  const dq = fp.data_quality;
  const coverage = dq?.coverage;
  const sources = dq?.sources ?? [];
  const warnings = dq?.warnings ?? [];
  const usesFree =
    sources.some((s) => s.source === "yfinance") ||
    warnings.includes("fmp_key_missing");
  const tone =
    coverage == null
      ? "text-muted-foreground"
      : coverage >= 0.75
        ? "text-emerald-600 dark:text-emerald-400"
        : coverage >= 0.4
          ? "text-amber-600 dark:text-amber-400"
          : "text-red-600 dark:text-red-400";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium ${tone}`}
        aria-expanded={open}
        title="Data coverage — click for source breakdown"
      >
        {coverage != null ? `${Math.round(coverage * 100)}% coverage` : "coverage"}
        {usesFree && <span className="ml-1 text-muted-foreground">· free data</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-72 rounded-md border border-border bg-card p-3 text-xs shadow-md">
          {warnings.length > 0 && (
            <ul className="mb-2 space-y-1">
              {warnings.map((w, i) => (
                <li key={i} className="text-amber-600 dark:text-amber-400">
                  {humanizeWarning(w)}
                </li>
              ))}
            </ul>
          )}
          {sources.length === 0 ? (
            <p className="text-muted-foreground">No source detail available.</p>
          ) : (
            <table className="w-full">
              <tbody>
                {sources.map((s) => (
                  <tr key={s.field} className="border-b border-border/40">
                    <td className="py-1 pr-2 text-muted-foreground">{s.field}</td>
                    <td className="py-1 pr-2 capitalize">{s.source}</td>
                    <td className="py-1 text-right tabular-nums text-muted-foreground">
                      {s.coverage != null ? `${Math.round(s.coverage * 100)}%` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
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

        <div className="grid gap-4 sm:grid-cols-2">
          <BulletCard
            title="Catalysts"
            items={verdict.catalysts}
            empty="No near-term catalysts flagged."
          />
          <BulletCard
            title="Key risks"
            items={verdict.risks}
            empty="No standout risks flagged."
            tone="danger"
          />
        </div>

        {verdict.what_would_change_my_mind.length > 0 && (
          <BulletCard
            title="What would change my mind"
            items={verdict.what_would_change_my_mind}
          />
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

// ── news ────────────────────────────────────────────────────────────

function NewsCard({ news }: { news: FactPack["news"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent news</CardTitle>
        <CardDescription>Headlines — metadata only.</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {news.map((n, i) => {
            const body = (
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium leading-snug">{n.title}</span>
                <span className="text-xs text-muted-foreground">
                  {[n.site, relativeTime(n.published)].filter(Boolean).join(" · ")}
                </span>
              </div>
            );
            return (
              <li key={i}>
                {n.url ? (
                  <a
                    href={n.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block rounded-md px-1 py-0.5 hover:bg-muted"
                  >
                    {body}
                  </a>
                ) : (
                  body
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
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
          <p className="text-sm">
            You&apos;ve used your AI analysis quota this month. The fact pack
            below is still all yours — upgrade for more AI verdicts.
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

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const diffMs = Date.now() - d.getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function humanizeWarning(w: string): string {
  if (w === "fmp_key_missing")
    return "Premium fields unavailable — built from free data.";
  return w.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function ratingTone(rating: string): { badge: string } {
  const r = rating.toUpperCase().replace(/\s+/g, "_");
  if (r === "STRONG_BUY" || r === "BUY")
    return { badge: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" };
  if (r === "STRONG_SELL" || r === "SELL" || r === "REDUCE" || r === "AVOID")
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
