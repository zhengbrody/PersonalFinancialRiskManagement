"use client";

/**
 * "Test in my portfolio" — from a Research ticker, model a hypothetical change
 * to the ACTIVE book (add / increase / reduce / replace) and see the before→after
 * risk, WITHOUT touching holdings. Re-scores via the SAME deterministic
 * /risk/score (no client risk math); reuses the shared whatif row-mapping +
 * WhatIfCompare + Save-as-plan. Analysis-only just links to the full research.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Sheet } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { WhatIfCompare } from "@/components/whatif-compare";
import { SaveAsPlan } from "@/components/save-as-plan";
import { apiFetch, ApiError } from "@/lib/api";
import { track } from "@/lib/analytics";
import { usePortfolioContext } from "@/lib/portfolio-context";
import {
  applyTestOp,
  equityTickersFromHoldings,
  nonEquitySummary,
  rowsFromHoldingsAndPrices,
  type TestOp,
  type TestOpExecution,
} from "@/lib/whatif";
import { type ScoreResponse, scoreResponseSchema } from "@/lib/schemas";
import {
  useActiveScore,
  useCopilotPreferences,
  useMarketPrices,
  useMyPortfolios,
} from "@/lib/queries";

type Op = TestOp | "analysis_only";
type Row = { ticker: string; market_value: number };

const OP_LABEL: Record<Op, string> = {
  add: "Add a hypothetical position",
  increase: "Increase this position",
  reduce: "Reduce this position",
  replace: "Replace another position with it",
  analysis_only: "Analysis only (don't change the book)",
};

export function ResearchTestDrawer({
  ticker,
  open,
  onClose,
}: {
  ticker: string;
  open: boolean;
  onClose: () => void;
}) {
  const { current, activePortfolioId } = usePortfolioContext();
  const baseline = useActiveScore();
  const preferences = useCopilotPreferences();
  const myPortfolios = useMyPortfolios();
  const activeBook = useMemo(
    () => myPortfolios.data?.portfolios.find((p) => p.id === current?.id) ?? current ?? undefined,
    [myPortfolios.data, current],
  );
  const tickers = useMemo(
    () => (activeBook ? equityTickersFromHoldings(activeBook.holdings) : []),
    [activeBook],
  );
  const prices = useMarketPrices(tickers);
  const baseRows = useMemo<Row[]>(
    () =>
      rowsFromHoldingsAndPrices(activeBook?.holdings, prices.data).map((r) => ({
        ticker: r.ticker,
        market_value: Number(r.market_value) || 0,
      })),
    [activeBook, prices.data],
  );
  const bookTotal = useMemo(() => baseRows.reduce((s, r) => s + r.market_value, 0), [baseRows]);
  const effectiveRiskPreference =
    baseline.data?.risk_preference ??
    (preferences.data?.confirmed && preferences.data.risk_tolerance
      ? preferences.data.risk_tolerance
      : 3);
  const riskProfileReady =
    baseline.data?.risk_preference != null ||
    (!preferences.isLoading && !preferences.isError);

  const T = ticker.toUpperCase();
  const heldTicker = baseRows.some((r) => r.ticker === T);
  const [op, setOp] = useState<Op>(heldTicker ? "increase" : "add");
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<"usd" | "pct">("usd");
  const [fromTicker, setFromTicker] = useState("");
  const [sandbox, setSandbox] = useState<ScoreResponse | null>(null);
  // The execution record is frozen AT RUN TIME (incl. which leg funded a
  // replace) — the live form state can drift after the run, and the summary /
  // saved plan must describe what was actually simulated, not the current form.
  const [execution, setExecution] = useState<(TestOpExecution & { from: string }) | null>(null);
  const [showSave, setShowSave] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A portfolio switch or a new research ticker invalidates the sandbox AND the
  // form inputs — a stale amount / funding leg / op must not carry across.
  useEffect(() => {
    setSandbox(null);
    setExecution(null);
    setShowSave(false);
    setError(null);
    setAmount("");
    setFromTicker("");
    setOp(heldTicker ? "increase" : "add");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, ticker]);

  const dollars = unit === "pct" ? (Number(amount) / 100) * bookTotal : Number(amount) || 0;
  // The sandbox re-scores the priced EQUITY sleeve (the shared what-if mapping
  // drops cash & option legs); NAME what stays unchanged so the before→after
  // isn't read as a whole-book restatement when the user holds cash or options.
  const excluded = useMemo(() => nonEquitySummary(activeBook?.holdings), [activeBook]);
  // A book with NO priced equity can't produce an honest before→after — the
  // "before" would be an empty equity sleeve. Block instead of misleading.
  const equityOnlyBlocked = excluded.hasNonEquity && baseRows.length === 0;

  async function run() {
    if (!riskProfileReady || !baseline.data) return;
    setError(null);
    const result = applyTestOp(baseRows, op as TestOp, T, dollars, fromTicker);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    if (result.rows.length === 0) {
      setError("This change would leave the equity sleeve empty — nothing to score.");
      return;
    }
    setLoading(true);
    try {
      const data = await apiFetch<ScoreResponse>("/api/v1/risk/score", {
        method: "POST",
        body: {
          holdings: result.rows.map((r) => ({
            ticker: r.ticker,
            market_value: r.market_value,
            asset_type: "public_security" as const,
          })),
          risk_preference: effectiveRiskPreference,
        },
        schema: scoreResponseSchema,
      });
      setSandbox(data);
      setExecution({ ...result.execution, from: fromTicker.trim().toUpperCase() });
      setShowSave(false);
      track("research_test_completed", {}); // value-free
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  const base = baseline.data ?? null;
  const lowConfidence = (sandbox?.data_confidence?.label ?? base?.data_confidence?.label) === "low";

  return (
    <Sheet open={open} onClose={onClose} title={`Test ${T} in your portfolio`}>
      {!activePortfolioId ? (
        <p className="text-sm text-muted-foreground">
          Select a portfolio to model a change. This never touches your holdings.
        </p>
      ) : (
        <div className="space-y-4 text-sm">
          <p className="text-xs text-muted-foreground">
            Simulation only · your holdings are never changed.
          </p>
          {excluded.hasNonEquity && (
            <p className="text-[11px] text-muted-foreground">
              This sandbox re-scores only the equity sleeve of your portfolio.{" "}
              {[
                excluded.optionCount > 0
                  ? `${excluded.optionCount} option position${excluded.optionCount === 1 ? "" : "s"}`
                  : null,
                excluded.cashCount > 0 ? "your cash balance" : null,
              ]
                .filter(Boolean)
                .join(" and ")}{" "}
              stay unchanged — option Greeks and cash deployment are not modeled here. See the{" "}
              <Link href="/risk" className="text-primary hover:underline">
                Risk Report
              </Link>{" "}
              for full option analytics.
            </p>
          )}
          {equityOnlyBlocked && (
            <div className="space-y-2 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
              <p>
                Your active portfolio has no priced equity positions, so an equity-only before →
                after would be misleading — the &quot;before&quot; side would be an empty book.
                Add an equity holding to test {T} against your portfolio.
              </p>
              <Link href="/research" className="font-medium text-primary hover:underline">
                Open the full research on {T} →
              </Link>
            </div>
          )}

          {!equityOnlyBlocked && (
          <>
          <label className="block space-y-1">
            <span className="font-medium">What to model</span>
            <select
              value={op}
              onChange={(e) => {
                setOp(e.target.value as Op);
                setSandbox(null);
                setExecution(null);
              }}
              className="w-full rounded border border-border bg-background px-2 py-1.5"
            >
              {(Object.keys(OP_LABEL) as Op[])
                .filter((o) => (o === "reduce" || o === "replace" ? baseRows.length > 0 : true))
                .map((o) => (
                  <option key={o} value={o}>
                    {OP_LABEL[o]}
                  </option>
                ))}
            </select>
          </label>

          {op === "analysis_only" ? (
            <Link href="/research" className="font-medium text-primary hover:underline">
              Open the full research on {T} →
            </Link>
          ) : (
            <>
              {op === "replace" && (
                <label className="block space-y-1">
                  <span className="font-medium">Replace which position?</span>
                  <select
                    value={fromTicker}
                    onChange={(e) => setFromTicker(e.target.value)}
                    className="w-full rounded border border-border bg-background px-2 py-1.5"
                  >
                    <option value="">Select…</option>
                    {baseRows
                      .filter((r) => r.ticker !== T)
                      .map((r) => (
                        <option key={r.ticker} value={r.ticker}>
                          {r.ticker}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              <div className="flex items-end gap-2">
                <label className="block flex-1 space-y-1">
                  <span className="font-medium">
                    {op === "reduce" ? "Reduce by" : "Amount"}
                  </span>
                  <input
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    inputMode="decimal"
                    placeholder={unit === "usd" ? "$ value" : "% of portfolio"}
                    className="w-full rounded border border-border bg-background px-2 py-1.5 tabular-nums"
                  />
                </label>
                <div className="flex overflow-hidden rounded border border-border">
                  {(["usd", "pct"] as const).map((u) => (
                    <button
                      key={u}
                      type="button"
                      onClick={() => setUnit(u)}
                      className={`px-2 py-1.5 text-xs ${unit === u ? "bg-primary text-primary-foreground" : "text-muted-foreground"}`}
                    >
                      {u === "usd" ? "$" : "%"}
                    </button>
                  ))}
                </div>
              </div>
              {unit === "pct" && bookTotal > 0 && amount && (
                <p className="text-[11px] text-muted-foreground">
                  ≈ ${Math.round(dollars).toLocaleString()} of your ~$
                  {Math.round(bookTotal).toLocaleString()} book
                </p>
              )}

              <Button
                type="button"
                size="sm"
                disabled={loading || !riskProfileReady || !baseline.data}
                onClick={run}
              >
                {loading
                  ? "Scoring…"
                  : riskProfileReady && baseline.data
                    ? "See before → after"
                    : "Loading portfolio baseline…"}
              </Button>
              {error && <p className="text-destructive">{error}</p>}

              {sandbox && base && (
                <div className="space-y-3 rounded-lg border border-border bg-muted/20 p-3">
                  {lowConfidence && (
                    <p className="text-[11px] text-amber-600 dark:text-amber-400">
                      {T}&apos;s data is incomplete — treat this comparison as low-confidence.
                    </p>
                  )}
                  {execution && op === "replace" && (
                    <ReplaceExecutionSummary
                      execution={execution}
                      target={T}
                      from={execution.from}
                    />
                  )}
                  {execution && op === "reduce" && execution.residual > 0 && (
                    <p className="text-[11px] text-muted-foreground">
                      You asked to reduce {T} by ${Math.round(execution.requested).toLocaleString()},
                      but the position is only worth $
                      {Math.round(execution.applied).toLocaleString()} — the simulation removed the
                      full position and nothing more.
                    </p>
                  )}
                  <WhatIfCompare
                    baseline={base}
                    sandbox={sandbox}
                    onReset={() => {
                      setSandbox(null);
                      setShowSave(false);
                    }}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    {!showSave && (
                      <Button type="button" size="sm" onClick={() => setShowSave(true)}>
                        Save as risk plan
                      </Button>
                    )}
                    <Link href="/analyze?view=stress">
                      <Button type="button" size="sm" variant="outline">
                        Open in Analyze → Stress
                      </Button>
                    </Link>
                  </div>
                  {showSave && (
                    <SaveAsPlan
                      portfolioId={activePortfolioId}
                      source="research"
                      baseline={base}
                      sandbox={sandbox}
                      proposedChanges={{
                        op,
                        ticker: T,
                        // Persist what the simulation ACTUALLY moved — a plan
                        // must never claim a bigger move than was funded.
                        amount_usd: execution?.applied ?? dollars,
                        ...(execution && execution.residual > 0
                          ? { requested_usd: execution.requested }
                          : {}),
                        // The leg that funded the EXECUTED run — never the
                        // live select (it can drift after the run).
                        from: execution?.from || null,
                      }}
                      onSaved={() => setShowSave(false)}
                      onCancel={() => setShowSave(false)}
                    />
                  )}
                </div>
              )}
            </>
          )}
          </>
          )}
        </div>
      )}
    </Sheet>
  );
}

/** The honest ledger of a replace simulation: what was requested, what the
 * funding leg could actually free, what was deployed into the target, and any
 * residual that was NOT deployed — with a one-line English reason. */
function ReplaceExecutionSummary({
  execution,
  target,
  from,
}: {
  execution: TestOpExecution;
  target: string;
  from: string;
}) {
  const fmt = (n: number) => `$${Math.round(n).toLocaleString()}`;
  const partial = execution.residual > 0;
  return (
    <div className="space-y-1.5 text-[11px]" data-testid="replace-execution-summary">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 tabular-nums sm:grid-cols-4">
        <div>
          <dt className="text-muted-foreground">Requested</dt>
          <dd className="font-medium">{fmt(execution.requested)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Freed from {from}</dt>
          <dd className="font-medium">{fmt(execution.applied)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Deployed into {target}</dt>
          <dd className="font-medium">{fmt(execution.applied)}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Not deployed</dt>
          <dd className={partial ? "font-medium text-amber-600 dark:text-amber-400" : "font-medium"}>
            {fmt(execution.residual)}
          </dd>
        </div>
      </dl>
      {partial && (
        <p className="text-muted-foreground">
          Your {from} position is worth only {fmt(execution.applied)}, so the simulation moved{" "}
          {fmt(execution.applied)} instead of the requested {fmt(execution.requested)} — it never
          creates exposure that isn&apos;t funded by the position you&apos;re replacing.
        </p>
      )}
    </div>
  );
}
