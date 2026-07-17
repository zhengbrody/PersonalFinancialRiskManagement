"use client";

/**
 * Saved risk plans (PR2): the list, a deterministic "Review" (compares a plan's
 * baseline to the current metrics), status lifecycle, and due-review surfacing.
 * A plan is an analysis to revisit — nothing here changes holdings.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { track } from "@/lib/analytics";
import { planMetrics } from "@/lib/plan-snapshot";
import type { ScoreResponse } from "@/lib/schemas";
import {
  type PlanReview,
  type RiskPlan,
  useDeleteRiskPlan,
  useReviewPlan,
  useRiskPlans,
  useUpdateRiskPlan,
} from "@/lib/queries";

const STATUS_TONE: Record<RiskPlan["status"], "neutral" | "primary" | "success" | "warning"> = {
  draft: "neutral",
  active: "primary",
  resolved: "success",
  archived: "neutral",
};
const VERDICT_TONE: Record<PlanReview["verdict"], "success" | "danger" | "neutral"> = {
  improved: "success",
  worsened: "danger",
  inconclusive: "neutral",
};

function isDue(p: RiskPlan): boolean {
  if (!p.review_at || p.status === "resolved" || p.status === "archived") return false;
  const t = new Date(p.review_at).getTime();
  return Number.isFinite(t) && t <= Date.now();
}

export function RiskPlansPanel({
  portfolioId,
  currentScore,
}: {
  portfolioId: string | null;
  currentScore: ScoreResponse | null;
}) {
  const plans = useRiskPlans(portfolioId);

  if (plans.isLoading) return <Skeleton className="h-24 w-full" />;
  if (plans.isError) return null; // 503 not-provisioned → hide (per the digest-card contract)
  const list = plans.data?.plans ?? [];
  if (list.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No saved plans yet. Run a what-if or an action simulation and “Save as risk plan” to
        revisit it later.
      </p>
    );
  }

  const due = list.filter(isDue);
  return (
    <div className="space-y-3">
      {due.length > 0 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs">
          <span className="font-medium text-amber-700 dark:text-amber-300">
            {due.length} plan{due.length === 1 ? "" : "s"} due for review
          </span>
        </div>
      )}
      <ul className="space-y-2">
        {list.map((p) => (
          <PlanCard key={p.id} plan={p} currentScore={currentScore} due={isDue(p)} />
        ))}
      </ul>
    </div>
  );
}

function PlanCard({
  plan,
  currentScore,
  due,
}: {
  plan: RiskPlan;
  currentScore: ScoreResponse | null;
  due: boolean;
}) {
  const review = useReviewPlan();
  const update = useUpdateRiskPlan();
  const del = useDeleteRiskPlan();
  const [result, setResult] = useState<PlanReview | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  function runReview() {
    review.mutate(
      { id: plan.id, current: planMetrics(currentScore) },
      {
        onSuccess: (r) => {
          setResult(r);
          track("risk_plan_reviewed", {}); // value-free
          track("journey_step_completed", { step: "review" }); // stage enum only
        },
      },
    );
  }

  return (
    <li
      className={`rounded-md border p-3 text-sm ${due ? "border-amber-500/40" : "border-border"}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">{plan.title}</span>
            <Badge tone={STATUS_TONE[plan.status]} uppercase>
              {plan.status}
            </Badge>
          </div>
          {plan.hypothesis && (
            <p className="mt-0.5 text-xs text-muted-foreground">{plan.hypothesis}</p>
          )}
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            from {plan.source}
            {plan.created_at ? ` · ${plan.created_at.slice(0, 10)}` : ""}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button type="button" size="sm" variant="outline" disabled={review.isPending} onClick={runReview}>
            {review.isPending ? "…" : "Review"}
          </Button>
        </div>
      </div>

      {result && (
        <div className="mt-2 space-y-1 rounded bg-muted/30 p-2">
          <div className="flex items-center gap-2">
            <Badge tone={VERDICT_TONE[result.verdict]} uppercase>
              {result.verdict}
            </Badge>
            <span className="text-[11px] text-muted-foreground">{result.confidence} confidence</span>
          </div>
          <ul className="space-y-0.5">
            {result.metrics
              .filter((m) => m.improved !== null && m.current != null)
              .map((m) => (
                <li key={m.metric} className="flex items-center justify-between text-[11px]">
                  <span className="text-muted-foreground">{m.metric.replace(/_/g, " ")}</span>
                  <span className={m.improved ? "text-emerald-600 dark:text-emerald-400" : "text-destructive"}>
                    {m.improved ? "↓ better" : "↑ worse"}
                  </span>
                </li>
              ))}
          </ul>
          {result.missing_data.length > 0 && (
            <p className="text-[11px] text-muted-foreground">
              Not comparable: {result.missing_data.join(", ")}
            </p>
          )}
          <p className="text-[10px] text-muted-foreground">{result.disclaimer}</p>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px]">
        {plan.status !== "resolved" && (
          <Button type="button" size="sm" variant="ghost" onClick={() => update.mutate({ id: plan.id, patch: { status: "resolved" } })}>
            Mark resolved
          </Button>
        )}
        {plan.status === "draft" && (
          <Button type="button" size="sm" variant="ghost" onClick={() => update.mutate({ id: plan.id, patch: { status: "active" } })}>
            Activate
          </Button>
        )}
        {!confirmDelete ? (
          <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmDelete(true)}>
            Delete
          </Button>
        ) : (
          <>
            <Button type="button" size="sm" variant="destructive" onClick={() => del.mutate(plan.id)}>
              Confirm delete
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>
              Keep
            </Button>
          </>
        )}
      </div>
    </li>
  );
}
