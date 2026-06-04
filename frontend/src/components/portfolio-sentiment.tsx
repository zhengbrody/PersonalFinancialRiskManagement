"use client";

/**
 * Per-holding AI sentiment (signed-in only). On-demand — it spends credits, so
 * the user clicks to run it. Each holding gets a 0–100 sentiment bar + label +
 * a one-line narrative. Quota → "see plans" CTA; data-only without an LLM key.
 */

import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { track } from "@/lib/analytics";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { usePortfolioSentiment, type SentimentRow } from "@/lib/queries";
import { cn } from "@/lib/utils";

function tone(score: number): string {
  if (score >= 60) return "text-emerald-600 dark:text-emerald-400";
  if (score <= 40) return "text-red-600 dark:text-red-400";
  return "text-amber-600 dark:text-amber-400";
}
function barColor(score: number): string {
  if (score >= 60) return "bg-emerald-500/70";
  if (score <= 40) return "bg-red-500/70";
  return "bg-amber-500/70";
}

export function PortfolioSentiment() {
  const { user, configured } = useAuth();
  const sentiment = usePortfolioSentiment();

  // Public visitors can't score a portfolio — keep the section signed-in only.
  if (!configured || !user) return null;

  const err = sentiment.error as ApiError | null;
  const quotaHit = err instanceof ApiError && err.code === "quota_exceeded";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">Your holdings — AI sentiment</CardTitle>
            <CardDescription>
              What the latest headlines say about each of your positions.
            </CardDescription>
          </div>
          <Button
            size="sm"
            disabled={sentiment.isPending}
            onClick={() => {
              sentiment.mutate(undefined, {
                onSuccess: (d) => track("markets_sentiment_viewed", { ai: d.ai_generated }),
              });
            }}
          >
            {sentiment.isPending
              ? "Scoring…"
              : sentiment.data
                ? "Refresh"
                : "Score my holdings"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {sentiment.isPending && (
          <>
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </>
        )}

        {quotaHit && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
            You&apos;re out of AI credits for this month.{" "}
            <Link href="/pricing" className="font-medium text-primary hover:underline">
              See plans →
            </Link>
          </div>
        )}
        {err && !quotaHit && (
          <p className="text-sm text-red-500">Couldn&apos;t score sentiment — try again shortly.</p>
        )}

        {sentiment.data && sentiment.data.sentiments.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No holdings to score yet — add some on the Holdings page.
          </p>
        )}

        {sentiment.data?.sentiments.map((s: SentimentRow) => (
          <div key={s.ticker} className="rounded-md border border-border bg-muted/20 p-3">
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono font-medium">{s.ticker}</span>
              <span className={cn("text-sm font-semibold", tone(s.score))}>{s.label}</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-muted">
              <div className={cn("h-full", barColor(s.score))} style={{ width: `${s.score}%` }} />
            </div>
            {s.narrative && (
              <p className="mt-1.5 text-xs text-muted-foreground">{s.narrative}</p>
            )}
          </div>
        ))}

        {sentiment.data && !sentiment.data.ai_generated && sentiment.data.sentiments.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Showing headline counts only — AI scoring is unavailable right now.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
