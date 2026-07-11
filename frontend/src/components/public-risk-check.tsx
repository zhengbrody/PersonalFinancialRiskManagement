"use client";

/**
 * Anonymous, no-signup portfolio risk check (feature-flagged — see
 * lib/public-risk.ts). Mobile-first: stacked rows, full-width controls.
 *
 * Scope by design: ticker + shares only (no cost basis, margin, options, or
 * contact info), at most 10 public-security holdings, limited result set
 * (concentration · volatility · 1-day historical VaR/CVaR · simple stress ·
 * provenance). No AI, no recommendations. "Import a broker CSV" reads a FILE
 * the user exported — nothing connects to a brokerage.
 *
 * Analytics: step events with a coarse holdings_band only — never tickers/shares/exact counts.
 */

import { useRef, useState } from "react";
import Link from "next/link";

import { track } from "@/lib/analytics";
import { holdingsBand } from "@/lib/analytics-events";
import { parseHoldingsCsv } from "@/lib/parse-holdings-csv";
import {
  MAX_PUBLIC_HOLDINGS,
  runPublicRiskCheck,
  saveAnonHoldings,
  type AnonHolding,
  type PublicRiskCheckResult,
} from "@/lib/public-risk";

const pct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
const usd = (v: number | null | undefined) =>
  v === null || v === undefined
    ? "—"
    : `${v < 0 ? "−" : ""}$${Math.abs(Math.round(v)).toLocaleString("en-US")}`;

const BLANK_ROWS: AnonHolding[] = [
  { ticker: "", shares: "" },
  { ticker: "", shares: "" },
  { ticker: "", shares: "" },
];

export function PublicRiskCheck() {
  const [rows, setRows] = useState<AnonHolding[]>(BLANK_ROWS);
  const [result, setResult] = useState<PublicRiskCheckResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [csvNote, setCsvNote] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const startedRef = useRef(false);

  const filled = rows.filter((r) => r.ticker.trim() && r.shares.trim());

  function markStarted() {
    if (!startedRef.current) {
      startedRef.current = true;
      track("public_check_started");
    }
  }

  function setRow(i: number, patch: Partial<AnonHolding>) {
    markStarted();
    setRows((prev) => prev.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  async function onCsvFile(file: File) {
    markStarted();
    const text = await file.text();
    const { rows: parsed, warning } = parseHoldingsCsv(text);
    // Deliberately keep ONLY ticker + shares — the public check never
    // collects cost basis.
    const mapped = parsed
      .filter((r) => r.ticker && r.shares)
      .slice(0, MAX_PUBLIC_HOLDINGS)
      .map((r) => ({ ticker: r.ticker, shares: r.shares }));
    if (mapped.length === 0) {
      setCsvNote(warning ?? "No usable ticker + shares rows found in that file.");
      return;
    }
    setRows(mapped);
    setCsvNote(
      parsed.length > MAX_PUBLIC_HOLDINGS
        ? `Imported the first ${MAX_PUBLIC_HOLDINGS} holdings (public check limit).`
        : `Imported ${mapped.length} holding(s).`,
    );
    track("public_check_csv_imported", { holdings_band: holdingsBand(mapped.length) });
  }

  async function run() {
    setError(null);
    const holdings = filled.map((r) => ({
      ticker: r.ticker.trim().toUpperCase(),
      shares: Number(r.shares),
    }));
    if (holdings.length === 0) {
      setError("Add at least one ticker with a share count.");
      return;
    }
    if (holdings.some((h) => !Number.isFinite(h.shares) || h.shares <= 0)) {
      setError("Share counts must be positive numbers.");
      return;
    }
    setPending(true);
    try {
      const res = await runPublicRiskCheck(holdings);
      setResult(res);
      // The signup handoff: browser-only storage, confirmed by the user on
      // /portfolios/new before anything is written to the database.
      saveAnonHoldings(filled);
      track("public_check_completed", { holdings_band: holdingsBand(holdings.length) });
    } catch (e) {
      setError((e as Error)?.message ?? "Risk check failed — try again shortly.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-label="Check your own portfolio" className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Check your own portfolio — no signup</h2>
        <p className="text-sm text-muted-foreground">
          Up to {MAX_PUBLIC_HOLDINGS} stock or ETF holdings: ticker + share count. Nothing is
          stored, nothing connects to your brokerage, and no email is asked for.
        </p>
      </div>

      <div className="space-y-2">
        {rows.map((row, i) => (
          <div key={i} className="flex gap-2">
            <input
              className="w-28 rounded-md border border-border bg-background px-3 py-2 font-mono text-sm uppercase"
              placeholder="AAPL"
              aria-label={`Ticker ${i + 1}`}
              value={row.ticker}
              onChange={(e) => setRow(i, { ticker: e.target.value })}
              maxLength={10}
            />
            <input
              className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
              placeholder="Shares"
              aria-label={`Shares ${i + 1}`}
              inputMode="decimal"
              value={row.shares}
              onChange={(e) => setRow(i, { shares: e.target.value })}
            />
            {rows.length > 1 && (
              <button
                type="button"
                className="rounded-md border border-border px-3 text-sm text-muted-foreground"
                aria-label={`Remove row ${i + 1}`}
                onClick={() => setRows((prev) => prev.filter((_, j) => j !== i))}
              >
                ×
              </button>
            )}
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        {rows.length < MAX_PUBLIC_HOLDINGS && (
          <button
            type="button"
            className="rounded-md border border-border px-3 py-2 text-sm"
            onClick={() => setRows((prev) => [...prev, { ticker: "", shares: "" }])}
          >
            + Add holding
          </button>
        )}
        <button
          type="button"
          className="rounded-md border border-border px-3 py-2 text-sm"
          onClick={() => fileRef.current?.click()}
        >
          Import a broker CSV
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          aria-label="Broker CSV file"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void onCsvFile(f);
            e.target.value = "";
          }}
        />
        <button
          type="button"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          disabled={pending || filled.length === 0}
          onClick={() => void run()}
        >
          {pending ? "Checking…" : "Run risk check"}
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        A CSV you exported from your broker — we read the file locally; nothing connects to a
        brokerage account.
      </p>
      {csvNote && <p className="text-xs text-muted-foreground">{csvNote}</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {result && <ResultPanel result={result} holdingsCount={filled.length} />}
    </section>
  );
}

function ResultPanel({
  result,
  holdingsCount,
}: {
  result: PublicRiskCheckResult;
  holdingsCount: number;
}) {
  const c = result.concentration;
  const m = result.metrics;
  const p = result.provenance;
  return (
    <div className="space-y-4 rounded-lg border border-border p-4" data-testid="public-risk-result">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Portfolio value" value={usd(m.total_value)} />
        <Stat label="Annual volatility" value={pct(m.annual_volatility)} />
        <Stat label="1-day VaR (95%)" value={pct(m.var_95_1d)} />
        <Stat label="1-day CVaR (95%)" value={pct(m.cvar_95_1d)} />
      </div>

      <div>
        <h3 className="text-sm font-medium">Concentration</h3>
        <p className="text-sm text-muted-foreground">
          Largest holding {c.top_ticker ?? "—"} is {pct(c.top_weight)} of the book · effective
          holdings {c.effective_holdings ?? "—"}
        </p>
      </div>

      <div>
        <h3 className="text-sm font-medium">If the market drops…</h3>
        <table className="mt-1 w-full text-sm">
          <tbody>
            {result.stress.map((s) => (
              <tr key={s.market_shock_pct} className="border-t border-border/60">
                <td className="py-1.5 text-muted-foreground">
                  Market {pct(s.market_shock_pct, 0)}
                </td>
                <td className="py-1.5 text-right font-mono">
                  {pct(s.est_portfolio_impact_pct)}
                </td>
                <td className="py-1.5 text-right font-mono">{usd(s.est_portfolio_impact_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-muted-foreground">
          First-order estimate from your portfolio&apos;s market beta
          {m.beta_to_market != null ? ` (${m.beta_to_market.toFixed(2)})` : ""}.
        </p>
      </div>

      <p className="text-xs text-muted-foreground">
        Data: {p.priced.length} of {p.priced.length + p.missing.length} holdings priced ·{" "}
        {p.observations} trading days · as of {p.as_of ?? "—"}
        {p.missing.length > 0 && ` · unpriced: ${p.missing.join(", ")}`}
      </p>
      {p.window_limited_by && (
        <p className="text-xs text-muted-foreground">
          Volatility and VaR need a longer shared history —{" "}
          <span className="font-mono">{p.window_limited_by}</span> has too little price
          history to span the window.
        </p>
      )}
      <p className="text-xs text-muted-foreground">{result.disclaimer}</p>

      <div className="rounded-md border border-primary/30 bg-primary/5 p-3">
        <p className="text-sm font-medium">Save this portfolio and unlock the full risk desk</p>
        <p className="mt-1 text-xs text-muted-foreground">
          Health Score, full VaR/stress report, factor exposure, and what-if analysis — your
          holdings carry over automatically after signup, and are saved only when you confirm.
        </p>
        <Link
          href="/signup"
          className="mt-2 inline-block rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          onClick={() => track("public_check_signup_cta", { holdings_band: holdingsBand(holdingsCount) })}
        >
          Create a free account
        </Link>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-lg tabular-nums">{value}</p>
    </div>
  );
}
