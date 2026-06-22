"use client";

/**
 * Market risk-state from the TRAINED classifier (backend/app/ml, /api/v1/ml/regime).
 * This is market CONTEXT only — a risk-STATE read (calm…stressed), NOT a price
 * forecast, NOT advice, and it does NOT change the deterministic Health Score.
 * Every figure is shown with provenance (model version, as-of, source).
 */

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useMlRegime } from "@/lib/queries";
import type { MlRegime } from "@/lib/queries";

const STATE: Record<string, { label: string; blurb: string; tone: string; dot: string }> = {
  risk_on: {
    label: "Calm",
    blurb: "Volatility is expected to stay low over the next ~2 weeks.",
    tone: "border-emerald-300/60 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-950/30 dark:text-emerald-200",
    dot: "bg-emerald-500",
  },
  neutral: {
    label: "Normal",
    blurb: "Volatility is near its typical range.",
    tone: "border-sky-300/60 bg-sky-50 text-sky-900 dark:border-sky-500/30 dark:bg-sky-950/30 dark:text-sky-200",
    dot: "bg-sky-500",
  },
  volatile: {
    label: "Elevated",
    blurb: "Choppier, higher-volatility conditions look more likely.",
    tone: "border-amber-300/60 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-200",
    dot: "bg-amber-500",
  },
  stress: {
    label: "Stressed",
    blurb: "A high-volatility, risk-off environment.",
    tone: "border-red-300/60 bg-red-50 text-red-900 dark:border-red-500/30 dark:bg-red-950/30 dark:text-red-200",
    dot: "bg-red-500",
  },
};

function provenance(r: MlRegime): string {
  if (r.source === "unavailable") return "market data unavailable";
  if (r.source === "heuristic_fallback")
    return `current-vol estimate · model unavailable${r.last_updated ? ` · as of ${r.last_updated}` : ""}`;
  return `model ${r.model_version ?? "regime"}${r.last_updated ? ` · as of ${r.last_updated}` : ""}`;
}

// One source of truth for the compliance caveat — it lived in three surfaces
// with drifting wording. Centralized so the "not advice / not your score"
// invariant can't be weakened in just one of them.
const REGIME_CAVEAT =
  "Risk-state only — not a price forecast, not investment advice, and it does not change your Health Score.";

type RegimeView = { r: MlRegime; s: (typeof STATE)[string] };

/** Shared data + fail-soft guard for both surfaces (one hook, one rule). */
function useRegimeState(): { loading: boolean; view: RegimeView | null } {
  const q = useMlRegime();
  const r = q.data;
  if (!r || !r.regime || r.source === "unavailable") {
    return { loading: q.isLoading, view: null }; // loading or genuinely hidden
  }
  return { loading: false, view: { r, s: STATE[r.regime] ?? STATE.neutral } };
}

export function RegimeContext() {
  const { loading, view } = useRegimeState();
  if (loading) return <Skeleton className="h-40 w-full rounded-lg" />;
  if (!view) return null; // fail-soft: hide
  const { r, s } = view;
  const conf = r.confidence != null ? `${Math.round(r.confidence * 100)}%` : null;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle>Risk-state model</CardTitle>
        <CardDescription>
          A trained classifier&apos;s read of the near-term volatility regime — context, not advice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className={`flex items-center justify-between gap-3 rounded-md border p-3 ${s.tone}`}>
          <div className="flex items-center gap-2">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${s.dot}`} />
            <span className="text-base font-semibold">{s.label}</span>
            <span className="text-xs uppercase tracking-wide opacity-70">{r.regime}</span>
          </div>
          {conf && <span className="font-mono text-sm tabular-nums">{conf} confidence</span>}
        </div>
        <p className="text-sm text-muted-foreground">{s.blurb}</p>

        {r.top_drivers.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              What the model is weighing
            </p>
            {r.top_drivers.map((d) => (
              <div key={d.feature} className="flex items-center justify-between gap-3 text-sm">
                <span>{d.label}</span>
                <span className="text-muted-foreground">{d.vs_normal}</span>
              </div>
            ))}
          </div>
        )}

        <p className="border-t border-border/40 pt-2 text-xs text-muted-foreground">
          {REGIME_CAVEAT} <span className="opacity-70">Source: {provenance(r)}.</span>
        </p>
      </CardContent>
    </Card>
  );
}

/** Compact one-liner for /score + /risk — the same model, as a context chip. */
export function RegimeContextLine() {
  const { view } = useRegimeState();
  if (!view) return null;
  const { r, s } = view;
  const conf = r.confidence != null ? ` (${Math.round(r.confidence * 100)}%)` : "";
  return (
    <p className="flex items-start gap-2 text-sm text-muted-foreground">
      <span className={`mt-1 inline-block h-2 w-2 shrink-0 rounded-full ${s.dot}`} />
      <span>
        Market risk-state: <span className="font-medium text-foreground">{s.label}</span>
        {conf}. {REGIME_CAVEAT}
      </span>
    </p>
  );
}
