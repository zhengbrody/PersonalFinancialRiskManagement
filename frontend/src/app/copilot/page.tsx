"use client";

/**
 * AI Portfolio Copilot — a calm, beginner-friendly chat.
 *
 * Product philosophy ("Robinhood skin"): the user is a brand-new
 * retail investor who uses margin but has little risk discipline. We
 * NEVER lead with raw numbers or matrices. Each assistant turn opens
 * with the AI's plain-language guidance; the hardcore figures are
 * tucked into a collapsible "The numbers behind this". Latency is
 * masked with a "Thinking…" skeleton bubble so the wait feels alive.
 *
 * Auth: same client-side gate as /portfolios — skeleton while the
 * Supabase session probes, redirect to /login when signed out.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useBillingMe, useCopilotChat } from "@/lib/queries";

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  agentName?: string;
  grounded?: Record<string, unknown>;
  trades?: unknown[];
};

const EXAMPLE_QUESTIONS = [
  "Is my portfolio too risky?",
  "What's my biggest risk right now?",
  "How do I protect against a crash?",
];

export default function CopilotPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const billing = useBillingMe();
  const chat = useCopilotChat();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const scrollAnchor = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, configured, router]);

  // Keep the newest message in view as the conversation grows.
  useEffect(() => {
    scrollAnchor.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages.length, chat.isPending]);

  if (!configured) {
    return <ConfigureSupabaseNotice />;
  }

  if (authLoading || !user) {
    return <PageSkeleton />;
  }

  function send(text: string) {
    const trimmed = text.trim();
    if (trimmed === "" || chat.isPending) return;

    setError(null);
    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setDraft("");

    chat.mutate(
      { message: trimmed },
      {
        onSuccess: (data) => {
          setMessages((prev) => [
            ...prev,
            {
              role: "assistant",
              text: data.response_markdown,
              agentName: data.agent_name,
              grounded: data.grounded_in,
              trades: data.draft_trades,
            },
          ]);
        },
        onError: (err) => {
          setError(
            err instanceof ApiError ? err : new ApiError(0, "unknown", String(err)),
          );
        },
      },
    );
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends; Shift+Enter inserts a newline.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(draft);
    }
  }

  const planLabel = billing.data?.plan;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-tight">
            Portfolio Copilot
          </h1>
          {planLabel && (
            <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {planLabel}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Ask anything about your portfolio in plain English. Your Copilot
          explains the risk first — the hard numbers are always one tap away.
        </p>
      </header>

      <div className="space-y-4">
        {messages.length === 0 && !chat.isPending && (
          <EmptyState onPick={(q) => send(q)} />
        )}

        {messages.map((m, i) =>
          m.role === "user" ? (
            <UserBubble key={i} text={m.text} />
          ) : (
            <AssistantBubble key={i} message={m} />
          ),
        )}

        {chat.isPending && <ThinkingBubble />}

        {error && <ErrorNotice error={error} />}

        <div ref={scrollAnchor} />
      </div>

      <div className="sticky bottom-4 space-y-2 rounded-lg border border-border bg-background/90 p-3 backdrop-blur">
        <Textarea
          aria-label="Ask your Portfolio Copilot"
          placeholder="Ask your Copilot… (Enter to send, Shift+Enter for a new line)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          disabled={chat.isPending}
        />
        <div className="flex justify-end">
          <Button
            type="button"
            onClick={() => send(draft)}
            disabled={chat.isPending || draft.trim() === ""}
          >
            {chat.isPending ? "Thinking…" : "Ask"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-primary/10 px-4 py-3 text-sm text-foreground">
        {text}
      </div>
    </div>
  );
}

function AssistantBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[90%] space-y-3 rounded-2xl rounded-bl-sm border border-border bg-card px-4 py-3 text-sm">
        {message.agentName && (
          <p className="text-[10px] font-medium uppercase tracking-widest text-primary">
            {message.agentName}
          </p>
        )}
        <p className="whitespace-pre-wrap leading-relaxed text-foreground">
          {message.text}
        </p>

        {message.trades && message.trades.length > 0 && (
          <DraftTrades trades={message.trades} />
        )}

        {message.grounded && Object.keys(message.grounded).length > 0 && (
          <NumbersBehindThis grounded={message.grounded} />
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

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
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

function ConfigureSupabaseNotice() {
  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Supabase not configured</CardTitle>
        <CardDescription>
          The Copilot needs an authenticated Supabase session.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Set <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code className="font-mono">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in{" "}
          <code className="font-mono">.env.local</code>, then restart the dev
          server.
        </p>
        <Link href="/score">
          <Button variant="outline">Try the public /score demo</Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-16 w-full" />
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
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
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
