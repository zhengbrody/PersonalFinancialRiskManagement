"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
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
import { ApiError, apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useScoreActivePortfolio } from "@/lib/queries";
import { scoreResponseSchema } from "@/lib/schemas";
import type { Holding, ScoreRequest, ScoreResponse } from "@/lib/schemas";

type HoldingRow = { ticker: string; market_value: string };

const DEFAULT_ROWS: HoldingRow[] = [
  { ticker: "SPY", market_value: "60000" },
  { ticker: "BND", market_value: "40000" },
];

export default function ScorePage() {
  const [rows, setRows] = useState<HoldingRow[]>(DEFAULT_ROWS);
  const [riskPref, setRiskPref] = useState(3);
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);

  // Signed-in users get their SAVED portfolio scored automatically (no need
  // to re-type holdings) — the manual form below is an optional what-if.
  const { user, configured } = useAuth();
  const signedIn = Boolean(configured && user);
  const active = useScoreActivePortfolio();
  const scoredFor = useRef<string | null>(null);
  useEffect(() => {
    const uid = user?.id ?? null;
    if (signedIn && uid && scoredFor.current !== uid) {
      scoredFor.current = uid;
      active.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id, signedIn]);

  // What the result panel shows: a manual run takes precedence; otherwise the
  // signed-in user's auto-scored saved portfolio.
  const shown = result ?? (signedIn ? active.data ?? null : null);
  const showLoading = loading || (signedIn && !result && active.isPending);
  const showError =
    error ?? (signedIn && !result ? (active.error as ApiError | null) : null);

  function updateRow(i: number, patch: Partial<HoldingRow>) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { ticker: "", market_value: "" }]);
  }

  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    setResult(null);

    const holdings: Holding[] = rows
      .filter((r) => r.ticker.trim() !== "")
      .map((r) => ({
        ticker: r.ticker.trim().toUpperCase(),
        market_value: Number(r.market_value) || 0,
        asset_type: "public_security",
      }));

    const body: ScoreRequest = {
      holdings,
      risk_preference: riskPref,
    };

    try {
      const data = await apiFetch<ScoreResponse>("/api/v1/risk/score", {
        method: "POST",
        body,
        schema: scoreResponseSchema,
      });
      setResult(data);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          POST /api/v1/risk/score
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Portfolio score</h1>
        <p className="text-sm text-muted-foreground">
          Synthesised returns matrix when none supplied; same deterministic
          engine the Streamlit Copilot uses.
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        {/* ── form ──────────────────────────────────────────── */}
        <Card>
          <CardHeader>
            <CardTitle>{signedIn ? "What-if sandbox" : "Holdings"}</CardTitle>
            <CardDescription>
              {signedIn
                ? "Try a hypothetical mix — your saved portfolio is scored on the right."
                : "Edit, then run."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                {rows.map((row, i) => (
                  <div key={i} className="flex gap-2">
                    <Input
                      aria-label="Ticker"
                      placeholder="SPY"
                      value={row.ticker}
                      onChange={(e) => updateRow(i, { ticker: e.target.value })}
                      className="font-mono"
                    />
                    <Input
                      aria-label="Market value"
                      type="number"
                      inputMode="decimal"
                      placeholder="60000"
                      value={row.market_value}
                      onChange={(e) =>
                        updateRow(i, { market_value: e.target.value })
                      }
                      className="font-mono"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => removeRow(i)}
                      aria-label="Remove row"
                    >
                      ×
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addRow}
                >
                  + add holding
                </Button>
              </div>

              <div className="flex items-center gap-3">
                <label
                  htmlFor="risk-pref"
                  className="text-sm text-muted-foreground"
                >
                  Risk preference (1–5)
                </label>
                <Input
                  id="risk-pref"
                  type="number"
                  min={1}
                  max={5}
                  value={riskPref}
                  onChange={(e) => setRiskPref(Number(e.target.value) || 3)}
                  className="w-20 font-mono"
                />
              </div>

              <Button type="submit" disabled={loading} className="w-full">
                {loading ? "Scoring…" : "Run score"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* ── result panel ───────────────────────────────────── */}
        <div className="space-y-4">
          {signedIn && !result && active.data && (
            <p className="text-xs text-muted-foreground">
              Scored from your saved Holdings.{" "}
              <Link href="/portfolios" className="text-primary hover:underline">
                Edit holdings →
              </Link>
            </p>
          )}
          {showLoading && <ResultSkeleton />}
          {showError && !showLoading && <ScoreError error={showError} />}
          {shown && !showLoading && <ResultPanel result={shown} />}
          {!showLoading && !showError && !shown && (
            <Card>
              <CardHeader>
                <CardTitle>No score yet</CardTitle>
                <CardDescription>
                  {signedIn
                    ? "Add holdings to your portfolio, or run a what-if on the left."
                    : "Hit Run score on the left — this public sandbox uses the same scoring engine as the signed-in workflow."}
                </CardDescription>
              </CardHeader>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function ResultSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-32" />
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-16 w-40" />
        <div className="grid grid-cols-3 gap-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
        <Skeleton className="h-32" />
      </CardContent>
    </Card>
  );
}

/** Error renderer that turns the no-portfolio codes into a create-CTA. */
function ScoreError({ error }: { error: ApiError }) {
  const noPortfolio =
    error.code === "no_active_portfolio" ||
    error.code === "no_priced_holdings" ||
    error.code === "no_market_data";
  if (noPortfolio) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Set up your portfolio</CardTitle>
          <CardDescription>
            Add your holdings and we&apos;ll score the risk automatically.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/portfolios/new">
            <Button>Create a portfolio</Button>
          </Link>
        </CardContent>
      </Card>
    );
  }
  return <ErrorPanel error={error} />;
}

function ErrorPanel({ error }: { error: ApiError }) {
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">
          {error.code === "network_error" ? "Backend unreachable" : "Request failed"}
        </CardTitle>
        <CardDescription>
          <span className="font-mono text-xs">
            {error.status || "—"} · {error.code}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm">{error.message}</p>
        {error.code === "network_error" && (
          <p className="mt-3 text-xs text-muted-foreground">
            Start the backend with{" "}
            <code className="font-mono">
              uvicorn backend.app.main:app --reload --port 8000
            </code>{" "}
            from the repo root.
          </p>
        )}
        {Object.keys(error.details).length > 0 && (
          <pre className="mt-3 max-h-64 overflow-auto rounded bg-muted/40 p-3 text-xs text-muted-foreground">
            {JSON.stringify(error.details, null, 2)}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

function ResultPanel({ result }: { result: ScoreResponse }) {
  const dims = Object.values(result.dimensions);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Overall score</CardTitle>
        <CardDescription>0–1000 · MindMarket Portfolio Health</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-6xl font-semibold tracking-tight text-primary">
            {result.overall_score}
          </span>
          <span className="text-sm text-muted-foreground">
            risk pref {result.risk_preference}
          </span>
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {dims.map((d) => (
            <div
              key={d.name}
              className="rounded-lg border border-border bg-muted/30 p-3"
            >
              <div className="text-xs uppercase tracking-wide text-muted-foreground">
                {d.name}
              </div>
              <div className="mt-1 font-mono text-2xl">{Math.round(d.score)}</div>
              <div className="mt-1 text-xs text-muted-foreground">{d.status}</div>
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">Metrics</h3>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm md:grid-cols-3">
            <MetricRow label="Annual return" value={fmtPct(result.metrics.annual_return)} />
            <MetricRow label="Annual vol" value={fmtPct(result.metrics.annual_volatility)} />
            <MetricRow label="Sharpe" value={fmtNum(result.metrics.sharpe_ratio, 2)} />
            <MetricRow label="Max DD" value={fmtPct(result.metrics.max_drawdown)} />
            <MetricRow label="VaR 95 (daily)" value={fmtPct(result.metrics.var_95_daily)} />
            <MetricRow label="CVaR 95 (daily)" value={fmtPct(result.metrics.cvar_95_daily)} />
            <MetricRow label="Beta" value={fmtNum(result.metrics.beta_to_benchmark, 2)} />
            <MetricRow label="Total value" value={fmtUSD(result.metrics.total_value)} />
            <MetricRow label="Observations" value={String(result.metrics.observations ?? "—")} />
          </div>
        </div>

        {result.metrics.data_quality_notes.length > 0 && (
          <div className="rounded-md border border-warning/40 bg-warning/10 p-3 text-xs text-muted-foreground">
            <div className="font-medium text-warning">Data quality notes</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {result.metrics.data_quality_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-border/40 py-1">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function fmtNum(v: number | null | undefined, dp = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(dp);
}

function fmtUSD(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
