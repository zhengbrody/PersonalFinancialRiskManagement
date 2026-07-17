"use client";

/**
 * Data-coverage matrix for /research — the one panel that answers "which
 * datasets back this analysis, how fresh is each, what's missing and how
 * does that affect the conclusions". Grouped, retail-worded rows; CORE
 * datasets carry a badge; absent datasets show an honest "Unavailable" with
 * the TYPED reason (never a fake 0 or placeholder value). The unified
 * <DataConfidence> summary renders once at the top of the page
 * (ResearchTrustSummary) — deliberately NOT repeated here. Hidden while
 * loading fails — the page keeps its per-figure SourcesCard regardless.
 */

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type CoverageField,
  type ResearchCoverage,
  useResearchCoverage,
} from "@/lib/queries";

const FIELD_LABEL: Record<string, string> = {
  company_profile: "Company profile",
  price: "Price",
  technicals: "Technicals (RSI / trend)",
  profit_margins: "Profit margins",
  return_on_equity: "Return on equity",
  revenue_growth: "Revenue growth",
  valuation_pe: "P/E ratio",
  forward_pe: "Forward P/E",
  analyst_estimates: "Analyst estimates",
  institutional_ownership: "Institutional ownership",
  insider_activity: "Insider activity",
  news: "News",
  income_statement_quarterly: "Income statement (quarterly)",
  balance_sheet_quarterly: "Balance sheet (quarterly)",
  cashflow_statement_quarterly: "Cash-flow statement (quarterly)",
  earnings_history: "Earnings history",
  earnings_estimates: "Earnings estimates",
  transcripts: "Call transcripts",
  dcf_assumptions: "DCF assumptions",
};

const REASON_TEXT: Record<string, string> = {
  unsupported: "not included in the current data plan",
  no_key: "provider not configured",
  provider_error: "provider error — retry later",
  rate_limited: "provider rate-limited",
  insufficient_history: "not enough history",
  not_applicable: "not applicable for this security",
  stale_fallback: "serving a stale cached value",
  synthetic_demo: "demo input",
  empty: "nothing usable returned",
};

const TIER_STYLE: Record<string, string> = {
  primary: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  secondary: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400",
  derived: "border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-400",
};

export function ResearchCoverageCard({ ticker }: { ticker: string | null }) {
  const coverage = useResearchCoverage(ticker);
  if (!ticker || coverage.isError) return null;
  if (coverage.isLoading) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Data coverage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    );
  }
  const data = coverage.data;
  if (!data) return null;
  return <CoverageBody data={data} />;
}

function CoverageBody({ data }: { data: ResearchCoverage }) {
  const groups = groupRows(data);
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Data coverage — what backs this analysis</CardTitle>
        <CardDescription>
          Every dataset with its source, freshness and — when absent — the exact
          reason. Core datasets cap how strong any conclusion is allowed to be.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* The unified <DataConfidence> summary renders ONCE at the top of the
            research page (ResearchTrustSummary) — this card keeps only the
            dataset matrix so the same information never appears twice. */}
        <div className="space-y-3">
          {groups.map(([group, rows]) => (
            <div key={group}>
              <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group}
              </h4>
              <ul className="divide-y divide-border overflow-hidden rounded-md border border-border">
                {rows.map((r) => (
                  <CoverageRow key={r.field} row={r} />
                ))}
              </ul>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function groupRows(data: ResearchCoverage): Array<[string, CoverageField[]]> {
  const order: string[] = [];
  const by: Record<string, CoverageField[]> = {};
  for (const row of [...data.fields, ...data.missing]) {
    const g = row.group ?? "Other";
    if (!by[g]) {
      by[g] = [];
      order.push(g);
    }
    by[g].push(row);
  }
  return order.map((g) => [g, by[g]]);
}

function CoverageRow({ row }: { row: CoverageField }) {
  const present = (row.coverage ?? 0) > 0;
  const label = FIELD_LABEL[row.field] ?? row.field.replace(/_/g, " ");
  return (
    <li className="flex flex-wrap items-center gap-x-2 gap-y-1 bg-background px-2 py-1.5 text-xs">
      <span
        aria-hidden
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${present ? "bg-emerald-500" : "bg-muted-foreground/40"}`}
      />
      <span className={present ? "font-medium" : "text-muted-foreground"}>{label}</span>
      {row.critical && (
        <span className="rounded border border-border bg-muted px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          core
        </span>
      )}
      <span className="ml-auto flex flex-wrap items-center gap-1.5 text-muted-foreground">
        {present ? (
          <>
            {row.stale && (
              <span className="text-amber-600 dark:text-amber-400">stale</span>
            )}
            {row.as_of && <span>as of {row.as_of.slice(0, 10)}</span>}
            <span
              className={`rounded border px-1 py-0.5 text-[10px] font-semibold uppercase ${TIER_STYLE[row.source_type] ?? TIER_STYLE.derived}`}
            >
              {row.label ?? row.source}
              {row.source_type === "secondary" ? " · fallback" : ""}
              {row.source_type === "derived" ? " · derived" : ""}
            </span>
          </>
        ) : (
          <span className="text-amber-600 dark:text-amber-400">
            Unavailable — {REASON_TEXT[row.missing_reason ?? "empty"] ?? row.missing_reason}
          </span>
        )}
      </span>
    </li>
  );
}
