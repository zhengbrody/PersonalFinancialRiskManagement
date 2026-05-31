"use client";

/**
 * "Market season" — the market's bull / bear / transition mood, in plain
 * English, for the /markets page. Ported from the legacy Quant Lab regime
 * detector (`regime_detector` composite GMM/vol/trend).
 *
 * Robinhood skin: a big current-regime badge + confidence + "since <date>",
 * the three underlying signals as chips, and a color-coded regime-history
 * ribbon so a novice sees the trend at a glance. Semantic theme tokens only
 * (light/dark safe); null-safe per field; Skeleton on load; friendly error.
 */

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useRegimeDetail } from "@/lib/queries";

type Tone = "good" | "bad" | "warn" | "neutral";

/** Map a free-text regime label to a tone (bull→good, bear→bad, else warn). */
function toneOf(label: string | null | undefined): Tone {
  if (!label) return "neutral";
  const l = label.toLowerCase();
  if (l.includes("bull")) return "good";
  if (l.includes("bear")) return "bad";
  if (l.includes("transition") || l.includes("mixed") || l.includes("lean")) return "warn";
  return "neutral";
}

const TONE_TEXT: Record<Tone, string> = {
  good: "text-emerald-500",
  bad: "text-rose-500",
  warn: "text-amber-500",
  neutral: "text-muted-foreground",
};
const TONE_BG: Record<Tone, string> = {
  good: "bg-emerald-500",
  bad: "bg-rose-500",
  warn: "bg-amber-500",
  neutral: "bg-muted-foreground/40",
};

export function MarketSeason() {
  const q = useRegimeDetail();

  return (
    <section className="space-y-4">
      <div>
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          Market season · live
        </p>
        <h2 className="text-2xl font-semibold tracking-tight">Bull, bear, or in-between?</h2>
        <p className="text-xs text-muted-foreground">
          The market&apos;s current phase from trend, volatility &amp; VIX signals.
        </p>
      </div>

      {q.isLoading && <Skeleton className="h-44" />}

      {q.isError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-muted-foreground">
          Could not load the market regime right now.
        </div>
      )}

      {q.data && (
        <Card>
          <CardHeader className="p-4 pb-2">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <CardTitle className={`text-2xl ${TONE_TEXT[toneOf(q.data.current_regime)]}`}>
                {q.data.current_regime ?? "—"}
              </CardTitle>
              {q.data.confidence != null && (
                <span className="text-sm text-muted-foreground">
                  {Math.round(q.data.confidence * 100)}% confidence
                </span>
              )}
              {q.data.regime_since_date && (
                <span className="text-xs text-muted-foreground">
                  since {q.data.regime_since_date}
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3 p-4 pt-0">
            {/* sub-signals */}
            <div className="flex flex-wrap gap-2">
              <SignalChip label="Trend" value={q.data.trend_regime} />
              <SignalChip label="Volatility" value={q.data.vol_regime} />
              <SignalChip label="VIX" value={q.data.vix_regime} />
            </div>

            {q.data.history.length > 0 && (
              <RegimeRibbon history={q.data.history} />
            )}
          </CardContent>
        </Card>
      )}
    </section>
  );
}

function SignalChip({ label, value }: { label: string; value: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2.5 py-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={value ? TONE_TEXT[toneOf(value)] : "text-muted-foreground"}>
        {value ?? "—"}
      </span>
    </span>
  );
}

/**
 * Horizontal ribbon of one segment per history point, colored by regime —
 * a lightweight, novice-readable timeline (no chart lib needed).
 */
function RegimeRibbon({ history }: { history: { date: string; regime: string }[] }) {
  const first = history[0]?.date ?? "";
  const last = history[history.length - 1]?.date ?? "";
  return (
    <div className="space-y-1.5">
      <div className="flex h-3 w-full overflow-hidden rounded-sm">
        {history.map((p, i) => (
          <div
            key={`${p.date}-${i}`}
            className={`h-full flex-1 ${TONE_BG[toneOf(p.regime)]}`}
            title={`${p.date}: ${p.regime}`}
          />
        ))}
      </div>
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{first}</span>
        <span>{last}</span>
      </div>
      <div className="flex flex-wrap gap-3 pt-0.5 text-[10px] text-muted-foreground">
        <LegendDot tone="good" label="Bull" />
        <LegendDot tone="warn" label="Transition" />
        <LegendDot tone="bad" label="Bear" />
      </div>
    </div>
  );
}

function LegendDot({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={`inline-block h-2 w-2 rounded-full ${TONE_BG[tone]}`} />
      {label}
    </span>
  );
}
