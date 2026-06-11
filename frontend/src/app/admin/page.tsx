"use client";

/**
 * /admin — owner-only usage & cost dashboard.
 *
 * Reads the month-to-date aggregates the backend already logs to
 * usage_events (tokens / $ / credits, per kind + per user) so the owner
 * can SEE real spend and calibrate the credit budgets. The endpoint
 * 403s for non-owners; this page surfaces that as a friendly notice.
 */

import { useEffect, useRef, useState } from "react";
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
  useAdminMetrics,
  useAdminStatus,
  useAdminUsage,
  type AdminMetrics,
  type AdminStatus,
} from "@/lib/queries";
import { cn } from "@/lib/utils";

export default function AdminPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const usage = useAdminUsage(Boolean(user));
  const [liveChecks, setLiveChecks] = useState(false);
  const status = useAdminStatus(Boolean(user), liveChecks);
  // Only poll the live-metrics endpoint once usage confirms this caller is the
  // owner — otherwise a non-owner would 403 every 4s.
  const isOwner = Boolean(usage.data) && !usage.isError;
  const metrics = useAdminMetrics(isOwner);

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

  const { totals, by_kind, by_model, users, since } = usage.data;
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

      <LiveActivity data={metrics.data} loading={metrics.isLoading} />

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

      {by_model && Object.keys(by_model).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">By model</CardTitle>
            <CardDescription>AI spend split by the model that served it.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table
              head={["Model", "Events", "Tokens", "Cost", "Cost units"]}
              rows={Object.entries(by_model)
                .sort((a, b) => (b[1].cost_usd ?? 0) - (a[1].cost_usd ?? 0))
                .map(([m, v]) => [
                  m,
                  (v.events ?? 0).toLocaleString(),
                  fmtTokens((v.tokens_in ?? 0) + (v.tokens_out ?? 0)),
                  `$${(v.cost_usd ?? 0).toFixed(2)}`,
                  (v.credits ?? 0).toLocaleString(),
                ])}
            />
          </CardContent>
        </Card>
      )}

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

function LiveActivity({
  data,
  loading,
}: {
  data: AdminMetrics | undefined;
  loading: boolean;
}) {
  // Live request rate = Δrequests / Δuptime across consecutive 4s polls. The
  // server only exposes monotonic counters; the rate is derived here.
  const prev = useRef<{ total: number; uptime: number } | null>(null);
  const [rate, setRate] = useState<number | null>(null);

  useEffect(() => {
    if (!data) return;
    const p = prev.current;
    // Skip the tick where uptime went backwards (process restarted / redeployed).
    if (p && data.uptime_s > p.uptime) {
      const dReq = data.total_requests - p.total;
      const dT = data.uptime_s - p.uptime;
      if (dT > 0) setRate(Math.max(0, dReq / dT));
    }
    prev.current = { total: data.total_requests, uptime: data.uptime_s };
  }, [data]);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500/70" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              Live activity
            </CardTitle>
            <CardDescription>
              In-process counters since last deploy · auto-refresh 4s. Real $ cost
              is in the cards above.
            </CardDescription>
          </div>
          {data && (
            <span className="text-xs text-muted-foreground">up {fmtUptime(data.uptime_s)}</span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading && !data ? (
          <Skeleton className="h-24" />
        ) : !data ? (
          <p className="text-sm text-muted-foreground">No activity yet.</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <Stat label="Requests" value={data.total_requests.toLocaleString()} />
              <Stat label="Live rate" value={rate == null ? "…" : `${rate.toFixed(1)}/s`} />
              <Stat label="Errors (5xx)" value={data.total_errors.toLocaleString()} />
            </div>

            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                External data providers
              </div>
              <Table
                head={["Provider", "Calls", "OK", "Cache", "Errors", "Limited"]}
                rows={data.providers.map((p) => [
                  p.name,
                  p.calls.toLocaleString(),
                  (p.ok ?? 0).toLocaleString(),
                  (p.cache_hit ?? 0).toLocaleString(),
                  (p.error ?? 0).toLocaleString(),
                  (p.rate_limited ?? 0).toLocaleString(),
                ])}
              />
            </div>

            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">
                Top endpoints
              </div>
              <Table
                head={["Endpoint", "Count", "Avg ms", "Errors"]}
                rows={data.routes
                  .slice(0, 12)
                  .map((r) => [
                    `${r.method} ${r.route}`,
                    r.count.toLocaleString(),
                    (r.avg_ms ?? 0).toFixed(0),
                    (r.errors ?? 0).toLocaleString(),
                  ])}
                mono
              />
            </div>
          </>
        )}
      </CardContent>
    </Card>
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

function fmtUptime(s: number): string {
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m`;
  return `${Math.round(s)}s`;
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
