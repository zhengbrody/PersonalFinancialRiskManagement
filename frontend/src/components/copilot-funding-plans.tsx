"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { apiFetch } from "@/lib/api";
import { fundingResultSchema, type FundingResult } from "@/lib/copilot-funding";
import { planReviewSchema, usePlanSessionReview } from "@/lib/use-plan-session-review";
import { classifySaveFailure, FUNDING_PLAN_MISSING_CODE, FUNDING_PLAN_SETTLED_CODES } from "@/lib/copilot-save-outcome";
import { FundingAccountRisk } from "./funding-account-risk";
import { Button } from "./ui/button";

const savedSchema = z.object({ plan_id: z.string().uuid(), portfolio_id: z.string().uuid(), confirmed_at: z.string(), result: fundingResultSchema }).superRefine((saved, ctx) => {
  if (saved.plan_id !== saved.result.result_id || saved.portfolio_id !== saved.result.portfolio_id || saved.result.receipt) ctx.addIssue({ code: "custom", message: "Saved funding evidence mismatch" });
});
const reviewSchema = planReviewSchema;
const usd = (value: number) => value.toLocaleString("en-US", { style: "currency", currency: "USD" });
export function CopilotFundingPlans({ result = null, planId, portfolioId, token }: {
  result?: FundingResult | null; planId?: string; portfolioId: string; token: string | null;
}) {
  const id = result?.result_id ?? planId;
  const [confirmed, setConfirmed] = useState(false);
  const [saved, setSaved] = useState<z.infer<typeof savedSchema> | null>(null);
  const [review, setReview] = useState<z.infer<typeof reviewSchema> | null>(null);
  const [notice, setNotice] = useState("");
  const monitor = usePlanSessionReview({ token, portfolioId, scopeKey: id ?? "", planIds: saved ? [saved.plan_id] : [], kind: "funding-plans", onChanged: setReview });
  const [busy, setBusy] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    setSaved(null); setReview(null); setConfirmed(false); setNotice(""); setBusy(false);
    return () => active.current?.abort();
  }, [id, token, portfolioId]);
  async function run(action: "save" | "read" | "review") {
    if (!id || !token || busy || (action === "save" && (!confirmed || !result?.receipt?.save_available))) return;
    const abort = new AbortController(); active.current?.abort(); active.current = abort;
    setBusy(true); setNotice("");
    const base = `/api/v1/copilot/funding-plans/${id}`;
    try {
      if (action === "review") {
        const value = await apiFetch(`${base}/review`, { method: "POST", authToken: token, signal: abort.signal, schema: reviewSchema, body: { expected_portfolio_id: portfolioId } });
        if (value.plan_id !== id || value.portfolio_id !== portfolioId) throw new Error("Review scope mismatch.");
        if (!abort.signal.aborted) setReview(value);
      } else {
        const value = await apiFetch(action === "save" ? `${base}/confirm` : `${base}?expected_portfolio_id=${portfolioId}`, {
          method: action === "save" ? "POST" : "GET", authToken: token, signal: abort.signal, schema: savedSchema,
          ...(action === "save" ? { body: { expected_portfolio_id: portfolioId, receipt: result!.receipt, confirmed: true } } : {}),
        });
        if (value.plan_id !== id || value.portfolio_id !== portfolioId ||
          (result && JSON.stringify(value.result) !== JSON.stringify({ ...result, receipt: null }))) throw new Error("Saved result does not match the original calculation.");
        if (!abort.signal.aborted) { setSaved(value); setNotice("Verified original funding plan. No holdings or orders changed."); }
      }
    } catch (e) {
      if (abort.signal.aborted) return;
      if (action === "review") { setNotice(e instanceof Error ? e.message : "Could not review the plan."); return; }
      const failure = classifySaveFailure(e, {
        settled: FUNDING_PLAN_SETTLED_CODES, missing: FUNDING_PLAN_MISSING_CODE, retrieve: action === "read",
        uncertainSave: "Save status is unconfirmed. Retrieve the original or retry the same result; a draft may already exist.",
        uncertainRead: "The saved funding plan could not be read. Check again; this did not change anything.",
        vanished: "No saved funding plan exists for this calculation. It may have been deleted with its plan.",
      });
      // A definite 404 on the read path means the plan is gone: stop showing a
      // remembered record as if it still existed.
      if (failure.vanished) { setSaved(null); setReview(null); }
      setNotice(failure.message);
    }
    finally { if (active.current === abort) setBusy(false); }
  }
  return <section aria-label="Saved funding plan" className="mt-3 space-y-3 rounded-lg border border-border p-3 text-sm">
    {result?.receipt?.save_available && <><label className="flex gap-2"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Save these original funding assumptions as a draft RiskPlan. This does not execute a trade.</label>
      <Button size="sm" disabled={busy || !confirmed || !token} onClick={() => void run("save")}>Confirm save funding plan</Button></>}
    <Button size="sm" variant="outline" disabled={busy || !token || !id} onClick={() => void run("read")}>Retrieve saved funding plan</Button>
    {notice && <p role="status">{notice}</p>}
    {saved && <><p>Saved {saved.confirmed_at}. Original account capture {saved.result.captured_at}.</p>
      <details><summary>Original funding inputs and results</summary><p>Reduce {saved.result.sale_ticker} · fees {usd(saved.result.assumptions.sale_fees)} · Put {saved.result.assumptions.put.underlying} {saved.result.assumptions.put.expiry} · strike {usd(saved.result.assumptions.put.strike)} · {saved.result.assumptions.put.contracts} contract(s).</p>
        <ul className="space-y-2">{saved.result.alternatives.map(row => <li key={row.kind}>{row.kind.replace(/_/g, " ")}: cash {usd(row.cash_before_put)}, debt {usd(row.margin_remaining)}, assignment reserve shortfall {usd(row.assignment_cash_shortfall)}. {row.status.replace(/_/g, " ")}.</li>)}</ul>
        {saved.result.account_risk && <FundingAccountRisk risk={saved.result.account_risk} />}
        <ul className="list-disc pl-4">{saved.result.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("review")}>Review funding assumptions</Button></>}
    {saved && <label className="flex gap-2 text-xs"><input type="checkbox" checked={monitor.enabled} disabled={!token} onChange={e => monitor.setEnabled(e.target.checked)} />Review this funding plan every minute while signed in and this window is visible. This session only; no quotes, trades or return attribution.</label>}
    {monitor.notice && <p role="status">{monitor.notice}</p>}
    {review && <div role="status"><p>{review.verdict === "requires_recalculation" ? "Recalculate funding scenario" : "Funding assumptions need confirmation"}</p><p>Reviewed {review.reviewed_at}. Changed: {review.changed_fields.join(", ") || "No recorded account change"}.</p>{review.reasons.map(reason => <p key={reason}>{reason}</p>)}</div>}
  </section>;
}
