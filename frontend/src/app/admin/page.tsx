"use client";

/**
 * /admin — owner-only usage & cost dashboard.
 *
 * Reads the month-to-date aggregates the backend already logs to
 * usage_events (tokens / $ / credits, per kind + per user) so the owner
 * can SEE real spend and calibrate the credit budgets. The endpoint
 * 403s for non-owners; this page surfaces that as a friendly notice.
 */

import { useEffect, useState } from "react";
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
import { useAdminStatus, useAdminUsage, type AdminStatus } from "@/lib/queries";
import { cn } from "@/lib/utils";

export default function AdminPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const usage = useAdminUsage(Boolean(user));
  const [liveChecks, setLiveChecks] = useState(false);
  const status = useAdminStatus(Boolean(user), liveChecks);

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  if (!configured || authLoading || !user) return <PageSkeleton />;

  if (usage.isError) {
    const forbidden =
      usage.error instanceof ApiError && usage.error.status === 403;
    return (
      <div className="mx-auto max-w-2xl">
        <Card>
          <CardHeader>
            <CardTitle>{forbidden ? "Owner only" : "Could not load usage"}</CardTitle>
            <CardDescription>
              {forbidden
                ? "This dashboard is restricted to the account owner."
                : (usage.error as Error).message}
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  if (usage.isLoading || !usage.data) return <PageSkeleton />;

  const { totals, by_kind, users, since } = usage.data;
  const sinceLabel = formatSinceUtc(since);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Usage & cost</h1>
        <p className="text-sm text-muted-foreground">
          Month to date{sinceLabel ? ` (since ${sinceLabel})` : ""} ·
          metered from real token cost. 1 cost unit = $0.01.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Events" value={(totals.events ?? 0).toLocaleString()} />
        <Stat label="Cost" value={`$${(totals.cost_usd ?? 0).toFixed(2)}`} />
        <Stat label="Cost units" value={(totals.credits ?? 0).toLocaleString()} />
        <Stat
          label="Tokens"
          value={fmtTokens((totals.tokens_in ?? 0) + (totals.tokens_out ?? 0))}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">By kind</CardTitle>
        </CardHeader>
        <CardContent>
          <Table
            head={["Kind", "Events", "Cost", "Cost units"]}
            rows={Object.entries(by_kind).map(([k, v]) => [
              k,
              (v.events ?? 0).toLocaleString(),
              `$${(v.cost_usd ?? 0).toFixed(2)}`,
              (v.credits ?? 0).toLocaleString(),
            ])}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top users by spend</CardTitle>
          <CardDescription>{users.length} active this month</CardDescription>
        </CardHeader>
        <CardContent>
          <Table
            head={["User", "Events", "Cost", "Cost units"]}
            rows={users.map((u) => [
              u.user_id.slice(0, 8) + "…",
              (u.events ?? 0).toLocaleString(),
              `$${(u.cost_usd ?? 0).toFixed(2)}`,
              (u.credits ?? 0).toLocaleString(),
            ])}
            mono
          />
        </CardContent>
      </Card>

      <SystemStatus
        data={status.data}
        loading={status.isLoading}
        live={liveChecks}
        onRunLive={() => setLiveChecks(true)}
      />
    </div>
  );
}

const STATE_TONE: Record<string, string> = {
  Connected: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  Configured: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30",
  Missing: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
  Error: "bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30",
};

function SystemStatus({
  data,
  loading,
  live,
  onRunLive,
}: {
  data: AdminStatus | undefined;
  loading: boolean;
  live: boolean;
  onRunLive: () => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">System status</CardTitle>
            <CardDescription>
              Server-side integration keys{live ? " · live-validated" : " · presence only"}.
            </CardDescription>
          </div>
          <Button size="sm" variant="outline" disabled={live && loading} onClick={onRunLive}>
            {live ? (loading ? "Checking…" : "Re-check live") : "Run live checks"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {loading && !data && (
          <>
            <Skeleton className="h-9" />
            <Skeleton className="h-9" />
          </>
        )}
        {data?.integrations.map((i) => (
          <div
            key={i.name}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-muted/20 px-3 py-2"
          >
            <span className="text-sm font-medium">{i.name}</span>
            <div className="flex items-center gap-3">
              <span className="hidden text-xs text-muted-foreground sm:inline">{i.detail}</span>
              <span
                className={cn(
                  "rounded-full border px-2 py-0.5 text-xs font-semibold",
                  STATE_TONE[i.state] ?? "border-border text-muted-foreground",
                )}
              >
                {i.state}
              </span>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function formatSinceUtc(since: string | null | undefined) {
  if (!since) return "";
  const date = new Date(since);
  if (Number.isNaN(date.getTime())) return since;
  return `${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(date)} UTC`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Table({
  head,
  rows,
  mono,
}: {
  head: string[];
  rows: string[][];
  mono?: boolean;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No usage yet.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[360px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            {head.map((h) => (
              <th key={h} className="py-2 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-border/50">
              {r.map((c, j) => (
                <td
                  key={j}
                  className={`py-2 pr-4 tabular-nums ${mono && j === 0 ? "font-mono text-xs" : ""}`}
                >
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtTokens(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(n);
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}
