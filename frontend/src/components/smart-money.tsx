"use client";

/**
 * Smart-money (SEC 13F) views — shared by the /institutions page.
 *
 * `SmartMoneySignals` ranks the user's holdings by institutional conviction;
 * `InstitutionDeepDive` lets them pick a top filer and see its top holdings +
 * quarter-over-quarter position changes. All data is free SEC EDGAR, fail-soft
 * server-side, so these render "—"/empty rather than erroring.
 */

import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { DataTable, type Column } from "@/components/ui/data-table";
import {
  useInstitution,
  useSmartMoney,
  useTopInstitutions,
  type InstChangeRow,
  type InstHolding,
  type SmartMoneySignal,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

const SIGNAL_STYLE: Record<string, string> = {
  HIGH_CONVICTION: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  MODERATE: "bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30",
  LOW: "bg-muted text-muted-foreground border-border",
};

function signalLabel(s: string): string {
  return s === "HIGH_CONVICTION" ? "High conviction" : s === "MODERATE" ? "Moderate" : "Low";
}

export function SmartMoneySignals() {
  const q = useSmartMoney();
  const signals = q.data?.signals ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Smart money in your holdings</CardTitle>
        <CardDescription>
          How many of the ~30 most-watched institutional funds hold each of your
          positions (from their latest SEC 13F filings).
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {q.isLoading && (
          <>
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </>
        )}
        {!q.isLoading && signals.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No institutional signals yet — add holdings to your portfolio, or the
            13F data is still warming up (it can take a moment on first load).
          </p>
        )}
        {signals.map((s: SmartMoneySignal) => (
          <div
            key={s.ticker}
            className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border bg-muted/20 px-3 py-2"
          >
            <div className="flex items-center gap-3">
              <span className="font-mono font-medium">{s.ticker}</span>
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-xs font-semibold",
                  SIGNAL_STYLE[s.signal] ?? SIGNAL_STYLE.LOW,
                )}
              >
                {signalLabel(s.signal)}
              </span>
            </div>
            <div className="flex items-center gap-4 text-sm">
              <span className="text-muted-foreground">
                {s.num_institutions} fund{s.num_institutions === 1 ? "" : "s"} hold it
              </span>
              {s.top_holders.length > 0 && (
                <span className="hidden max-w-[22ch] truncate text-xs text-muted-foreground sm:inline">
                  {s.top_holders.slice(0, 3).join(", ")}
                </span>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const HOLDING_COLS: Column<InstHolding>[] = [
  { key: "ticker", header: "Ticker", render: (r) => <span className="font-sans">{r.ticker}</span>, sortValue: (r) => r.ticker },
  { key: "name", header: "Name", render: (r) => <span className="font-sans">{r.name}</span> },
  {
    key: "pct",
    header: "% of fund",
    align: "right",
    render: (r) => (r.pct_of_portfolio == null ? "—" : `${r.pct_of_portfolio.toFixed(1)}%`),
    sortValue: (r) => r.pct_of_portfolio ?? 0,
  },
  {
    key: "value",
    header: "Value",
    align: "right",
    render: (r) => (r.value == null ? "—" : fmtUsdCompact(r.value)),
    sortValue: (r) => r.value ?? 0,
  },
];

export function InstitutionDeepDive() {
  const top = useTopInstitutions();
  const [cik, setCik] = useState<string | null>(null);
  const detail = useInstitution(cik);
  const institutions = top.data?.institutions ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Institution deep-dive</CardTitle>
        <CardDescription>
          Pick a fund to see its largest positions and what it bought or sold
          last quarter.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <select
          value={cik ?? ""}
          onChange={(e) => setCik(e.target.value || null)}
          className="h-9 w-full max-w-sm rounded-md border border-border bg-background px-3 text-sm"
          aria-label="Choose an institution"
        >
          <option value="">Choose a fund…</option>
          {institutions.map((i) => (
            <option key={i.cik} value={i.cik}>
              {i.name}
            </option>
          ))}
        </select>

        {cik && detail.isLoading && <Skeleton className="h-40" />}
        {cik && detail.data && (
          <div className="space-y-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">
                Top holdings
                {detail.data.changes.latest_filing_date
                  ? ` · as of ${detail.data.changes.latest_filing_date}`
                  : ""}
              </p>
              <div className="mt-2">
                <DataTable
                  rows={detail.data.holdings}
                  columns={HOLDING_COLS}
                  rowKey={(r) => r.ticker}
                  filterKey="ticker"
                  initialSort={{ key: "pct", dir: "desc" }}
                  minWidth={420}
                  emptyText="No holdings parsed for this fund."
                />
              </div>
            </div>
            <ChangeChips changes={detail.data.changes} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ChangeChips({ changes }: { changes: InstitutionDetailChanges }) {
  const groups: { label: string; rows: InstChangeRow[]; tone: string }[] = [
    { label: "New", rows: changes.new_positions, tone: "text-emerald-600 dark:text-emerald-400" },
    { label: "Added", rows: changes.increased, tone: "text-emerald-600 dark:text-emerald-400" },
    { label: "Trimmed", rows: changes.decreased, tone: "text-amber-600 dark:text-amber-400" },
    { label: "Exited", rows: changes.exited, tone: "text-red-600 dark:text-red-400" },
  ];
  const any = groups.some((g) => g.rows.length > 0);
  if (!any) return null;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {groups.map((g) => (
        <div key={g.label} className="rounded-md border border-border bg-muted/20 p-3">
          <p className={cn("text-xs font-semibold uppercase tracking-wide", g.tone)}>
            {g.label} ({g.rows.length})
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            {g.rows.slice(0, 8).map((r) => (
              <span key={r.ticker} className="rounded bg-background px-1.5 py-0.5 font-mono text-xs">
                {r.ticker}
              </span>
            ))}
            {g.rows.length === 0 && <span className="text-xs text-muted-foreground">—</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

type InstitutionDetailChanges = NonNullable<
  ReturnType<typeof useInstitution>["data"]
>["changes"];

function fmtUsdCompact(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}
