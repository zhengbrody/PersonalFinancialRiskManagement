"use client";

/**
 * /scenarios — the "what could go wrong / am I paid for my risk?" view
 * (Phase-14 port of legacy 4_Portfolio). Two reads, both deterministic
 * (no LLM, no quota):
 *   1. Efficient frontier: your portfolio plotted against the best
 *      risk/return trade-offs — are you being paid for the risk you take?
 *   2. Scenario sweep: projected portfolio P&L across a −30%…+30% market
 *      move, with the defensive "in a crash you'd be here" callout.
 */

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  useEfficientFrontier,
  useScenarios,
  type EfficientFrontier,
  type Scenarios,
} from "@/lib/queries";

const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";

export default function ScenariosPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const frontier = useEfficientFrontier();
  const scenarios = useScenarios();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  // Run once per signed-in user; keyed on user.id so a silent token refresh
  // (which recreates the user object) doesn't recompute both reads.
  const ranFor = useRef<string | null>(null);
  useEffect(() => {
    const uid = user?.id ?? null;
    if (uid && ranFor.current !== uid) {
      ranFor.current = uid;
      frontier.mutate();
      scenarios.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  if (!configured || authLoading || !user) return <PageSkeleton />;

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-3xl font-semibold tracking-tight">Scenarios</h1>
        <p className="text-sm text-muted-foreground">
          Stress-test your portfolio before the market does. All free, no AI
          credits used.
        </p>
      </header>

      <ScenarioCard state={scenarios} />
      <FrontierCard state={frontier} />
    </div>
  );
}

// ── scenario sweep ──────────────────────────────────────────────────

function ScenarioCard({
  state,
}: {
  state: ReturnType<typeof useScenarios>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">If the market moves…</CardTitle>
        <CardDescription>
          Projected portfolio P&amp;L across a −30% to +30% market move (uses
          each holding&apos;s market beta).
        </CardDescription>
      </CardHeader>
      <CardContent>
        {(state.isIdle || state.isPending) && <Skeleton className="h-64 w-full" />}
        {state.isError && <Notice error={state.error as Error} />}
        {state.data && !state.isPending && <ScenarioView data={state.data} />}
      </CardContent>
    </Card>
  );
}

function ScenarioView({ data }: { data: Scenarios }) {
  const rows = data.scenarios.map((s) => ({
    label: `${s.shock_pct > 0 ? "+" : ""}${Math.round(s.shock_pct * 100)}%`,
    pnl: s.pnl_pct * 100,
    value: s.portfolio_value,
  }));
  const crash = data.scenarios.find((s) => Math.round(s.shock_pct * 100) === -30);

  return (
    <div className="space-y-4">
      {crash && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">
          In a <span className="font-medium">−30% market crash</span>, your
          portfolio is projected to{" "}
          <span className="font-semibold text-destructive">
            {(crash.pnl_pct * 100).toFixed(1)}%
          </span>{" "}
          (≈ {money(crash.portfolio_value)} from {money(data.total_value)}).
          Defensive ballast (cash / SGOV / trimming high-beta names) softens this.
        </div>
      )}
      <div style={{ width: "100%", height: 260 }} role="img" aria-label="Scenario P&L" data-testid="scenario-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="label" stroke={AXIS} tick={{ fontSize: 11, fill: AXIS }} tickLine={false} axisLine={{ stroke: GRID }} />
            <YAxis
              stroke={AXIS}
              tick={{ fontSize: 11, fill: AXIS }}
              width={44}
              tickFormatter={(v) => `${v}%`}
              tickLine={false}
              axisLine={false}
            />
            <ReferenceLine y={0} stroke={GRID} />
            <Tooltip content={ScenarioTip} cursor={{ fill: "hsl(var(--muted))" }} />
            <Bar dataKey="pnl" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {rows.map((r, i) => (
                <Cell key={i} fill={r.pnl >= 0 ? "hsl(142 71% 45%)" : "hsl(0 72% 51%)"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

type TipProps = {
  active?: boolean;
  payload?: ReadonlyArray<{ payload?: { label?: string; pnl?: number; value?: number } }>;
};

function ScenarioTip(props: TipProps) {
  const p = props.payload?.[0]?.payload;
  if (!props.active || !p) return null;
  return (
    <div className="rounded-md border border-border bg-card px-3 py-2 text-xs shadow-sm">
      <p className="text-muted-foreground">Market {p.label}</p>
      <p className="font-mono text-foreground">
        P&amp;L {p.pnl != null ? `${p.pnl.toFixed(1)}%` : "—"}
      </p>
      {p.value != null && <p className="font-mono text-foreground">{money(p.value)}</p>}
    </div>
  );
}

// ── efficient frontier ──────────────────────────────────────────────

function FrontierCard({
  state,
}: {
  state: ReturnType<typeof useEfficientFrontier>;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Are you paid for your risk?</CardTitle>
        <CardDescription>
          Your portfolio (◆) vs the efficient frontier — the best return
          available at each level of risk. Closer to the curve = better
          compensated.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {(state.isIdle || state.isPending) && <Skeleton className="h-64 w-full" />}
        {state.isError && <Notice error={state.error as Error} />}
        {state.data && !state.isPending && <FrontierView data={state.data} />}
      </CardContent>
    </Card>
  );
}

function FrontierView({ data }: { data: EfficientFrontier }) {
  const curve = data.frontier.map((p) => ({ x: p.vol * 100, y: p.ret * 100 }));
  const mine = [{ x: data.current.vol * 100, y: data.current.ret * 100 }];
  return (
    <div style={{ width: "100%", height: 280 }} role="img" aria-label="Efficient frontier" data-testid="frontier-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
          <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            name="Volatility"
            stroke={AXIS}
            tick={{ fontSize: 11, fill: AXIS }}
            tickFormatter={(v) => `${v.toFixed(0)}%`}
            tickLine={false}
            axisLine={{ stroke: GRID }}
            label={{ value: "Risk (annual vol)", position: "insideBottom", offset: -4, fontSize: 11, fill: AXIS }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name="Return"
            stroke={AXIS}
            tick={{ fontSize: 11, fill: AXIS }}
            tickFormatter={(v) => `${v.toFixed(0)}%`}
            width={44}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} />
          <Scatter name="Frontier" data={curve} fill="hsl(var(--primary))" line isAnimationActive={false} />
          <Scatter name="Your portfolio" data={mine} fill="hsl(var(--foreground))" shape="diamond" isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── shared ──────────────────────────────────────────────────────────

function Notice({ error }: { error: Error }) {
  const code = error instanceof ApiError ? error.code : "";
  const noPortfolio =
    code === "no_active_portfolio" || code === "no_priced_holdings" || code === "no_market_data";
  return (
    <div className="py-4 text-sm text-muted-foreground">
      {noPortfolio ? (
        <>
          No active portfolio yet.{" "}
          <Link href="/portfolios/new" className="text-primary hover:underline">
            Create one
          </Link>{" "}
          to run scenarios.
        </>
      ) : (
        "Couldn't run this right now — try again in a moment."
      )}
    </div>
  );
}

function money(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function PageSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-72 w-full" />
      <Skeleton className="h-72 w-full" />
    </div>
  );
}
