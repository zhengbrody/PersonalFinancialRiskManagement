"use client";

/**
 * Copilot 2.0 — structured single-shot answer (six-section renderer).
 *
 * Distinct from the streaming <CopilotConversation/>: the user picks a
 * quick-prompt (or types a question), we call the credit-gated /copilot/ask
 * endpoint, and render the SIX-SECTION contract the backend composes —
 * direct answer first, then portfolio relevance, expandable evidence (source ·
 * tool · id), data confidence & missing data, what-would-change, and a
 * visually-distinct what-if simulation. Every number is platform-vetted
 * evidence, never invented by the model. Older/cached answers without
 * `sections` fall back to the flat markdown render.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "@/components/ui/button";
import { DataConfidence } from "@/components/data-confidence";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import { ApiError } from "@/lib/api";
import { BETA_LIMIT_MESSAGE, isBillingEnabled } from "@/lib/billing-flag";
import { track } from "@/lib/analytics";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { useSessionState } from "@/lib/use-session-state";
import {
  type CopilotAnswer,
  type CopilotEvidence,
  type CopilotSection,
  type PortfolioRow,
  useCopilotAsk,
  useMyPortfolios,
} from "@/lib/queries";

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
  reference: "border-border bg-muted text-muted-foreground",
  glossary: "border-border bg-muted text-muted-foreground",
};

// Friendly names for the deterministic tools behind evidence rows — user
// language, not API internals.
const TOOL_LABEL: Record<string, string> = {
  portfolio_score: "Portfolio health engine",
  factpack: "Stock fact pack",
  macro_regime: "Market regime feed",
  glossary: "Metric glossary",
  options_exposure: "Options exposure engine",
  risk_reference: "Risk reference bands",
  score_change: "Score-change attribution",
  ticker_exposure: "Your-book exposure",
  optimizer: "Portfolio scans",
  simulation: "What-if simulation",
  user_preferences: "Your confirmed preferences",
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
  const pathname = usePathname();
  // Persist the last answer so switching screens/tabs and returning restores it
  // instead of an empty card (the mutation result itself is lost on unmount).
  // Keyed PER-PORTFOLIO — the answer folds in the active book, so switching
  // portfolios must not surface the prior book's answer.
  const { activePortfolioId, current } = usePortfolioContext();
  const [savedAnswer, setSavedAnswer] = useSessionState<CopilotAnswer | null>(
    `mm:copilot:ask:answer:${activePortfolioId ?? "none"}`,
    null,
  );
  // Clear the live mutation result on a portfolio switch — otherwise `ask.data`
  // (the prior book's answer) would win over the freshly-reset savedAnswer.
  useEffect(() => {
    ask.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePortfolioId]);
  const answer = ask.data ?? savedAnswer;
  // Default English on the first render and switch post-mount when the
  // browser locale is Chinese (SSR-safe: never touch `navigator` in render).
  const [zh, setZh] = useState(false);
  useEffect(() => {
    setZh(navigator.language?.toLowerCase().startsWith("zh") ?? false);
  }, []);

  // Portfolio-aware example: fold the user's largest holding into a chip so
  // the samples speak about THEIR book (ticker never leaves the device except
  // as the question they explicitly send).
  const portfolios = useMyPortfolios();
  const topTicker = topHoldingTicker(portfolios.data?.portfolios);
  const quickPrompts = [
    ...(topTicker
      ? [zh ? `${topTicker} 在我的组合里占多少风险？` : `How much of my book is ${topTicker}?`]
      : []),
    ...(zh ? QUICK_PROMPTS_ZH : QUICK_PROMPTS),
  ];

  function run(q: string) {
    const text = q.trim();
    if (!text || ask.isPending) return;
    setMessage(text);
    ask.mutate(
      { message: text, route: pathname ?? undefined },
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
        {current?.name && (
          <p className="text-xs text-muted-foreground">
            Analyzing <span className="font-medium text-foreground">{current.name}</span> — switch
            your active portfolio to ask about another book.
          </p>
        )}
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

function topHoldingTicker(portfolios: PortfolioRow[] | undefined): string | null {
  const active = portfolios?.find((p) => p.is_default) ?? portfolios?.[0] ?? null;
  if (!active?.holdings) return null;
  let best: string | null = null;
  let bestShares = 0;
  for (const [ticker, h] of Object.entries(active.holdings)) {
    const shares = Number((h as { shares?: number })?.shares ?? 0);
    const assetType = String((h as { asset_type?: string })?.asset_type ?? "");
    if (assetType === "option" || assetType === "cash") continue;
    if (shares > bestShares && /^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)) {
      best = ticker;
      bestShares = shares;
    }
  }
  return best;
}

function AnswerCard({ answer }: { answer: CopilotAnswer }) {
  const sections = answer.sections ?? [];
  const directionalBlocked =
    answer.data_confidence != null && answer.data_confidence.directional_allowed === false;
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
          <span className="text-[10px] text-muted-foreground">data-driven answer</span>
        )}
      </div>

      {directionalBlocked && (
        <div
          role="status"
          className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-muted-foreground"
        >
          Not enough verified data for a directional answer — the sections below
          show what is known and what&apos;s missing.
        </div>
      )}

      {sections.length > 0 ? (
        <div className="space-y-3">
          {sections.map((s) => (
            <AnswerSection key={s.key} section={s} answer={answer} />
          ))}
          {answer.disclaimer && (
            <p className="text-[11px] italic text-muted-foreground">{answer.disclaimer}</p>
          )}
        </div>
      ) : (
        // Pre-sections (cached/legacy) answers keep the original flat render:
        // markdown + confidence + the evidence strip.
        <div className="space-y-4">
          <div className="text-[15px] leading-relaxed">
            <Markdown>{answer.answer_markdown}</Markdown>
          </div>
          <DataConfidence confidence={answer.data_confidence} title="Answer confidence" />
          {answer.evidence.length > 0 && (
            <div className="border-t border-border pt-3">
              <EvidenceSection
                title="Evidence — every number above is one of these vetted facts"
                evidence={answer.evidence}
              />
            </div>
          )}
        </div>
      )}

      <NextActions answer={answer} />
    </div>
  );
}

/**
 * Deterministic next-actions — pure NAVIGATION deep-links derived from the
 * answer's intent/tickers. The Copilot never executes a trade or edits
 * holdings; these only route the user to a workspace that's already prefilled
 * (Analyze tabs, a stress test, or the ticker's research). Kept value-free in
 * analytics (action label only, never the ticker or any content).
 */
function NextActions({ answer }: { answer: CopilotAnswer }) {
  const ticker = answer.tickers[0];
  const actions: { key: string; label: string; href: string }[] = [
    { key: "analyze", label: "Open Analyze", href: "/analyze" },
    { key: "stress", label: "Run a stress test", href: "/analyze?view=stress" },
    ...(ticker
      ? [{ key: "research", label: `Research ${ticker}`, href: `/research?ticker=${encodeURIComponent(ticker)}` }]
      : []),
  ];
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
      <span className="text-[11px] uppercase tracking-wide text-muted-foreground">Next steps</span>
      {actions.map((a) => (
        <Link
          key={a.key}
          href={a.href}
          onClick={() => track("copilot_action_clicked", { action: a.key })}
          className="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
        >
          {a.label}
        </Link>
      ))}
    </div>
  );
}

function AnswerSection({
  section,
  answer,
}: {
  section: CopilotSection;
  answer: CopilotAnswer;
}) {
  if (section.key === "evidence") {
    return <EvidenceSection title={section.title} evidence={answer.evidence} />;
  }
  if (section.key === "data_confidence") {
    return (
      <section aria-label={section.title} className="space-y-2">
        <SectionTitle title={section.title} />
        <div className="text-sm leading-relaxed text-muted-foreground">
          <Markdown>{section.markdown}</Markdown>
        </div>
        <DataConfidence confidence={answer.data_confidence} title="Details" />
      </section>
    );
  }
  if (section.key === "simulation") {
    return (
      <section
        aria-label={section.title}
        className="space-y-1 rounded-lg border border-dashed border-sky-500/50 bg-sky-500/5 p-3"
      >
        <div className="flex items-center gap-2">
          <SectionTitle title={section.title} />
          <span className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-600 dark:text-sky-400">
            what-if · not a market fact
          </span>
        </div>
        <div className="text-sm leading-relaxed">
          <Markdown>{section.markdown}</Markdown>
        </div>
      </section>
    );
  }
  return (
    <section aria-label={section.title} className="space-y-1">
      <div className="flex items-center gap-2">
        <SectionTitle title={section.title} />
        {section.ai_generated && (
          <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
            AI-phrased · numbers verified
          </span>
        )}
      </div>
      <div
        className={
          section.key === "direct_answer"
            ? "text-[15px] font-medium leading-relaxed"
            : "text-sm leading-relaxed"
        }
      >
        <Markdown>{section.markdown}</Markdown>
      </div>
    </section>
  );
}

function SectionTitle({ title }: { title: string }) {
  return (
    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {title}
    </h4>
  );
}

function EvidenceSection({
  title,
  evidence,
}: {
  title: string;
  evidence: CopilotEvidence[];
}) {
  if (!evidence.length) {
    return (
      <section aria-label={title} className="space-y-1">
        <SectionTitle title={title} />
        <p className="text-sm text-muted-foreground">
          No verified data was available for this answer.
        </p>
      </section>
    );
  }
  return (
    <section aria-label={title} className="space-y-2">
      <SectionTitle title={title} />
      <p className="text-xs text-muted-foreground">
        Every number above comes from one of these vetted facts — expand any row
        for its source.
      </p>
      <ul className="space-y-1">
        {evidence.map((e, i) => (
          <EvidenceRow key={`${e.id ?? e.label}-${i}`} item={e} />
        ))}
      </ul>
    </section>
  );
}

function EvidenceRow({ item }: { item: CopilotEvidence }) {
  return (
    <li>
      <details className="group rounded-md border border-border bg-background">
        <summary
          className="flex cursor-pointer list-none flex-wrap items-center gap-1.5 px-2 py-1.5 text-xs [&::-webkit-details-marker]:hidden"
          aria-label={`Evidence: ${item.label}`}
        >
          {item.id && (
            <span className="rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground">
              {item.id}
            </span>
          )}
          <span className="text-muted-foreground">{item.label}:</span>
          <span className="font-medium">{item.value}</span>
          <span
            className={`ml-auto rounded px-1 py-0.5 text-[10px] font-semibold uppercase ${sourceClass(item.source)}`}
          >
            {item.source}
          </span>
        </summary>
        <div className="border-t border-border px-2 py-1.5 text-[11px] text-muted-foreground">
          <span className="font-medium">Computed by:</span>{" "}
          {TOOL_LABEL[item.tool ?? ""] ?? item.tool ?? "platform data"}
          {item.source_type ? ` · ${item.source_type} source` : null}
        </div>
      </details>
    </li>
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
        <p className="mt-1 text-muted-foreground">Upgrade for more Copilot answers.</p>
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
