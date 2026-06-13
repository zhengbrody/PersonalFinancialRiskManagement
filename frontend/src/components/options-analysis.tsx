"use client";

/**
 * Options analytics block — Black-Scholes Greeks, implied vol, mark, and an
 * at-expiry payoff curve per contract, plus a portfolio Greeks roll-up. Fed by
 * the active portfolio's option holdings (the entries with asset_type ===
 * "option"); renders nothing when the book has no options, so it's safe to drop
 * onto /risk unconditionally.
 *
 * Every number is deterministic backend math (POST /options/analyze) over free
 * yfinance chains — the LLM is not involved. A contract that couldn't be priced
 * shows its own amber warning rather than blanking the whole block.
 */

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TickerBadge } from "@/components/ui/ticker-badge";
import {
  type OptionAnalytics,
  type OptionContract,
  type OptionTotals,
  useOptionAnalytics,
} from "@/lib/queries";

export function OptionsAnalysis({ contracts }: { contracts: OptionContract[] }) {
  const analytics = useOptionAnalytics(contracts);

  if (contracts.length === 0) return null; // no options in this book

  return (
    <section className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-lg font-semibold tracking-tight">Options</h2>
        <span className="text-[11px] uppercase tracking-widest text-muted-foreground">
          Black-Scholes · yfinance chains
        </span>
      </div>

      {analytics.isPending ? (
        <div className="grid gap-3 md:grid-cols-2">
          <Skeleton className="h-48" />
          <Skeleton className="h-48" />
        </div>
      ) : analytics.isError ? (
        <Card>
          <CardHeader>
            <CardDescription className="text-sm text-muted-foreground">
              Couldn&apos;t price your options right now (market data hiccup) — your
              risk report above is unaffected. Try again in a moment.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : analytics.data ? (
        <>
          <GreeksRollup totals={analytics.data.totals} asOf={analytics.data.as_of} />
          <div className="grid gap-3 md:grid-cols-2">
            {analytics.data.results.map((r, i) => (
              <ContractCard key={r.contract_symbol ?? `${r.underlying}-${i}`} a={r} />
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

function GreeksRollup({
  totals,
  asOf,
}: {
  totals: OptionTotals;
  asOf: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          Portfolio Greeks{" "}
          <span className="font-normal text-muted-foreground">
            ({totals.contracts} contract{totals.contracts === 1 ? "" : "s"} · as of {asOf})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Net Δ" value={num(totals.net_delta, 1)} hint="share-equivalents" />
        <Stat label="Net Γ" value={num(totals.net_gamma, 2)} />
        <Stat label="Net Θ / day" value={usd(totals.net_theta)} tone={totals.net_theta < 0 ? "down" : undefined} />
        <Stat label="Net ν / 1%" value={usd(totals.net_vega)} />
        <Stat label="Δ-notional" value={usd(totals.delta_notional)} hint="directional $" />
        <Stat
          label="Unreal. P&L"
          value={totals.unrealized_pnl == null ? "—" : usd(totals.unrealized_pnl)}
          tone={totals.unrealized_pnl != null ? (totals.unrealized_pnl >= 0 ? "up" : "down") : undefined}
        />
      </CardContent>
    </Card>
  );
}

function ContractCard({ a }: { a: OptionAnalytics }) {
  const dir = a.option_type === "call" ? "CALL" : "PUT";
  const pnl = a.unrealized_pnl;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          <TickerBadge ticker={a.underlying} />
          <span className="font-mono">
            {dir} {a.strike}
          </span>
          <span className="text-muted-foreground">{shortExpiry(a.expiry)}</span>
          {a.moneyness && <Chip label={a.moneyness} tone={a.moneyness === "ITM" ? "up" : a.moneyness === "OTM" ? "muted" : undefined} />}
          <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
            {a.days_to_expiry}d
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Greeks row */}
        {a.greeks ? (
          <div className="grid grid-cols-4 gap-2 text-xs">
            <Stat label="Δ" value={num(a.greeks.delta, 3)} />
            <Stat label="Γ" value={num(a.greeks.gamma, 4)} />
            <Stat label="Θ/day" value={num(a.greeks.theta, 3)} tone={a.greeks.theta < 0 ? "down" : undefined} />
            <Stat label="ν/1%" value={num(a.greeks.vega, 3)} />
          </div>
        ) : (
          <p className="text-xs text-amber-600 dark:text-amber-400">
            {a.warnings[0] ?? "Greeks unavailable for this contract."}
          </p>
        )}

        {/* Price facts */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
          <Stat label="Spot" value={a.spot == null ? "—" : usd(a.spot)} />
          <Stat label="Mark" value={a.mark == null ? "—" : `$${a.mark.toFixed(2)}`} />
          <Stat label="IV" value={a.iv == null ? "—" : pct(a.iv)} />
          <Stat label="Mkt value" value={a.market_value == null ? "—" : usd(a.market_value)} />
          {a.break_even != null && <Stat label="Break-even" value={usd(a.break_even)} />}
          {pnl != null && (
            <Stat label="P&L" value={usd(pnl)} tone={pnl >= 0 ? "up" : "down"} />
          )}
        </div>

        {a.payoff.length > 0 && <PayoffChart a={a} />}
      </CardContent>
    </Card>
  );
}

/** At-expiry P&L vs underlying price, with a zero line + break-even marker. */
function PayoffChart({ a }: { a: OptionAnalytics }) {
  return (
    <div>
      <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        P&amp;L at expiry
      </p>
      <ResponsiveContainer width="100%" height={120}>
        <LineChart data={a.payoff} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="hsl(var(--border))" strokeDasharray="2 4" vertical={false} />
          <XAxis
            dataKey="price"
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            tickFormatter={(v: number) => `$${Math.round(v)}`}
            type="number"
            domain={["dataMin", "dataMax"]}
          />
          <YAxis
            tick={{ fontSize: 10, fill: "hsl(var(--muted-foreground))" }}
            tickFormatter={(v: number) => (Math.abs(v) >= 1000 ? `${Math.round(v / 1000)}k` : `${Math.round(v)}`)}
            width={34}
          />
          <Tooltip
            contentStyle={{
              background: "hsl(var(--popover))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 6,
              fontSize: 11,
            }}
            formatter={(v) => [usd(Number(v ?? 0)), "P&L"]}
            labelFormatter={(v) => `Underlying $${Number(v).toFixed(0)}`}
          />
          <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" strokeWidth={1} />
          {a.break_even != null && (
            <ReferenceLine x={a.break_even} stroke="hsl(var(--primary))" strokeDasharray="3 3" />
          )}
          <Line
            type="monotone"
            dataKey="pnl"
            stroke="hsl(var(--primary))"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── small presentational helpers ──────────────────────────────────────────────

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "up" | "down";
}) {
  return (
    <div className="space-y-0.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p
        className={`font-mono tabular-nums ${
          tone === "up"
            ? "text-emerald-600 dark:text-emerald-400"
            : tone === "down"
              ? "text-red-600 dark:text-red-400"
              : ""
        }`}
      >
        {value}
      </p>
      {hint && <p className="text-[9px] text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Chip({ label, tone }: { label: string; tone?: "up" | "muted" }) {
  return (
    <span
      className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
        tone === "up"
          ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : tone === "muted"
            ? "border-border bg-muted/50 text-muted-foreground"
            : "border-primary/40 bg-primary/10 text-primary"
      }`}
    >
      {label}
    </span>
  );
}

function num(v: number, dp: number): string {
  return v.toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
}

function usd(v: number): string {
  const sign = v < 0 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

function shortExpiry(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "2-digit" });
}
