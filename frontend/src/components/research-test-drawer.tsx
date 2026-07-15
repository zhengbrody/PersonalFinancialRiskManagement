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
import { equityTickersFromHoldings, rowsFromHoldingsAndPrices } from "@/lib/whatif";
import { type ScoreResponse, scoreResponseSchema } from "@/lib/schemas";
import { useActiveScore, useMarketPrices, useMyPortfolios } from "@/lib/queries";

type Op = "add" | "increase" | "reduce" | "replace" | "analysis_only";
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

  const T = ticker.toUpperCase();
  const heldTicker = baseRows.some((r) => r.ticker === T);
  const [op, setOp] = useState<Op>(heldTicker ? "increase" : "add");
  const [amount, setAmount] = useState("");
  const [unit, setUnit] = useState<"usd" | "pct">("usd");
  const [fromTicker, setFromTicker] = useState("");
  const [sandbox, setSandbox] = useState<ScoreResponse | null>(null);
  const [showSave, setShowSave] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A portfolio switch or a new research ticker invalidates the sandbox AND the
  // form inputs — a stale amount / funding leg / op must not carry across.
  useEffect(() => {
    setSandbox(null);
    setShowSave(false);
    setError(null);
    setAmount("");
    setFromTicker("");
    setOp(heldTicker ? "increase" : "add");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, ticker]);

  const dollars = unit === "pct" ? (Number(amount) / 100) * bookTotal : Number(amount) || 0;
  // The sandbox re-scores the priced EQUITY sleeve (the shared what-if mapping
  // drops cash & option legs); surface that so the before→after isn't read as a
  // whole-book restatement when the user holds cash or options.
  const hasExcluded = useMemo(
    () =>
      Object.values(activeBook?.holdings ?? {}).some(
        (h) =>
          (h as { asset_type?: string })?.asset_type === "cash" ||
          (h as { asset_type?: string })?.asset_type === "option",
      ),
    [activeBook],
  );

  function applyOp(): Row[] | null {
    const rows = baseRows.map((r) => ({ ...r }));
    const idx = rows.findIndex((r) => r.ticker === T);
    if (op === "add") {
      if (idx >= 0) rows[idx].market_value += dollars;
      else rows.push({ ticker: T, market_value: dollars });
    } else if (op === "increase") {
      if (idx >= 0) rows[idx].market_value += dollars;
      else rows.push({ ticker: T, market_value: dollars });
    } else if (op === "reduce") {
      if (idx < 0) return null;
      rows[idx].market_value = Math.max(0, rows[idx].market_value - dollars);
    } else if (op === "replace") {
      const from = fromTicker.toUpperCase();
      if (!from || from === T) return null; // must fund from a DIFFERENT position
      const fi = rows.findIndex((r) => r.ticker === from);
      if (fi < 0) return null;
      // Conserve book value: only what's actually freed from the funding leg
      // moves into the target — never fabricate exposure larger than the source.
      const freed = Math.min(dollars, rows[fi].market_value);
      rows[fi].market_value -= freed;
      if (idx >= 0) rows[idx].market_value += freed;
      else rows.push({ ticker: T, market_value: freed });
    }
    return rows.filter((r) => r.market_value > 0);
  }

  async function run() {
    setError(null);
    if (!(dollars > 0)) {
      setError("Enter an amount first.");
      return;
    }
    const rows = applyOp();
    if (!rows || rows.length === 0) {
      setError("Pick a position and an amount first.");
      return;
    }
    setLoading(true);
    try {
      const data = await apiFetch<ScoreResponse>("/api/v1/risk/score", {
        method: "POST",
        body: {
          holdings: rows.map((r) => ({
            ticker: r.ticker,
            market_value: r.market_value,
            asset_type: "public_security" as const,
          })),
          risk_preference: 3,
        },
        schema: scoreResponseSchema,
      });
      setSandbox(data);
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
          {hasExcluded && (
            <p className="text-[11px] text-muted-foreground">
              Compares your priced equity positions — cash &amp; options are excluded from this
              before → after.
            </p>
          )}

          <label className="block space-y-1">
            <span className="font-medium">What to model</span>
            <select
              value={op}
              onChange={(e) => {
                setOp(e.target.value as Op);
                setSandbox(null);
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

              <Button type="button" size="sm" disabled={loading} onClick={run}>
                {loading ? "Scoring…" : "See before → after"}
              </Button>
              {error && <p className="text-destructive">{error}</p>}

              {sandbox && base && (
                <div className="space-y-3 rounded-lg border border-border bg-muted/20 p-3">
                  {lowConfidence && (
                    <p className="text-[11px] text-amber-600 dark:text-amber-400">
                      {T}&apos;s data is incomplete — treat this comparison as low-confidence.
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
                      proposedChanges={{ op, ticker: T, amount_usd: dollars, from: fromTicker || null }}
                      onSaved={() => setShowSave(false)}
                      onCancel={() => setShowSave(false)}
                    />
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}
