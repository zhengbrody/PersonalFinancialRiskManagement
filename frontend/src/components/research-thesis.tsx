"use client";

/**
 * AI-grounded bull/bear/monitor thesis (Phase 3). The LLM only writes prose over
 * the deterministic FactPack/DCF/earnings evidence — it never invents numbers
 * (the backend flags any it can't ground) and gives no buy/sell/hold call. On
 * demand (credit-gated); falls back to a deterministic thesis with no LLM key.
 */

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { isBillingEnabled, BETA_LIMIT_MESSAGE } from "@/lib/billing-flag";
import { ApiError } from "@/lib/api";
import { useThesis, type ThesisOutput } from "@/lib/queries";

export function ResearchThesis({
  ticker,
  initial,
}: {
  ticker: string | null;
  initial?: ThesisOutput;
}) {
  const m = useThesis();
  if (!ticker) return null;
  // The LLM upgrade (m.data) wins; otherwise the deterministic thesis the
  // bundle already computed (initial) renders immediately.
  const thesis = m.data?.thesis ?? initial;

  if (!thesis) {
    return (
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">AI investment debate</CardTitle>
          <CardDescription>
            A grounded bull/bear case written over the deterministic figures — no recommendation, no
            invented numbers.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          {m.isError && <ErrorNote error={m.error} />}
          <Button size="sm" onClick={() => m.mutate({ ticker })} disabled={m.isPending}>
            {m.isPending ? "Thinking…" : "Build the bull / bear debate"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  // When the shown thesis is still the deterministic one, offer the AI upgrade.
  const canUpgrade = !m.data && !thesis.ai_generated;
  return (
    <div className="space-y-2">
      <ThesisCard thesis={thesis} />
      {canUpgrade && (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={() => m.mutate({ ticker })}
            disabled={m.isPending}
          >
            {m.isPending ? "Thinking…" : "Upgrade to the AI-written debate"}
          </Button>
          {m.isError && <ErrorNote error={m.error} />}
        </div>
      )}
    </div>
  );
}

function ThesisCard({ thesis }: { thesis: ThesisOutput }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-base">AI investment debate</CardTitle>
          <span
            className={`rounded px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${thesis.ai_generated ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}
          >
            {thesis.ai_generated ? "AI-generated" : "Deterministic"}
          </span>
        </div>
        {thesis.key_debate && (
          <CardDescription className="text-foreground">{thesis.key_debate}</CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Lane title="Bull case" items={thesis.bull_case} tone="emerald" />
          <Lane title="Bear case" items={thesis.bear_case} tone="red" />
        </div>
        <Lane title="What to monitor next quarter" items={thesis.monitor_next_quarter} />
        <Lane title="What would change the view" items={thesis.what_would_change_view} />
        <Lane title="Questions for management" items={thesis.questions_for_management} />
        {thesis.red_flags.length > 0 && <Lane title="Red flags" items={thesis.red_flags} tone="red" />}

        {thesis.warnings.length > 0 && (
          <div className="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
            {thesis.warnings.map((w) => (
              <p key={w}>⚠ {w}</p>
            ))}
            {thesis.flagged_numbers.length > 0 && (
              <p className="mt-1 font-mono">Unverified figures: {thesis.flagged_numbers.join(", ")}</p>
            )}
          </div>
        )}
        <p className="text-xs leading-relaxed text-muted-foreground">{thesis.disclaimer}</p>
      </CardContent>
    </Card>
  );
}

function Lane({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone?: "emerald" | "red";
}) {
  if (items.length === 0) return null;
  const dot = tone === "emerald" ? "bg-emerald-500" : tone === "red" ? "bg-red-500" : "bg-muted-foreground";
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </p>
      <ul className="space-y-1.5 text-sm">
        {items.map((it, i) => (
          <li key={i} className="flex gap-2">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ErrorNote({ error }: { error: Error }) {
  const code = error instanceof ApiError ? error.code : "";
  if (code === "quota_exceeded") {
    if (!isBillingEnabled()) {
      return <p className="text-sm text-muted-foreground">{BETA_LIMIT_MESSAGE}</p>;
    }
    return (
      <p className="text-sm text-muted-foreground">
        You&apos;ve used your analysis quota.{" "}
        <Link href="/pricing" className="text-primary hover:underline">
          See plans
        </Link>
      </p>
    );
  }
  return <p className="text-sm text-muted-foreground">Couldn&apos;t build the thesis — try again.</p>;
}
