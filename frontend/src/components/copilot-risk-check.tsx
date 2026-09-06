"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { formatCheckValue, type RiskCheck } from "@/lib/risk-check";

export function CopilotRiskCheck({
  result,
  onRepeat,
  disabled,
}: {
  result: RiskCheck;
  onRepeat: () => void;
  disabled: boolean;
}) {
  const [showMetrics, setShowMetrics] = useState(false);
  return (
    <section
      aria-label="Portfolio risk check"
      className="min-w-0 space-y-4 rounded-2xl border border-border bg-card p-4 sm:p-5"
    >
      <header className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-primary">
          Your risk check
        </p>
        <h2 className="text-lg font-semibold">
          Understand what could hurt your portfolio
        </h2>
        <p className="text-sm text-muted-foreground">{result.summary}</p>
        <p className="text-xs text-muted-foreground">
          {result.status === "limited"
            ? "Limited coverage — not a complete account-risk assessment"
            : "Available checks completed — not a safety guarantee"}
        </p>
        <p className="text-xs text-muted-foreground">
          Historical result · generated{" "}
          {new Date(result.computed_at).toLocaleString()} · price history
          through {result.price_history_as_of ?? "unknown"}. Rerun after
          changing holdings.
        </p>
      </header>
      <ol className="space-y-2">
        {result.findings.map((finding) => (
          <li key={finding.key} className="rounded-xl border border-border p-3">
            <p className="font-medium">
              {finding.title}{" "}
              <span className="text-xs text-muted-foreground">
                · {finding.severity === "info" ? "review" : finding.severity}
              </span>
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {finding.explanation}
            </p>
          </li>
        ))}
      </ol>
      {result.strategies.length > 0 && (
        <details className="rounded-xl border border-border p-3">
          <summary className="cursor-pointer text-sm font-medium">
            Your options — grouped expiry risk
          </summary>
          <p className="mt-2 text-xs text-muted-foreground">
            Option-only groups, not stock-covered positions or original orders.
            Expiry bounds do not include early assignment, execution or
            financing costs. Do not sum different expiries as one loss limit.
          </p>
          <div className="mt-3 space-y-3">
            {result.strategies.map((s) => (
              <article
                key={`${s.underlying}:${s.expiry}`}
                className="rounded-lg border border-border p-3 text-sm"
              >
                <h3 className="font-medium">
                  {s.underlying} · {s.name.replace(/_/g, " ")} · {s.expiry}
                </h3>
                <p className="text-xs text-muted-foreground">
                  {s.leg_count} legs ·{" "}
                  {s.premium_basis === "entry"
                    ? "Entry-cost basis"
                    : s.premium_basis === "current_mark"
                      ? "Current-mark basis — not original trade cost"
                      : s.premium_basis === "mixed"
                        ? "Mixed entry/mark basis — not original maximum loss"
                        : "Premium basis unavailable"}
                </p>
                <dl className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      Expiry maximum loss
                    </dt>
                    <dd className="font-semibold">
                      {bound(s.loss_status, s.max_loss)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">
                      Expiry maximum gain
                    </dt>
                    <dd className="font-semibold">
                      {bound(s.gain_status, s.max_gain)}
                    </dd>
                  </div>
                </dl>
              </article>
            ))}
          </div>
        </details>
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-expanded={showMetrics}
        onClick={() => setShowMetrics(!showMetrics)}
      >
        {showMetrics ? "Hide the numbers" : "Understand the numbers"}
      </Button>
      {showMetrics && (
        <div className="grid min-w-0 gap-3 sm:grid-cols-2">
          {result.metrics.map((metric) => (
            <article
              key={metric.key}
              className="min-w-0 rounded-xl border border-border p-3"
            >
              <h3 className="text-sm font-medium">{metric.label}</h3>
              <p className="mt-2 text-2xl font-semibold tabular-nums">
                {formatCheckValue(metric)}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {metric.horizon}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                {metric.explanation}
              </p>
              <details className="mt-2 text-xs text-muted-foreground">
                <summary className="cursor-pointer">
                  Calculation basis &amp; source
                </summary>
                <p className="mt-1">{metric.basis}</p>
                <p className="break-all">
                  Risk engine · {metric.source_field} ·{" "}
                  {result.methodology_version}
                </p>
              </details>
            </article>
          ))}
        </div>
      )}
      <details
        className="rounded-lg border border-border p-3 text-sm"
        open={result.status === "limited"}
      >
        <summary className="cursor-pointer font-medium">
          What this check cannot tell you
        </summary>
        <ul className="mt-2 list-disc space-y-2 pl-5 text-muted-foreground">
          {result.limitations.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
      <Button type="button" size="sm" onClick={onRepeat} disabled={disabled}>
        Run a fresh check
      </Button>
      <p className="text-xs text-muted-foreground">
        Deterministic model estimates · no trades or changes to your holdings.
      </p>
    </section>
  );
}

function bound(
  status: "bounded" | "unbounded" | "unavailable",
  value: number | null,
): string {
  if (status === "unavailable" || (status === "bounded" && value === null))
    return "Unavailable";
  if (status === "unbounded") return "Unbounded in expiry model";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value!);
}
