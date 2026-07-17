"use client";

/**
 * "Save as risk plan" — captures a what-if (or any analysis) as a reviewable
 * plan (PR2). Stores the baseline metric snapshot + the proposed change + the
 * expected impact so a future review can compare the plan to reality. It saves
 * an ANALYSIS, never an order.
 */

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { track } from "@/lib/analytics";
import { planMetrics } from "@/lib/plan-snapshot";
import type { ScoreResponse } from "@/lib/schemas";
import { type RiskPlan, useCreateRiskPlan } from "@/lib/queries";

export function SaveAsPlan({
  portfolioId,
  source,
  baseline,
  sandbox,
  proposedChanges,
  onSaved,
  onCancel,
}: {
  portfolioId: string | null;
  source: RiskPlan["source"];
  baseline: ScoreResponse | null;
  sandbox: ScoreResponse | null;
  proposedChanges?: Record<string, unknown>;
  onSaved?: (plan: RiskPlan) => void;
  onCancel?: () => void;
}) {
  const create = useCreateRiskPlan();
  const [title, setTitle] = useState("");
  const [hypothesis, setHypothesis] = useState("");

  if (!portfolioId) {
    return (
      <p className="text-xs text-muted-foreground">Select a portfolio to save a plan.</p>
    );
  }

  function save() {
    create.mutate(
      {
        portfolio_id: portfolioId!,
        title: title.trim() || "What-if scenario",
        source,
        hypothesis: hypothesis.trim() || null,
        baseline: planMetrics(baseline),
        proposed_changes: proposedChanges ?? {},
        expected_impact: planMetrics(sandbox),
        data_confidence:
          (baseline?.data_confidence as Record<string, unknown> | undefined) ?? {},
      },
      {
        onSuccess: (plan) => {
          track("risk_plan_saved", {}); // value-free
          track("journey_step_completed", { step: "plan" }); // stage enum only
          onSaved?.(plan);
        },
      },
    );
  }

  return (
    <div className="space-y-2 rounded-md border border-border bg-background p-3">
      <p className="text-sm font-medium">Save this as a risk plan</p>
      <input
        aria-label="Plan title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        maxLength={200}
        placeholder="e.g. Trim NVDA concentration"
        className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
      />
      <textarea
        aria-label="Hypothesis"
        value={hypothesis}
        onChange={(e) => setHypothesis(e.target.value)}
        maxLength={2000}
        rows={2}
        placeholder="What are you testing? (optional)"
        className="w-full rounded border border-border bg-background px-2 py-1 text-sm"
      />
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" disabled={create.isPending} onClick={save}>
          {create.isPending ? "Saving…" : "Save plan"}
        </Button>
        {onCancel && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        {create.isError && <span className="text-xs text-destructive">Could not save.</span>}
      </div>
      <p className="text-[11px] text-muted-foreground">
        Saves your analysis for later review — it never changes your holdings.
      </p>
    </div>
  );
}
