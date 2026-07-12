"use client";

/**
 * Copilot 2.0 — structured single-shot answer.
 *
 * Distinct from the streaming <CopilotConversation/>: the user picks an intent
 * quick-prompt (or types a question), we call the credit-gated /copilot/ask
 * endpoint, and render ONE structured card — a pre-formatted five-section
 * markdown answer plus an Evidence strip where every fact carries a source
 * badge. The whole point of Research/Copilot 2.0: the answer's numbers are the
 * platform's vetted evidence, never invented by the model.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { DataConfidence } from "@/components/data-confidence";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import { ApiError } from "@/lib/api";
import { BETA_LIMIT_MESSAGE, isBillingEnabled } from "@/lib/billing-flag";
import { track } from "@/lib/analytics";
import { useSessionState } from "@/lib/use-session-state";
import { type CopilotAnswer, type CopilotEvidence, useCopilotAsk } from "@/lib/queries";

const QUICK_PROMPTS = [
  "How risky is my portfolio?",
  "Compare AAPL vs MSFT",
  "Explain my Sharpe ratio",
  "What if the market drops 20%?",
  "Am I paying hidden fees?",
];

// Chinese counterparts (same order/intent) — shown when the browser locale
// is Chinese so the quick prompts already match the user's language.
const QUICK_PROMPTS_ZH = [
  "我的投资组合风险有多高？",
  "对比 AAPL 和 MSFT",
  "解释我的 Sharpe 比率",
  "如果市场下跌 20% 会怎样？",
  "我在支付隐藏费用吗？",
];

const SOURCE_STYLE: Record<string, string> = {
  engine: "border-primary/40 bg-primary/10 text-primary",
  fmp: "border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  yfinance: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400",
  macro: "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  derived: "border-violet-500/40 bg-violet-500/10 text-violet-600 dark:text-violet-400",
  glossary: "border-border bg-muted text-muted-foreground",
};

function sourceClass(source: string): string {
  return SOURCE_STYLE[source] ?? SOURCE_STYLE.glossary;
}

export function CopilotAsk({ initialQuestion }: { initialQuestion?: string } = {}) {
  // Prefill from a deep-link (e.g. the Research → Copilot handoff). We DON'T
  // auto-run — the user clicks "Get answer", so a credit is never spent by a
  // navigation alone.
  const [message, setMessage] = useState(initialQuestion ?? "");
  const ask = useCopilotAsk();
  // Persist the last answer so switching screens/tabs and returning restores it
  // instead of an empty card (the mutation result itself is lost on unmount).
  const [savedAnswer, setSavedAnswer] = useSessionState<CopilotAnswer | null>(
    "mm:copilot:ask:answer",
    null,
  );
  const answer = ask.data ?? savedAnswer;
  // Default English on the first render and switch post-mount when the
  // browser locale is Chinese (SSR-safe: never touch `navigator` in render).
  const [zh, setZh] = useState(false);
  useEffect(() => {
    setZh(navigator.language?.toLowerCase().startsWith("zh") ?? false);
  }, []);
  const quickPrompts = zh ? QUICK_PROMPTS_ZH : QUICK_PROMPTS;

  function run(q: string) {
    const text = q.trim();
    if (!text || ask.isPending) return;
    setMessage(text);
    ask.mutate(
      { message: text },
      {
        onSuccess: (a) => {
          setSavedAnswer(a);
          track("copilot_ask", { intent: a.intent });
        },
      },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Ask Copilot — structured answer</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(message);
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <Input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Ask about a stock, your portfolio, or the market…"
            aria-label="Ask Copilot"
          />
          <Button type="submit" disabled={ask.isPending || !message.trim()}>
            {ask.isPending ? "Thinking…" : "Get answer"}
          </Button>
        </form>

        <div className="flex flex-wrap gap-2">
          {quickPrompts.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => run(q)}
              disabled={ask.isPending}
              className="rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground transition hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
            >
              {q}
            </button>
          ))}
        </div>

        {ask.isPending && <AnswerSkeleton />}
        {ask.isError && !ask.isPending && <AskError error={ask.error} />}
        {answer && !ask.isPending && !ask.isError && <AnswerCard answer={answer} />}
      </CardContent>
    </Card>
  );
}

function AnswerCard({ answer }: { answer: CopilotAnswer }) {
  return (
    <div className="space-y-4 rounded-lg border border-border bg-card/50 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
          {answer.intent.replace(/_/g, " ")}
        </span>
        {answer.tickers.map((t) => (
          <span
            key={t}
            className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium"
          >
            {t}
          </span>
        ))}
        {answer.data_only && (
          <span className="text-[10px] text-muted-foreground">
            data-driven (no AI key)
          </span>
        )}
      </div>

      <div className="text-[15px] leading-relaxed">
        <Markdown>{answer.answer_markdown}</Markdown>
      </div>

      <DataConfidence confidence={answer.data_confidence} title="Answer confidence" />

      {answer.evidence.length > 0 && (
        <div className="space-y-2 border-t border-border pt-3">
          <p className="text-xs font-medium text-muted-foreground">
            Evidence — every number above is one of these vetted facts
          </p>
          <div className="flex flex-wrap gap-2">
            {answer.evidence.map((e, i) => (
              <EvidenceChip key={`${e.label}-${i}`} item={e} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EvidenceChip({ item }: { item: CopilotEvidence }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-xs">
      <span className="text-muted-foreground">{item.label}:</span>
      <span className="font-medium">{item.value}</span>
      <span
        className={`rounded px-1 py-0.5 text-[10px] font-semibold uppercase ${sourceClass(item.source)}`}
      >
        {item.source}
      </span>
    </span>
  );
}

function AnswerSkeleton() {
  return (
    <div className="space-y-2 rounded-lg border border-border p-4">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-16 w-full" />
    </div>
  );
}

function AskError({ error }: { error: Error }) {
  if (error instanceof ApiError && error.code === "quota_exceeded") {
    if (!isBillingEnabled()) {
      return (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-muted-foreground">
          {BETA_LIMIT_MESSAGE}
        </div>
      );
    }
    return (
      <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
        <p className="font-medium">You&apos;ve used your AI credits this month.</p>
        <p className="mt-1 text-muted-foreground">
          Upgrade for more Copilot answers.
        </p>
        <Link href="/pricing" className="mt-2 inline-block">
          <Button size="sm" variant="outline">
            See plans
          </Button>
        </Link>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-muted-foreground">
      Something went wrong. Please try again.
    </div>
  );
}
