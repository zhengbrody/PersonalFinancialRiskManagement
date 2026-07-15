"use client";

/**
 * Reusable What-if lab. Loads the ACTIVE book's holdings into editable sandbox
 * rows, lets the user nudge them (±10% or free edit), re-scores via the SAME
 * deterministic backend the public sandbox uses (POST /risk/score — no
 * client-side risk math), and shows a before→after <WhatIfCompare> vs the
 * baseline the caller passes. Simulation only — holdings are never mutated.
 *
 * Registers an unsaved-analysis guard with the portfolio context so switching
 * the active book while a run is unsaved prompts Save/Discard, and offers
 * "Save as risk plan" (PR2). The scoring algorithm + row-mapping are the shared
 * lib/whatif + /risk/score; this is only the focused UI.
 */

import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { WhatIfCompare } from "@/components/whatif-compare";
import { SaveAsPlan } from "@/components/save-as-plan";
import { apiFetch, ApiError } from "@/lib/api";
import { track } from "@/lib/analytics";
import { usePortfolioContext } from "@/lib/portfolio-context";
import {
  equityTickersFromHoldings,
  rowsFromHoldingsAndPrices,
  scaleValue,
} from "@/lib/whatif";
import { type ScoreResponse, scoreResponseSchema } from "@/lib/schemas";
import { type RiskPlan, useMarketPrices, useMyPortfolios } from "@/lib/queries";

type HoldingRow = { ticker: string; market_value: string };

export function WhatIfLab({
  baseline,
  riskPreference = 3,
  saveContext,
}: {
  baseline: ScoreResponse | null;
  riskPreference?: number;
  /** When present, offer "Save as risk plan" tied to the LIVE sandbox (the save
   *  form + its portfolio_id/source always match the sandbox on screen — no
   *  frozen prior-book snapshot can be persisted). */
  saveContext?: { portfolioId: string | null; source: RiskPlan["source"] };
}) {
  const { current, registerUnsavedGuard } = usePortfolioContext();
  const [rows, setRows] = useState<HoldingRow[]>([]);
  const [sandbox, setSandbox] = useState<ScoreResponse | null>(null);
  const [showSave, setShowSave] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const myPortfolios = useMyPortfolios();
  const activeBook = useMemo(
    () => myPortfolios.data?.portfolios.find((p) => p.id === current?.id) ?? current ?? undefined,
    [myPortfolios.data, current],
  );
  const equityTickers = useMemo(
    () => (activeBook ? equityTickersFromHoldings(activeBook.holdings) : []),
    [activeBook],
  );
  const bookPrices = useMarketPrices(equityTickers);
  const canLoad = equityTickers.length > 0 && Boolean(bookPrices.data);

  // Unsaved-analysis guard: a sandbox run that hasn't been saved is "dirty".
  useEffect(
    () => registerUnsavedGuard("whatif-lab", () => sandbox !== null),
    [registerUnsavedGuard, sandbox],
  );
  // A portfolio switch invalidates the sandbox (it belonged to the prior book).
  useEffect(() => {
    setRows([]);
    setSandbox(null);
    setShowSave(false);
    setError(null);
  }, [current?.id]);

  function loadMyHoldings() {
    const loaded = rowsFromHoldingsAndPrices(activeBook?.holdings, bookPrices.data);
    if (loaded.length === 0) return;
    setRows(loaded);
    setSandbox(null);
    setShowSave(false);
    track("whatif_loaded_holdings");
  }

  function nudge(i: number, factor: number) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, market_value: scaleValue(r.market_value, factor) } : r)));
  }
  function updateRow(i: number, patch: Partial<HoldingRow>) {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }
  function removeRow(i: number) {
    setRows((prev) => prev.filter((_, idx) => idx !== i));
  }

  async function run() {
    setError(null);
    setLoading(true);
    try {
      const holdings = rows
        .filter((r) => r.ticker.trim() !== "")
        .map((r) => ({
          ticker: r.ticker.trim().toUpperCase(),
          market_value: Number(r.market_value) || 0,
          asset_type: "public_security" as const,
        }));
      const data = await apiFetch<ScoreResponse>("/api/v1/risk/score", {
        method: "POST",
        body: { holdings, risk_preference: riskPreference },
        schema: scoreResponseSchema,
      });
      setSandbox(data);
      setShowSave(false); // a new run dismisses any open save form (no stale save)
      track("whatif_run");
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" disabled={!canLoad} onClick={loadMyHoldings}>
          Start from my holdings
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => setRows((p) => [...p, { ticker: "", market_value: "" }])}>
          Add row
        </Button>
        <span className="text-xs text-muted-foreground">
          Simulation only · holdings unchanged
        </span>
      </div>

      {rows.length > 0 && (
        <div className="space-y-2">
          {rows.map((r, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <input
                aria-label="Ticker"
                value={r.ticker}
                onChange={(e) => updateRow(i, { ticker: e.target.value })}
                className="w-24 rounded border border-border bg-background px-2 py-1 text-sm uppercase"
                placeholder="TICKER"
              />
              <input
                aria-label="Market value"
                value={r.market_value}
                onChange={(e) => updateRow(i, { market_value: e.target.value })}
                inputMode="decimal"
                className="w-32 rounded border border-border bg-background px-2 py-1 text-right text-sm tabular-nums"
                placeholder="$ value"
              />
              <Button type="button" variant="ghost" size="sm" onClick={() => nudge(i, 0.9)}>
                −10%
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => nudge(i, 1.1)}>
                +10%
              </Button>
              <button
                type="button"
                onClick={() => removeRow(i)}
                aria-label="Remove row"
                className="text-muted-foreground hover:text-destructive"
              >
                ✕
              </button>
            </div>
          ))}
          <Button type="button" size="sm" disabled={loading} onClick={run}>
            {loading ? "Scoring…" : "Run what-if"}
          </Button>
        </div>
      )}

      {error && (
        <p className="text-sm text-destructive">Could not score the sandbox. {error.message}</p>
      )}

      {sandbox && baseline && (
        <div className="space-y-3 rounded-lg border border-border bg-muted/20 p-3">
          <WhatIfCompare
            baseline={baseline}
            sandbox={sandbox}
            onReset={() => {
              setSandbox(null);
              setShowSave(false);
            }}
          />
          {saveContext && !showSave && (
            <Button type="button" size="sm" onClick={() => setShowSave(true)}>
              Save as risk plan
            </Button>
          )}
          {saveContext && showSave && (
            <SaveAsPlan
              portfolioId={saveContext.portfolioId}
              source={saveContext.source}
              baseline={baseline}
              sandbox={sandbox}
              proposedChanges={{ rows }}
              onSaved={() => setShowSave(false)}
              onCancel={() => setShowSave(false)}
            />
          )}
        </div>
      )}
      {sandbox && !baseline && (
        <p className="text-xs text-muted-foreground">
          Score your active portfolio first to compare a what-if against it.
        </p>
      )}
    </div>
  );
}
