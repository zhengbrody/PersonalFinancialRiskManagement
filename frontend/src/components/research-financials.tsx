"use client";

/**
 * Institutional Research FactPack (Phase 1) — minimal, deterministic view.
 *
 * Shows the company snapshot, the backend-computed trend summary (TTM, YoY/QoQ,
 * margins, acceleration flags), a compact quarterly table, and — per product
 * principle — EXPLICIT provenance + missing-data + a data-confidence score.
 * Every figure here comes straight from the backend; nothing is computed or
 * inferred in the client or by an LLM.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useResearchFinancials, type ResearchFactPack } from "@/lib/queries";

const fmtUsd = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};
const fmtPct = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)}%`;
const fmtNum = (v: number | null | undefined, d = 2): string =>
  v == null || !Number.isFinite(v) ? "—" : v.toFixed(d);

const confidenceTone: Record<string, string> = {
  high: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  medium: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  low: "bg-red-500/15 text-red-700 dark:text-red-300",
};

export function ResearchFinancials({
  ticker,
  data,
}: {
  ticker: string | null;
  data?: ResearchFactPack;
}) {
  // When `data` is supplied (from the consolidated bundle), render it directly
  // and skip the per-section fetch; otherwise self-fetch by ticker.
  const q = useResearchFinancials(data ? null : ticker);

  if (!ticker && !data) return null;
  if (!data) {
    if (q.isLoading) {
      return (
        <Card>
          <CardContent className="space-y-3 py-6">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-40 w-full" />
          </CardContent>
        </Card>
      );
    }
    if (q.isError || !q.data) {
      return (
        <Card>
          <CardContent className="py-6 text-sm text-muted-foreground">
            Couldn&apos;t load the financial fact pack right now. The deterministic figures load
            from the backend — please try again in a moment.
          </CardContent>
        </Card>
      );
    }
  }

  const fp = data ?? q.data!.fact_pack;
  return (
    <div className="space-y-4">
      <Snapshot fp={fp} />
      <TrendSummary fp={fp} />
      <QuarterTable fp={fp} />
      <Provenance fp={fp} />
      <p className="text-[11px] leading-relaxed text-muted-foreground">{fp.disclaimer}</p>
    </div>
  );
}

function Snapshot({ fp }: { fp: ResearchFactPack }) {
  const s = fp.snapshot;
  const label = fp.confidence_label;
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">
            {s.name ?? fp.ticker}{" "}
            <span className="text-sm font-normal text-muted-foreground">({fp.ticker})</span>
          </CardTitle>
          <span
            className={`rounded px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ${confidenceTone[label] ?? confidenceTone.low}`}
            title="Deterministic data-confidence score (history depth + critical fields + freshness)"
          >
            Data confidence: {label} ({Math.round(fp.data_confidence * 100)}%)
          </span>
        </div>
        <CardDescription>
          {[s.sector, s.industry, s.exchange].filter(Boolean).join(" · ") || "—"}
          {fp.as_of ? ` · as of ${fp.as_of}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
        <Field label="Price" value={s.price == null ? "—" : `$${fmtNum(s.price)}`} />
        <Field label="Market cap" value={fmtUsd(s.market_cap)} />
        <Field label="TTM revenue" value={fmtUsd(fp.trend.ttm_revenue)} />
        <Field label="TTM EPS" value={fmtNum(fp.trend.ttm_eps)} />
      </CardContent>
    </Card>
  );
}

function TrendSummary({ fp }: { fp: ResearchFactPack }) {
  const t = fp.trend;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Financial trend (deterministic)</CardTitle>
        <CardDescription>
          {t.quarters_used} quarters · {t.annuals_used} fiscal years analyzed
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
          <Field label="Revenue YoY" value={fmtPct(t.revenue_yoy)} />
          <Field label="Revenue QoQ" value={fmtPct(t.revenue_qoq)} />
          <Field label="EPS YoY" value={fmtPct(t.eps_yoy)} />
          <Field label="Net-income YoY" value={fmtPct(t.net_income_yoy)} />
          <Field label="Gross margin Δ YoY" value={fmtPct(t.gross_margin_delta_yoy)} />
          <Field label="Op margin Δ YoY" value={fmtPct(t.operating_margin_delta_yoy)} />
          <Field label="Net margin Δ YoY" value={fmtPct(t.net_margin_delta_yoy)} />
          <Field label="Revenue trend" value={t.revenue_trend ?? "—"} />
        </div>
        {t.flags.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {t.flags.map((f) => (
              <li
                key={f}
                className="rounded bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
              >
                {f}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function QuarterTable({ fp }: { fp: ResearchFactPack }) {
  if (fp.quarters.length === 0) return null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Quarterly financials</CardTitle>
        <CardDescription>Newest first · margins computed in backend code</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-right text-sm tabular-nums">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="py-1.5 text-left font-medium">Period</th>
              <th className="font-medium">Revenue</th>
              <th className="font-medium">Gross %</th>
              <th className="font-medium">Op %</th>
              <th className="font-medium">Net %</th>
              <th className="font-medium">EPS</th>
            </tr>
          </thead>
          <tbody>
            {fp.quarters.map((q) => (
              <tr key={q.period} className="border-b border-border/40">
                <td className="py-1.5 text-left font-medium">{q.period}</td>
                <td>{fmtUsd(q.revenue)}</td>
                <td>{fmtPct(q.gross_margin)}</td>
                <td>{fmtPct(q.operating_margin)}</td>
                <td>{fmtPct(q.net_margin)}</td>
                <td>{fmtNum(q.eps)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Provenance({ fp }: { fp: ResearchFactPack }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Sources &amp; data gaps</CardTitle>
        <CardDescription>Provenance and any missing data are shown explicitly.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <ul className="space-y-1">
          {fp.provenance.map((p) => (
            <li key={p.dataset} className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="text-muted-foreground">{p.dataset}</span>
              <span className="font-mono text-xs">
                {p.source}
                {p.as_of ? ` · ${p.as_of}` : ""} · {Math.round(p.coverage * 100)}% coverage
                {p.note ? ` · ${p.note}` : ""}
              </span>
            </li>
          ))}
        </ul>
        {fp.missing_data.length > 0 && (
          <div className="rounded-md bg-amber-500/10 px-3 py-2">
            <p className="text-[11px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">
              Missing data
            </p>
            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
              {fp.missing_data.map((m) => (
                <li key={`${m.dataset}:${m.reason}`}>
                  {m.dataset} — {m.reason.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
