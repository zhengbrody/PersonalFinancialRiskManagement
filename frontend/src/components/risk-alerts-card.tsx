"use client";

/**
 * Proactive risk-alert card + LIFECYCLE. Shows the top deterministic risk alerts
 * (from /risk/alerts — no LLM, no credit) with per-alert actions: Ask Copilot,
 * Test this risk (→ Analyze Stress), and Mark seen / Snooze / Resolve (persisted
 * per-portfolio via /risk/alert_states, PR2). A resolved/snoozed alert stays
 * hidden until it forms a NEW episode — the alert_key encodes the severity, so
 * an ESCALATION (watch → high) is a new, unresolved key and re-appears.
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
import { usePortfolioContext } from "@/lib/portfolio-context";
import {
  type AlertStateRow,
  type RiskAlert,
  type RiskAlertsInput,
  useAlertStates,
  useRiskAlerts,
  useUpsertAlertState,
} from "@/lib/queries";

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

// Stable episode id. Prefer the backend `key` (encodes the SUBJECT — ticker /
// sector / option flag — plus severity), so resolving one name's alert never
// hides a DIFFERENT name's alert of the same type/severity, and an escalation
// re-surfaces. Fall back to type:severity only for pre-deploy cached alerts.
const alertKey = (a: RiskAlert) => a.key || `${a.type}:${a.severity}`;

function isHidden(state: AlertStateRow | undefined): boolean {
  if (!state) return false;
  if (state.state === "resolved") return true;
  if (state.state === "snoozed" && state.snooze_until) {
    const t = new Date(state.snooze_until).getTime();
    return Number.isFinite(t) && t > Date.now();
  }
  return false;
}

export function RiskAlertsCard({
  input,
  limit = 2,
  source,
}: {
  input: RiskAlertsInput | null;
  limit?: number;
  source: string; // analytics label only — never any data
}) {
  const { activePortfolioId } = usePortfolioContext();
  const alerts = useRiskAlerts(input);
  const states = useAlertStates(activePortfolioId);
  const upsert = useUpsertAlertState();

  // Gate on BOTH queries: wait for the lifecycle states (when a portfolio is
  // active — `isLoading` is false for the disabled/no-portfolio query, so it
  // never blocks then) so a resolved/snoozed alert never flashes before the GET
  // lands, and a switch can't apply one book's states to another's alerts.
  if (!input || alerts.isPending || states.isLoading) return null;

  const stateByKey = new Map<string, AlertStateRow>();
  for (const s of states.data?.states ?? []) stateByKey.set(s.alert_key, s);

  const visible = (alerts.data ?? []).filter((a) => !isHidden(stateByKey.get(alertKey(a))));
  const top = visible.slice(0, limit);
  if (top.length === 0) return null;

  function setLifecycle(a: RiskAlert, state: AlertStateRow["state"]) {
    if (!activePortfolioId) return;
    const snooze_until =
      state === "snoozed" ? new Date(Date.now() + 7 * 864e5).toISOString() : null;
    upsert.mutate({ portfolio_id: activePortfolioId, alert_key: alertKey(a), state, snooze_until });
    track("alert_lifecycle_changed", { state }); // state only — never alert content
  }

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">What to watch</CardTitle>
        <CardDescription>
          Your top {top.length === 1 ? "risk" : `${top.length} risks`} right now — dig in, or
          mark them handled.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {top.map((a) => (
          <AlertRow
            key={alertKey(a)}
            a={a}
            source={source}
            seen={stateByKey.get(alertKey(a))?.state === "seen"}
            canLifecycle={Boolean(activePortfolioId)}
            onLifecycle={(state) => setLifecycle(a, state)}
          />
        ))}
        {visible.length > top.length && (
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

function AlertRow({
  a,
  source,
  seen,
  canLifecycle,
  onLifecycle,
}: {
  a: RiskAlert;
  source: string;
  seen: boolean;
  canLifecycle: boolean;
  onLifecycle: (state: AlertStateRow["state"]) => void;
}) {
  return (
    <div className={`rounded-lg border p-3 ${SEVERITY_TONE[a.severity] ?? "border-border"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">
            {a.headline}
            {seen && <span className="ml-1 text-[10px] font-normal text-muted-foreground">· seen</span>}
          </p>
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
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <span className="mr-auto font-mono text-[11px] tabular-nums text-muted-foreground">
          {a.metric}
        </span>
        <Link
          href={`/copilot?q=${encodeURIComponent(a.ask_copilot)}`}
          onClick={() => track("copilot_followup_clicked", { source: `alert_${source}`, alert: a.type })}
          className="shrink-0 rounded-md border border-border px-2 py-0.5 hover:bg-accent"
        >
          Ask Copilot
        </Link>
        <Link
          href="/analyze?view=stress"
          className="shrink-0 rounded-md border border-border px-2 py-0.5 hover:bg-accent"
        >
          Test this risk
        </Link>
        {canLifecycle && (
          <>
            {!seen && (
              <button type="button" onClick={() => onLifecycle("seen")} className="rounded-md px-2 py-0.5 text-muted-foreground hover:bg-accent">
                Seen
              </button>
            )}
            <button type="button" onClick={() => onLifecycle("snoozed")} className="rounded-md px-2 py-0.5 text-muted-foreground hover:bg-accent">
              Snooze
            </button>
            <button type="button" onClick={() => onLifecycle("resolved")} className="rounded-md px-2 py-0.5 text-muted-foreground hover:bg-accent">
              Resolve
            </button>
          </>
        )}
      </div>
    </div>
  );
}
