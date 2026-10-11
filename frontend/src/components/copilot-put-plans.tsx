"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { apiFetch } from "@/lib/api";
import { putResultSchema, type PutResult } from "@/lib/copilot-put";
import { planReviewSchema, usePlanSessionReview } from "@/lib/use-plan-session-review";
import { classifySaveFailure, PUT_PLAN_SETTLED_CODES } from "@/lib/copilot-save-outcome";
import { Button } from "./ui/button";

const savedSchema = z.object({
  plan_id: z.string().uuid(), portfolio_id: z.string().uuid(), confirmed_at: z.string(), result: putResultSchema,
}).superRefine((plan, ctx) => {
  if (plan.plan_id !== plan.result.result_id || plan.portfolio_id !== plan.result.portfolio_id || plan.result.receipt) {
    ctx.addIssue({ code: "custom", message: "Saved put scope mismatch" });
  }
});
const reviewSchema = planReviewSchema;
type Saved = z.infer<typeof savedSchema>;
type Review = z.infer<typeof reviewSchema>;

export function CopilotPutPlans({ token, portfolioId, result }: {
  token: string | null; portfolioId: string; result: PutResult | null;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [plans, setPlans] = useState<Saved[]>([]);
  const [reviews, setReviews] = useState<Record<string, Review>>({});
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const monitor = usePlanSessionReview({ token, portfolioId, planIds: plans.map(plan => plan.plan_id), kind: "put-plans",
    onChanged: value => setReviews(previous => ({ ...previous, [value.plan_id]: value })) });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    controller.current?.abort();
    setPlans([]); setReviews({}); setNextCursor(null);
    setConfirmed(false); setNotice("");
  }, [token, portfolioId]);
  useEffect(() => { setConfirmed(false); }, [result]);

  async function run(action: "save" | "list" | "more" | "review", planId?: string) {
    if (action === "save" && (!confirmed || !result?.receipt?.save_available)) return;
    const abort = new AbortController();
    controller.current?.abort(); controller.current = abort;
    setBusy(true); setNotice("");
    const base = "/api/v1/copilot/put-plans";
    try {
      if (action === "save" && result?.receipt) {
        const saved = savedSchema.parse(await apiFetch(`${base}/${result.result_id}/confirm`, {
          method: "POST", authToken: token ?? undefined, signal: abort.signal, schema: savedSchema,
          body: { expected_portfolio_id: portfolioId, confirmed: true, receipt: result.receipt },
        }));
        if (saved.portfolio_id !== portfolioId || saved.plan_id !== result.result_id ||
            Object.entries(result.assumptions).some(([key, value]) => saved.result.assumptions[key as keyof typeof result.assumptions] !== value)) {
          throw new Error("Saved result does not match this calculation.");
        }
        if (!abort.signal.aborted) {
          setPlans(previous => [saved, ...previous.filter(plan => plan.plan_id !== saved.plan_id)]);
          setNotice("Original calculation saved. No holdings were changed.");
        }
      } else if (action === "list" || action === "more") {
        const schema = z.object({ plans: z.array(savedSchema).max(20), next_cursor: z.string().nullable(), skipped_records: z.number().int().nonnegative() });
        const cursor = action === "more" && nextCursor ? `&cursor=${encodeURIComponent(nextCursor)}` : "";
        const page = schema.parse(await apiFetch(`${base}/history?expected_portfolio_id=${portfolioId}${cursor}`, {
          method: "GET", authToken: token ?? undefined, signal: abort.signal, schema,
        }));
        if (page.plans.some(plan => plan.portfolio_id !== portfolioId)) throw new Error("Saved portfolio mismatch.");
        if (!abort.signal.aborted) {
          setPlans(previous => action === "list" ? page.plans : [...previous, ...page.plans.filter(plan => !previous.some(old => old.plan_id === plan.plan_id))]);
          setNextCursor(page.next_cursor);
          setNotice(`Verified history in stable plan order. ${page.skipped_records} unrelated or unverifiable records skipped. ${page.next_cursor ? "More records available." : "End of history; reload for newly saved plans."}`);
        }
      } else if (planId) {
        const review = reviewSchema.parse(await apiFetch(`${base}/${planId}/review`, {
          method: "POST", authToken: token ?? undefined, signal: abort.signal, schema: reviewSchema,
          body: { expected_portfolio_id: portfolioId },
        }));
        if (review.portfolio_id !== portfolioId || review.plan_id !== planId) throw new Error("Review scope mismatch.");
        if (!abort.signal.aborted) setReviews(previous => ({ ...previous, [planId]: review }));
      }
    } catch (error) {
      if (abort.signal.aborted) return;
      if (action !== "save") { setNotice(error instanceof Error ? error.message : "The request did not complete. Nothing was changed."); return; }
      // Deny-list: only a provably pre-commit rejection is reported as definite;
      // anything else (network, timeout, unknown code, post-commit check) may
      // have left a saved draft behind and must stay retryable with the SAME result.
      setNotice(classifySaveFailure(error, {
        settled: PUT_PLAN_SETTLED_CODES, retrieve: false,
        uncertainSave: "Saving was not confirmed. Load saved Put plans to check, or retry this same result; a draft may already exist.",
        uncertainRead: "", vanished: "",
      }).message);
    } finally { if (controller.current === abort) setBusy(false); }
  }

  return <section aria-label="Saved put plans" className="mt-4 space-y-3 border-t border-border pt-3 text-sm">
    {result?.receipt?.save_available && <>
      <label className="flex gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} />
        Save this original hypothetical Put calculation as a draft RiskPlan. This does not place a trade.</label>
      <Button type="button" size="sm" disabled={busy || !confirmed || !token} onClick={() => void run("save")}>Confirm save Put plan</Button>
    </>}
    <Button type="button" variant="outline" size="sm" disabled={busy || !token} onClick={() => void run("list")}>Load saved Put plans</Button>
    {nextCursor && <Button type="button" variant="outline" size="sm" disabled={busy || !token} onClick={() => void run("more")}>Load more Put plans</Button>}
    <label className="flex gap-2 text-xs"><input type="checkbox" checked={monitor.enabled} disabled={!token || plans.length === 0} onChange={e => monitor.setEnabled(e.target.checked)} />
      Review loaded plans (first 20) every minute while signed in and this window is visible. This session only; no quotes, trades or return attribution.</label>
    {monitor.notice && <p role="status">{monitor.notice}</p>}
    {notice && <p role="status">{notice}</p>}
    {plans.map(plan => <details key={plan.plan_id} className="rounded border border-border p-3">
      <summary className="cursor-pointer">{plan.result.assumptions.underlying} Put · saved {plan.confirmed_at}</summary>
      <div className="mt-2 space-y-2 text-xs">
        <p>Original expiry {plan.result.assumptions.expiry} · strike ${plan.result.assumptions.strike} · {plan.result.assumptions.contracts} contract(s)</p>
        <p>Original cash gap ${plan.result.pre_trade_funding_gap.toFixed(2)} · maximum loss ${plan.result.maximum_loss.toFixed(2)} · {plan.result.funding_status.replaceAll("_", " ")}</p>
        <p>These are the authenticated original figures, not current quotes or a claim that the trade happened.</p>
        <details><summary className="cursor-pointer">Original inputs & funding</summary>
          <dl className="mt-2 grid gap-2 sm:grid-cols-2">
            {[["Assumed spot", plan.result.assumptions.assumed_spot], ["Premium per share", plan.result.assumptions.premium_per_share],
              ["Total fees", plan.result.assumptions.fees_total], ["Other cash holds", plan.result.assumptions.other_reserved_cash],
              ["Cash buffer", plan.result.assumptions.cash_buffer], ["Recorded cash", plan.result.recorded_cash],
              ["Existing put reserve", plan.result.existing_put_reserve], ["Assignment payment", plan.result.assignment_notional],
              ["Net premium", plan.result.net_premium], ["Break-even per share", plan.result.breakeven]
            ].map(([label, value]) => <div key={String(label)}><dt>{label}</dt><dd>${Number(value).toLocaleString("en-US", { maximumFractionDigits: 6 })}</dd></div>)}
          </dl>
          <p className="mt-2">Captured {plan.result.computed_at} · {plan.result.methodology_version}</p>
          <ul className="mt-2 list-disc pl-4">{plan.result.limitations.map(text => <li key={text}>{text}</li>)}</ul>
        </details>
        <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void run("review", plan.plan_id)}>Review current assumptions</Button>
        {reviews[plan.plan_id] && <div role="status" className="space-y-1">
          <p className="font-medium">{reviews[plan.plan_id].verdict === "requires_recalculation" ? "Recalculation required" : "Assumptions need confirmation"}</p>
          <p>Reviewed {reviews[plan.plan_id].reviewed_at}</p>
          <p>Changed: {reviews[plan.plan_id].changed_fields.join(", ") || "No account change detected"}</p>
          {reviews[plan.plan_id].reasons.map(reason => <p key={reason}>{reason}</p>)}
        </div>}
      </div>
    </details>)}
  </section>;
}
