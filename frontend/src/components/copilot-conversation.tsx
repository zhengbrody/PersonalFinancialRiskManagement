"use client";

/**
 * Shared AI Portfolio Copilot conversation — the reusable chat core.
 *
 * Product philosophy ("Robinhood skin"): the user is a brand-new
 * retail investor who uses margin but has little risk discipline. We
 * NEVER lead with raw numbers or matrices. Each assistant turn opens
 * with the AI's plain-language guidance; the hardcore figures are
 * tucked into a collapsible "The numbers behind this". Latency is
 * masked with a "Thinking…" skeleton bubble so the wait feels alive.
 *
 * This component owns the message list + composer + send logic and is
 * rendered by BOTH the full-page `/copilot` route AND the app-wide
 * floating widget. The `variant` prop tunes spacing/heights so the
 * same conversation feels native in a small bottom-right panel and on
 * the spacious dedicated page. There is NO copy of this logic anywhere
 * else — both surfaces delegate here (DRY).
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Markdown } from "@/components/markdown";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { track } from "@/lib/analytics";
import { ApiError } from "@/lib/api";
import { BETA_LIMIT_MESSAGE, isBillingEnabled } from "@/lib/billing-flag";
import { env } from "@/lib/env";
import { useAuth } from "@/lib/auth-context";

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  agentName?: string;
  grounded?: Record<string, unknown>;
  trades?: unknown[];
  aiGenerated?: boolean;
};

const EXAMPLE_QUESTIONS = [
  "Is my portfolio too risky?",
  "What's my biggest risk right now?",
  "How do I protect against a crash?",
];

// Deterministic follow-up prompts shown after each answer (no LLM call —
// just the natural next questions). Ones already asked are filtered out.
const FOLLOW_UP_QUESTIONS = [
  "What's my single biggest risk right now?",
  "How would a -20% market drop hit me?",
  "Am I being paid for the risk I'm taking?",
  "What would diversify my portfolio the most?",
  "Any hidden fees or tax-loss opportunities?",
];

export type CopilotConversationVariant = "page" | "floating";

/**
 * The reusable chat. `variant="floating"` makes the message list a
 * flex-filling scroll region with a denser empty-state (so it fits the
 * small panel); `variant="page"` keeps the airier full-page rhythm and
 * a sticky composer.
 */
export function CopilotConversation({
  variant = "page",
}: {
  variant?: CopilotConversationVariant;
}) {
  const { accessToken } = useAuth();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const scrollAnchor = useRef<HTMLDivElement>(null);
  // Lets us cancel an in-flight SSE stream — otherwise closing the floating
  // widget (unmount) mid-answer leaks the connection and the server keeps
  // running the (quota-consuming) LLM tool loop with no consumer.
  const abortRef = useRef<AbortController | null>(null);

  const floating = variant === "floating";

  // Keep the newest message in view as the conversation grows / streams.
  useEffect(() => {
    scrollAnchor.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, pending]);

  // Cancel any in-flight stream when the component unmounts.
  useEffect(() => () => abortRef.current?.abort(), []);

  /** Append streamed text to the in-flight assistant bubble (create it on
   * the first delta so the "Thinking…" bubble shows until words arrive). */
  function pushDelta(text: string) {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") {
        copy[copy.length - 1] = { ...last, text: last.text + text };
      } else {
        copy.push({ role: "assistant", text });
      }
      return copy;
    });
  }

  function setAssistantMeta(meta: {
    agent_name?: string;
    grounded_in?: Record<string, unknown>;
    draft_trades?: unknown[];
    ai_generated?: boolean;
  }) {
    setMessages((prev) => {
      const copy = [...prev];
      const last = copy[copy.length - 1];
      if (last && last.role === "assistant") {
        copy[copy.length - 1] = {
          ...last,
          agentName: meta.agent_name,
          grounded: meta.grounded_in,
          trades: meta.draft_trades,
          aiGenerated: meta.ai_generated,
        };
      }
      return copy;
    });
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (trimmed === "" || pending) return;

    track("copilot_message_sent", { variant });
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setDraft("");
    setPending(true);

    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const res = await fetch(`${env.apiBaseUrl}/api/v1/copilot/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({ message: trimmed }),
        signal: ac.signal,
      });
      if (!res.ok || !res.body) {
        throw new ApiError(
          res.status,
          res.status === 401 ? "unauthorized" : "http_error",
          `Request failed (${res.status}).`,
        );
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamErr: { code?: string; message?: string } | null = null;

      // Parse Server-Sent Event frames (separated by a blank line).
      const drain = () => {
        let i;
        while ((i = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, i);
          buffer = buffer.slice(i + 2);
          let event = "message";
          const dataLines: string[] = [];
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
          }
          if (!dataLines.length) continue;
          let data: Record<string, unknown> = {};
          try {
            data = JSON.parse(dataLines.join("\n"));
          } catch {
            continue;
          }
          if (event === "delta" && typeof data.text === "string") {
            pushDelta(data.text);
          } else if (event === "done") {
            setAssistantMeta(data as never);
          } else if (event === "error") {
            streamErr = data as { code?: string; message?: string };
          }
        }
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        drain();
      }
      buffer += decoder.decode();
      drain();

      if (streamErr) {
        // Drop the empty assistant placeholder, surface the friendly error.
        setMessages((prev) =>
          prev[prev.length - 1]?.role === "assistant" && !prev[prev.length - 1]?.text
            ? prev.slice(0, -1)
            : prev,
        );
        const e = streamErr as { code?: string; message?: string };
        setError(new ApiError(0, e.code ?? "unknown", e.message ?? "Something went wrong."));
      }
    } catch (err) {
      // Intentional cancel (unmount / new send) — leave state alone.
      if (err instanceof DOMException && err.name === "AbortError") return;
      setMessages((prev) =>
        prev[prev.length - 1]?.role === "assistant" && !prev[prev.length - 1]?.text
          ? prev.slice(0, -1)
          : prev,
      );
      setError(
        err instanceof ApiError ? err : new ApiError(0, "network_error", String(err)),
      );
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
      setPending(false);
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(draft);
    }
  }

  return (
    <div
      className={
        floating
          ? "flex min-h-0 flex-1 flex-col"
          : "flex flex-col gap-6"
      }
    >
      <div
        className={
          floating
            ? "min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
            : "space-y-4"
        }
      >
        {messages.length === 0 && !pending && (
          <EmptyState onPick={(q) => send(q)} compact={floating} />
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <UserBubble key={i} text={m.text} />
          ) : (
            <AssistantBubble key={i} message={m} />
          ),
        )}

        {pending && messages[messages.length - 1]?.role !== "assistant" && (
          <ThinkingBubble />
        )}

        {!pending &&
          !error &&
          messages.length > 0 &&
          messages[messages.length - 1]?.role === "assistant" && (
            <FollowUpChips
              asked={messages.filter((m) => m.role === "user").map((m) => m.text)}
              onPick={(q) => send(q)}
            />
          )}

        {error && <ErrorNotice error={error} />}

        <div ref={scrollAnchor} />
      </div>

      <div
        className={
          floating
            ? "space-y-2 border-t border-border bg-background/90 p-3 backdrop-blur"
            : "sticky bottom-4 space-y-2 rounded-lg border border-border bg-background/90 p-3 backdrop-blur"
        }
      >
        <Textarea
          data-testid="copilot-input"
          aria-label="Ask your Portfolio Copilot"
          placeholder="Ask your Copilot… (Enter to send, Shift+Enter for a new line)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          disabled={pending}
        />
        <div className="flex justify-end">
          <Button
            type="button"
            data-testid="copilot-send"
            size={floating ? "sm" : "default"}
            onClick={() => send(draft)}
            disabled={pending || draft.trim() === ""}
          >
            {pending ? "Thinking…" : "Ask"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary/10 px-4 py-3 text-[15px] leading-relaxed text-foreground">
        {text}
      </div>
    </div>
  );
}

function AssistantBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-3 rounded-2xl rounded-bl-sm border border-border bg-card px-4 py-3 text-[15px]">
        {message.agentName && (
          <p className="text-[10px] font-medium uppercase tracking-widest text-primary">
            {message.agentName}
          </p>
        )}
        <Markdown>{message.text}</Markdown>

        {message.trades && message.trades.length > 0 && (
          <DraftTrades trades={message.trades} />
        )}

        {message.grounded && Object.keys(message.grounded).length > 0 && (
          <NumbersBehindThis grounded={message.grounded} />
        )}

        {message.aiGenerated !== undefined && (
          <p className="text-[10px] text-muted-foreground">
            {message.aiGenerated
              ? "AI-generated · educational, not financial advice"
              : "Deterministic summary (AI unavailable) · educational, not financial advice"}
          </p>
        )}
      </div>
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-2 rounded-2xl rounded-bl-sm border border-border bg-card px-4 py-3">
        <p className="text-xs text-muted-foreground">Thinking…</p>
        <Skeleton className="h-3 w-48" />
        <Skeleton className="h-3 w-64" />
        <Skeleton className="h-3 w-40" />
      </div>
    </div>
  );
}

/**
 * The collapsible escape hatch for users who DO want the figures.
 * Native <details> so it's keyboard-accessible and needs no JS state.
 * Collapsed by default — guidance leads, numbers follow.
 */
function NumbersBehindThis({
  grounded,
}: {
  grounded: Record<string, unknown>;
}) {
  const facts = Object.entries(grounded)
    .map(([key, value]) => formatFact(key, value))
    .filter((f): f is GroundedFact => f !== null);

  if (facts.length === 0) return null;

  return (
    <details className="group rounded-md border border-border bg-muted/30">
      <summary className="cursor-pointer list-none px-3 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground">
        <span className="inline-block transition group-open:rotate-90">›</span>{" "}
        The numbers behind this
      </summary>
      <dl className="space-y-1 px-3 pb-3 text-xs">
        {facts.map((f) => (
          <div
            key={f.key}
            className="flex items-baseline justify-between gap-3 border-b border-border/40 py-1 last:border-b-0"
          >
            <dt className="text-muted-foreground">{f.label}</dt>
            <dd className="font-mono text-foreground">{f.display}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}

function DraftTrades({ trades }: { trades: unknown[] }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-3">
      <p className="mb-2 text-xs font-medium text-foreground">
        Suggested adjustments
      </p>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {trades.map((t, i) => (
          <li key={i} className="font-mono">
            {describeTrade(t)}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] text-muted-foreground">
        Ideas to consider — not financial advice, and nothing is executed.
      </p>
    </div>
  );
}

function FollowUpChips({
  asked,
  onPick,
}: {
  asked: string[];
  onPick: (q: string) => void;
}) {
  const askedSet = new Set(asked.map((q) => q.trim().toLowerCase()));
  const suggestions = FOLLOW_UP_QUESTIONS.filter(
    (q) => !askedSet.has(q.trim().toLowerCase()),
  ).slice(0, 3);
  if (suggestions.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {suggestions.map((q) => (
        <Button
          key={q}
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPick(q)}
        >
          {q}
        </Button>
      ))}
    </div>
  );
}

function EmptyState({
  onPick,
  compact,
}: {
  onPick: (q: string) => void;
  compact?: boolean;
}) {
  if (compact) {
    // Dense variant for the small floating panel: no Card chrome, just
    // a one-line nudge + the tappable example questions.
    return (
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">
          New to investing? Tap a question to get started — answers come in
          plain English.
        </p>
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((q) => (
            <Button
              key={q}
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onPick(q)}
            >
              {q}
            </Button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Say hello to your Copilot</CardTitle>
        <CardDescription>
          New to investing? Start with one of these — your Copilot answers in
          plain English, no jargon required.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-2">
        {EXAMPLE_QUESTIONS.map((q) => (
          <Button
            key={q}
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onPick(q)}
          >
            {q}
          </Button>
        ))}
      </CardContent>
    </Card>
  );
}

/**
 * Map the structured API error codes to gentle, actionable copy.
 * Beginners shouldn't see "422 no_active_portfolio" — they should see a
 * sentence and a button.
 */
function ErrorNotice({ error }: { error: ApiError }) {
  if (error.code === "no_active_portfolio") {
    return (
      <NoticeCard
        title="Let's set up your portfolio first"
        body="Your Copilot needs to know what you're holding before it can help."
      >
        <Link href="/portfolios/new">
          <Button variant="outline" size="sm">
            Create a portfolio
          </Button>
        </Link>
      </NoticeCard>
    );
  }

  if (error.code === "quota_exceeded") {
    if (!isBillingEnabled()) {
      return <NoticeCard title="Usage limit reached" body={BETA_LIMIT_MESSAGE} />;
    }
    return (
      <NoticeCard
        title="You've used your chat quota this month"
        body="Upgrade your plan to keep chatting with your Copilot."
      >
        <Link href="/pricing">
          <Button variant="outline" size="sm">
            See plans
          </Button>
        </Link>
      </NoticeCard>
    );
  }

  if (error.code === "unauthorized") {
    return (
      <NoticeCard
        title="Please sign in again"
        body="Your session expired. Sign back in to keep chatting."
      >
        <Link href="/login">
          <Button variant="outline" size="sm">
            Sign in
          </Button>
        </Link>
      </NoticeCard>
    );
  }

  return (
    <NoticeCard
      title="Something went wrong"
      body={
        error.code === "network_error"
          ? "Couldn't reach the Copilot. Check your connection and try again."
          : "Your Copilot hit a snag. Please try again in a moment."
      }
    />
  );
}

function NoticeCard({
  title,
  body,
  children,
}: {
  title: string;
  body: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="space-y-2 rounded-2xl border border-border bg-card px-4 py-3 text-sm">
      <p className="font-medium text-foreground">{title}</p>
      <p className="text-muted-foreground">{body}</p>
      {children}
    </div>
  );
}

// ── grounded-fact formatting ───────────────────────────────────────

type GroundedFact = { key: string; label: string; display: string };

/**
 * Human labels + sensible formatting for the numeric keys the backend
 * grounds responses in. Rate-like metrics render as %, the health
 * score as `/1000`, dollar figures as USD. Unknown keys fall back to a
 * title-cased label so new backend keys still render gracefully.
 */
const FACT_LABELS: Record<string, string> = {
  overall_score: "Health score",
  sharpe_ratio: "Risk-adjusted return (Sharpe)",
  annual_volatility: "Volatility",
  annual_return: "Expected annual return",
  max_drawdown: "Worst historical drop",
  var_95_daily: "Daily risk (VaR 95%)",
  var_95: "Daily risk (VaR 95%)",
  beta_to_benchmark: "Market sensitivity (beta)",
  total_value: "Total value",
};

const PERCENT_KEYS = new Set([
  "annual_volatility",
  "annual_return",
  "max_drawdown",
  "var_95_daily",
  "var_95",
  "cvar_95_daily",
  "cvar_95",
]);

const USD_KEYS = new Set(["total_value"]);

function formatFact(key: string, value: unknown): GroundedFact | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  const label = FACT_LABELS[key] ?? titleCase(key);

  let display: string;
  if (key === "overall_score") {
    display = `${Math.round(value)} / 1000`;
  } else if (PERCENT_KEYS.has(key)) {
    display = `${(value * 100).toFixed(1)}%`;
  } else if (USD_KEYS.has(key)) {
    display = `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  } else {
    display = value.toFixed(2);
  }
  return { key, label, display };
}

function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function describeTrade(trade: unknown): string {
  if (trade && typeof trade === "object") {
    const t = trade as Record<string, unknown>;
    const action = typeof t.action === "string" ? t.action : undefined;
    const ticker =
      typeof t.ticker === "string"
        ? t.ticker
        : typeof t.symbol === "string"
          ? t.symbol
          : undefined;
    if (action || ticker) {
      return [action?.toUpperCase(), ticker].filter(Boolean).join(" ");
    }
  }
  return JSON.stringify(trade);
}
