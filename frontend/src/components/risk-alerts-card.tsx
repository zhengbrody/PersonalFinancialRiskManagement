"use client";

/**
 * Proactive risk-alert card — shows the top 1-2 deterministic risk alerts and
 * a one-tap "Ask Copilot" deep-link per alert. Every figure comes from the
 * backend's deterministic /risk/alerts builder (no LLM, no credit); the LLM only
 * runs if the user clicks through to the Copilot. Robinhood-simple: lead with
 * the single most important risk, let the user go deeper.
 */

import Link from "next/link";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { track } from "@/lib/analytics";
import { useRiskAlerts, type RiskAlert, type RiskAlertsInput } from "@/lib/queries";

const SEVERITY_TONE: Record<string, string> = {
  high: "border-red-500/40 bg-red-500/5",
  elevated: "border-amber-500/40 bg-amber-500/5",
  moderate: "border-primary/30",
  low: "border-border",
};
const SEVERITY_TEXT: Record<string, string> = {
  high: "text-red-600 dark:text-red-400",
  elevated: "text-amber-600 dark:text-amber-400",
  moderate: "text-primary",
  low: "text-muted-foreground",
};

export function RiskAlertsCard({
  input,
  limit = 2,
  source,
}: {
  input: RiskAlertsInput | null;
  limit?: number;
  source: string; // analytics label only (e.g. "score" | "risk") — never any data
}) {
  const alerts = useRiskAlerts(input);
  const top = (alerts.data ?? []).slice(0, limit);
  if (!input || alerts.isPending || top.length === 0) return null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">What to watch</CardTitle>
        <CardDescription>
          Your top {top.length === 1 ? "risk" : `${top.length} risks`} right now — tap to ask
          the Copilot for the detail.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {top.map((a) => (
          <AlertRow key={a.type} a={a} source={source} />
        ))}
        {(alerts.data?.length ?? 0) > top.length && (
          <Link
            href="/copilot"
            onClick={() => track("copilot_opened", { source: `alerts_${source}` })}
            className="inline-block pt-1 text-xs text-primary hover:underline"
          >
            See all risks in Copilot →
          </Link>
        )}
      </CardContent>
    </Card>
  );
}

function AlertRow({ a, source }: { a: RiskAlert; source: string }) {
  return (
    <div className={`rounded-lg border p-3 ${SEVERITY_TONE[a.severity] ?? "border-border"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{a.headline}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{a.detail}</p>
        </div>
        <span
          className={`shrink-0 text-[10px] font-semibold uppercase tracking-wide ${
            SEVERITY_TEXT[a.severity] ?? "text-muted-foreground"
          }`}
        >
          {a.severity}
        </span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{a.metric}</span>
        <Link
          href={`/copilot?q=${encodeURIComponent(a.ask_copilot)}`}
          onClick={() => track("copilot_followup_clicked", { source: `alert_${source}`, alert: a.type })}
          className="shrink-0 rounded-md border border-border px-2.5 py-1 text-xs hover:bg-accent"
        >
          Ask Copilot →
        </Link>
      </div>
    </div>
  );
}
