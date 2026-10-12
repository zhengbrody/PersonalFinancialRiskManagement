"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { apiFetch } from "./api";

export const planReviewSchema = z.object({
  plan_id: z.string().uuid(), portfolio_id: z.string().uuid(), reviewed_at: z.string(),
  verdict: z.enum(["requires_recalculation", "assumptions_need_confirmation"]),
  changed_fields: z.array(z.string()), reasons: z.array(z.string()),
  live_quote_checked: z.literal(false), holdings_changed_by_review: z.literal(false),
});
export type PlanReview = z.infer<typeof planReviewSchema>;

/** In-memory consent only; no JWT storage, service worker or hidden-window polling. */
export function usePlanSessionReview({ token, portfolioId, scopeKey = "", planIds, kind, onChanged }: {
  token: string | null; portfolioId: string; scopeKey?: string; planIds: string[];
  kind: "put-plans" | "funding-plans"; onChanged: (review: PlanReview) => void;
}) {
  const [consent, setConsent] = useState<{ token: string; portfolioId: string; scopeKey: string } | null>(null);
  const [notice, setNotice] = useState("");
  const fingerprints = useRef<Record<string, string>>({});
  const callback = useRef(onChanged);
  callback.current = onChanged;
  const enabled = !!token && consent?.token === token && consent.portfolioId === portfolioId && consent.scopeKey === scopeKey;
  const ids = JSON.stringify(planIds.slice(0, 20));
  useEffect(() => {
    setConsent(null); setNotice(""); fingerprints.current = {};
  }, [token, portfolioId, scopeKey]);

  useEffect(() => {
    if (!enabled || !token) return;
    const abort = new AbortController();
    let running = false;
    const tick = async () => {
      if (running || document.visibilityState !== "visible") return;
      running = true;
      try {
        for (const id of JSON.parse(ids) as string[]) {
          if (abort.signal.aborted || document.visibilityState !== "visible") break;
          const review = await apiFetch(`/api/v1/copilot/${kind}/${id}/review`, {
            method: "POST", authToken: token, signal: abort.signal, schema: planReviewSchema,
            body: { expected_portfolio_id: portfolioId },
          });
          if (review.plan_id !== id || review.portfolio_id !== portfolioId) throw new Error("Review scope mismatch.");
          if (abort.signal.aborted) break;
          const fingerprint = JSON.stringify([review.verdict, review.changed_fields, review.reasons]);
          const previous = fingerprints.current[id];
          fingerprints.current[id] = fingerprint;
          if (previous !== fingerprint && (previous !== undefined || review.changed_fields.length > 0)) {
            callback.current(review);
            setNotice(kind === "put-plans" ? "Saved Put assumptions changed. Open the plan review before recalculating." : "Saved funding assumptions changed. Review the plan before recalculating.");
          }
        }
      } catch (error) {
        if (!abort.signal.aborted) {
          setConsent(null);
          setNotice(error instanceof Error ? error.message : "Session review stopped. Please sign in and retry.");
        }
      } finally { running = false; }
    };
    const timer = window.setInterval(() => void tick(), 60_000);
    void tick();
    return () => { abort.abort(); window.clearInterval(timer); };
  }, [enabled, token, portfolioId, ids, kind]);

  function setEnabled(value: boolean) {
    fingerprints.current = {}; setNotice("");
    setConsent(value && token ? { token, portfolioId, scopeKey } : null);
  }
  return { enabled, setEnabled, notice };
}
