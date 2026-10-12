"use client";

/** Cross-device saved-plan history inside the single Copilot window. Read-only. */
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";
import {
  formatMetric, metricReviewSchema, reviewFingerprint, savedPlanDetailSchema, savedPlanPageSchema,
  type MetricReview, type SavedPlanDetail, type SavedPlanItem,
} from "@/lib/plan-history";
import { Button } from "./ui/button";

const KIND = { comparison: "Reduction comparison", cash_secured_put: "Cash-secured Put", funding_scenarios: "Funding scenarios" } as const;
const BASE = "/api/v1/copilot/saved-plans";
export const PERIODIC_MAX_PLANS = 5;
export const PERIODIC_INTERVAL_MS = 15 * 60_000;

export function CopilotPlanHistory({ token, portfolioId }: { token: string | null; portfolioId: string }) {
  const [plans, setPlans] = useState<SavedPlanItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [details, setDetails] = useState<Record<string, SavedPlanDetail>>({});
  const [reviews, setReviews] = useState<Record<string, MetricReview>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [periodic, setPeriodic] = useState<{ token: string; portfolioId: string } | null>(null);
  const controller = useRef<AbortController | null>(null);
  const fingerprints = useRef<Record<string, string>>({});

  useEffect(() => {
    controller.current?.abort();
    setPlans([]); setCursor(null); setLoaded(false); setDetails({}); setReviews({});
    setNotice(""); setPeriodic(null); fingerprints.current = {};
  }, [token, portfolioId]);
  useEffect(() => () => controller.current?.abort(), []);

  async function call<T>(fn: (signal: AbortSignal) => Promise<T>): Promise<T | null> {
    const abort = new AbortController();
    controller.current?.abort(); controller.current = abort;
    setBusy(true); setNotice("");
    try { const value = await fn(abort.signal); return abort.signal.aborted ? null : value; }
    catch (error) {
      if (!abort.signal.aborted) setNotice(error instanceof Error ? error.message : "The request did not complete. Nothing was changed.");
      return null;
    } finally { if (controller.current === abort) setBusy(false); }
  }

  async function load(more: boolean) {
    if (!token) return;
    const suffix = more && cursor ? `&cursor=${encodeURIComponent(cursor)}` : "";
    const page = await call(signal => apiFetch(`${BASE}?expected_portfolio_id=${portfolioId}${suffix}`, {
      method: "GET", authToken: token, signal, schema: savedPlanPageSchema,
    }));
    if (!page) return;
    if (page.plans.some(plan => plan.portfolio_id !== portfolioId)) { setNotice("Saved portfolio mismatch. Nothing was shown."); return; }
    setPlans(previous => more ? [...previous, ...page.plans.filter(p => !previous.some(o => o.plan_id === p.plan_id))] : page.plans);
    setCursor(page.next_cursor); setLoaded(true);
    setNotice(`Verified plans in stable order (not by date).${page.unverified_records ? ` ${page.unverified_records} record(s) could not be verified and are not shown.` : ""}`);
  }

  async function open(planId: string) {
    if (!token || details[planId]) return;
    const value = await call(signal => apiFetch(`${BASE}/${planId}?expected_portfolio_id=${portfolioId}`, {
      method: "GET", authToken: token, signal, schema: savedPlanDetailSchema,
    }));
    if (value && value.item.plan_id === planId && value.item.portfolio_id === portfolioId) setDetails(d => ({ ...d, [planId]: value }));
  }

  async function review(planId: string, signal?: AbortSignal) {
    const value = await apiFetch(`${BASE}/${planId}/metric-review`, {
      method: "POST", authToken: token ?? undefined, signal, schema: metricReviewSchema, body: { expected_portfolio_id: portfolioId },
    });
    if (value.plan_id !== planId || value.portfolio_id !== portfolioId) throw new Error("Review scope mismatch.");
    return value;
  }

  // In-session periodic review: opt-in, visible window only, bounded, in-memory consent.
  const periodicOn = !!token && periodic?.token === token && periodic.portfolioId === portfolioId;
  const ids = JSON.stringify(plans.slice(0, PERIODIC_MAX_PLANS).map(p => p.plan_id));
  useEffect(() => {
    if (!periodicOn) return;
    const abort = new AbortController();
    let running = false;
    const tick = async () => {
      if (running || document.visibilityState !== "visible") return;
      running = true;
      try {
        for (const id of JSON.parse(ids) as string[]) {
          if (abort.signal.aborted || document.visibilityState !== "visible") break;
          const value = await review(id, abort.signal);
          if (abort.signal.aborted) break;
          const print = reviewFingerprint(value);
          const previous = fingerprints.current[id];
          fingerprints.current[id] = print;
          setReviews(r => ({ ...r, [id]: value }));
          if (previous !== undefined && previous !== print) setNotice("A saved plan's review changed. Open it to see what moved.");
        }
      } catch (error) {
        if (!abort.signal.aborted) {
          setPeriodic(null);
          setNotice(`Periodic review stopped: ${error instanceof Error ? error.message : "request failed"}. Re-enable to resume.`);
        }
      } finally { running = false; }
    };
    const timer = window.setInterval(() => void tick(), PERIODIC_INTERVAL_MS);
    void tick();
    return () => { abort.abort(); window.clearInterval(timer); };
    // review() closes over token/portfolioId, both covered by periodicOn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [periodicOn, ids]);

  return <details className="rounded-xl border border-border p-3 text-sm" aria-label="Saved plans">
    <summary className="cursor-pointer font-medium">Saved plans</summary>
    <div className="mt-3 min-w-0 space-y-3">
      <p className="text-xs text-muted-foreground">Read from your account on any device. Original figures are verified on every read; editing a plan&apos;s title or notes never changes them. No trades were executed and no returns are attributed.</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" disabled={busy || !token} onClick={() => void load(false)}>{loaded ? "Reload saved plans" : "Load saved plans"}</Button>
        {cursor && <Button type="button" size="sm" variant="outline" disabled={busy || !token} onClick={() => void load(true)}>Load more</Button>}
      </div>
      {loaded && plans.length > 0 && <label className="flex gap-2 text-xs">
        <input type="checkbox" checked={periodicOn} disabled={!token}
          onChange={e => { fingerprints.current = {}; setPeriodic(e.target.checked && token ? { token, portfolioId } : null); }} />
        Re-run the review for the first {PERIODIC_MAX_PLANS} plans every 15 minutes while this window is open and visible. This session only; nothing is scheduled on the server.
      </label>}
      {notice && <p role="status">{notice}</p>}
      {loaded && plans.length === 0 && <p>No verified saved plans for this portfolio.</p>}
      <ul className="space-y-2">{plans.map(plan => <li key={plan.plan_id} className="min-w-0 rounded border border-border p-3">
        <p className="break-words font-medium">{KIND[plan.kind]}: {plan.summary}</p>
        <p className="text-xs text-muted-foreground">Saved {plan.confirmed_at} · captured {plan.captured_at} · {plan.methodology_version}</p>
        <p className="break-all text-xs text-muted-foreground">Evidence fingerprint {plan.evidence_sha256.slice(0, 16)}… · signature verified</p>
        <div className="mt-2 flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void open(plan.plan_id)}>Open original evidence</Button>
          <Button type="button" size="sm" variant="outline" disabled={busy}
            onClick={async () => { const value = await call(signal => review(plan.plan_id, signal)); if (value) { fingerprints.current[plan.plan_id] = reviewFingerprint(value); setReviews(r => ({ ...r, [plan.plan_id]: value })); } }}>Run review</Button>
        </div>
        {details[plan.plan_id] && <Evidence detail={details[plan.plan_id]} />}
        {reviews[plan.plan_id] && <Review review={reviews[plan.plan_id]} />}
      </li>)}</ul>
    </div>
  </details>;
}

function Evidence({ detail }: { detail: SavedPlanDetail }) {
  const c = detail.comparison?.result;
  return <div className="mt-2 space-y-1 text-xs" aria-label="Original evidence">
    <p>Original calculation, as saved. Not current data.</p>
    {c && <div className="overflow-x-auto"><table className="min-w-[22rem] text-left">
      <thead><tr><th>Metric</th><th>Keep as is</th><th>Hypothetical change</th></tr></thead>
      <tbody>{([["Net equity", "net_equity", "usd"], ["Leverage", "leverage", "ratio"], ["Largest position", "largest_position_weight", "fraction"],
        ["Annualised volatility", "annual_volatility", "fraction_per_year"], ["1-day 95% VaR", "var_1d_95_usd", "usd"]] as const).map(([label, key, unit]) =>
        <tr key={key}><td>{label}</td><td>{formatMetric(c.baseline[key], unit)}</td><td>{formatMetric(c.candidate[key], unit)}</td></tr>)}</tbody>
    </table><p>Prices as of {c.price_as_of} · {c.observations} daily returns from {c.history_start}</p></div>}
    {detail.put && <p>Put {detail.put.result.assumptions.underlying} {detail.put.result.assumptions.expiry} · strike ${detail.put.result.assumptions.strike} · original maximum loss ${detail.put.result.maximum_loss.toFixed(2)} · captured {detail.put.result.computed_at}</p>}
    {detail.funding && <p>Funding scenarios for {detail.funding.result.sale_ticker} · {detail.funding.result.alternatives.length} alternatives · captured {detail.funding.result.captured_at}</p>}
    <p className="break-all">Full evidence fingerprint {detail.item.evidence_sha256}</p>
  </div>;
}

function Review({ review }: { review: MetricReview }) {
  const status = { comparable: "Same method: changes since saving", method_changed: "Calculation method changed — not comparable as a total",
    not_computable: "Review not computable" }[review.status];
  return <div role="status" aria-label="Plan review" className="mt-2 space-y-2 text-xs">
    <p className="font-medium">{status}{review.status_reason ? ` (${review.status_reason.replaceAll("_", " ")})` : ""}</p>
    <p>Reviewed {review.reviewed_at}. Account changes: {review.account_changes.join(", ").replaceAll("_", " ") || "none recorded"}.</p>
    {review.metrics.length > 0 && <div className="overflow-x-auto"><table className="min-w-[36rem] text-left">
      <thead><tr><th>Metric</th><th>Saved</th><th>Market change</th><th>Account change</th>{review.status === "method_changed" && <th>Method change (not your account)</th>}<th>Total</th><th>Now</th></tr></thead>
      <tbody>{review.metrics.map(m => <tr key={m.metric_id}>
        <td>{m.label}<span className="block text-muted-foreground">{m.horizon}</span></td>
        <td>{formatMetric(m.original, m.unit)}</td>
        <td>{formatMetric(m.market_change, m.unit, true)}</td>
        <td>{formatMetric(m.account_change, m.unit, true)}</td>
        {review.status === "method_changed" && <td>{formatMetric(m.method_change, m.unit, true)}</td>}
        <td>{review.status === "method_changed" ? "Not reported" : formatMetric(m.total_change, m.unit, true)}</td>
        <td>{formatMetric(m.current, m.unit)}{m.not_computable_reason && <span className="block text-muted-foreground">{m.not_computable_reason.replaceAll("_", " ")}</span>}</td>
      </tr>)}</tbody>
    </table></div>}
    {review.market_window && <p>Current prices as of {review.market_window.price_as_of} ({review.market_window.observations} daily returns).</p>}
    <ul className="list-disc pl-4">{review.notes.map(note => <li key={note}>{note}</li>)}</ul>
  </div>;
}
