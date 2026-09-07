"use client";

/** One input and one timeline for questions and foreground risk checks. */
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { CopilotAnswerCard } from "@/components/copilot-answer";
import { CopilotRiskCheck } from "@/components/copilot-risk-check";
import { CopilotChangeForm, CopilotChangeResult } from "@/components/copilot-change";
import { useAuth } from "@/lib/auth-context";
import { usePortfolioContext } from "@/lib/portfolio-context";
import { useCopilotThread } from "@/lib/use-copilot-thread";

export type CopilotConversationVariant = "page" | "floating";

export function CopilotConversation({
  variant = "page",
  initialQuestion,
}: {
  variant?: CopilotConversationVariant;
  initialQuestion?: string;
}) {
  const { user, accessToken } = useAuth();
  const { activePortfolioId, current, switchingId, isLoading } =
    usePortfolioContext();
  const scope = `mm:copilot:thread:v1:${user?.id ?? "anonymous"}:${activePortfolioId ?? "none"}`;
  // Remount before painting a changed identity; page and floating use one partition.
  return (
    <Conversation
      key={scope}
      scope={scope}
      token={accessToken}
      portfolioId={activePortfolioId}
      portfolioName={current?.name ?? null}
      switching={!!switchingId || isLoading}
      variant={variant}
      initialQuestion={initialQuestion}
    />
  );
}

function Conversation({
  scope,
  token,
  portfolioId,
  portfolioName,
  switching,
  variant,
  initialQuestion,
}: {
  scope: string;
  token: string | null;
  portfolioId: string | null;
  portfolioName: string | null;
  switching: boolean;
  variant: CopilotConversationVariant;
  initialQuestion?: string;
}) {
  const thread = useCopilotThread(scope, portfolioId, token);
  const [draft, setDraft] = useState(initialQuestion ?? "");
  const [newResult, setNewResult] = useState(false);
  const anchor = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const input = useRef<HTMLTextAreaElement>(null);
  const previousPrefill = useRef(initialQuestion);
  const floating = variant === "floating";
  const disabled = thread.pending || !thread.ready || switching;

  useEffect(() => {
    if (initialQuestion !== previousPrefill.current) {
      previousPrefill.current = initialQuestion;
      if (initialQuestion) setDraft(initialQuestion);
    }
  }, [initialQuestion]);

  useEffect(() => {
    const element = anchor.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      nearBottom.current = entry.isIntersecting;
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!thread.turns.length) return;
    if (nearBottom.current && !document.activeElement?.closest("form")) {
      anchor.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
    } else if (!thread.pending) setNewResult(true);
  }, [thread.turns, thread.pending]);

  function send(text: string) {
    if (disabled || !text.trim() || text.trim().length > 2000) return;
    setDraft("");
    setNewResult(false);
    void thread.send(text);
  }

  return (
    <div
      className={
        floating
          ? "flex min-h-0 flex-1 flex-col"
          : "flex min-w-0 flex-col gap-4"
      }
    >
      <p className="px-3 py-2 text-xs text-muted-foreground">
        {portfolioName
          ? `Working with ${portfolioName}`
          : "Select a portfolio to run an account risk check"}{" "}
        · no changes to holdings
      </p>
      <div
        className={
          floating
            ? "min-h-0 flex-1 space-y-4 overflow-y-auto p-3"
            : "min-w-0 space-y-4"
        }
      >
        {!thread.turns.length && (
          <div className="space-y-3 rounded-2xl border border-border bg-card p-4">
            <h2 className="text-lg font-semibold">
              What would you like to understand?
            </h2>
            <p className="text-sm text-muted-foreground">
              Check what could hurt your portfolio. Explore the evidence here,
              without switching pages.
            </p>
            <div className="flex flex-wrap gap-2">
              {[
                "Check my portfolio",
                "Test a change",
                "Explain expected shortfall",
                "What if the market drops 20%?",
              ].map((q) => (
                <Button
                  key={q}
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={disabled}
                  onClick={() => send(q)}
                >
                  {q}
                </Button>
              ))}
            </div>
          </div>
        )}
        {thread.turns.map((turn) => (
          <div key={turn.id} className="min-w-0 space-y-3">
            <div className="ml-auto w-fit max-w-[90%] whitespace-pre-wrap break-words rounded-2xl bg-primary/10 px-4 py-3 text-sm">
              {turn.question}
            </div>
            {turn.kind === "change" && ["needs_input", "interrupted"].includes(turn.status) && turn.change && (
              <>
                {turn.error && <p role="alert" className="rounded-lg border border-border p-3 text-sm">{turn.error}</p>}
                <CopilotChangeForm draft={turn.change} disabled={disabled || !portfolioId}
                  onChange={(draft) => thread.editChange(turn.id, draft)}
                  onSubmit={() => thread.compare({ ...turn, status: "needs_input" })} />
              </>
            )}
            {turn.status === "completed" && turn.comparison && (
              <CopilotChangeResult result={turn.comparison} disabled={disabled}
                onRevise={() => thread.openChange(turn.change)} onVerify={() => thread.verifyComparison(turn)}
                onSave={() => thread.saveComparison(turn)} onRetrieveSaved={() => thread.saveComparison(turn, true)}
                saved={turn.saved} savedNeedsCheck={turn.savedNeedsCheck} savePending={turn.savePending} saveError={turn.saveError}
                receiptEvicted={turn.receiptEvicted}
                verification={turn.verification} verificationPending={turn.verificationPending} verificationError={turn.verificationError} />
            )}
            {turn.status === "running" && (
              <div
                role="status"
                className="rounded-xl border border-border p-4 text-sm"
              >
                {turn.activity === "retrieve"
                  ? "Retrieving the saved check…"
                  : turn.activity === "cancel"
                    ? "Requesting server cancellation…"
                    : turn.kind === "change"
                      ? "Comparing unchanged and proposed holdings on the same closing-price data…"
                    : turn.kind === "check"
                  ? "Running the risk engine against your selected portfolio…"
                  : "Gathering evidence and preparing your answer…"}
                <p className="mt-1 text-xs text-muted-foreground">
                  {turn.activity
                    ? "Checking the original run. No new analysis is being started."
                    : turn.kind === "check"
                    ? "Fetching inputs and calculating the existing risk report. Cold data can take longer."
                    : "Numbers must come from platform evidence."}
                </p>
              </div>
            )}
            {turn.status === "completed" && turn.check && (
              <CopilotRiskCheck
                result={turn.check}
                disabled={disabled}
                onRepeat={() => send("Check my portfolio")}
              />
            )}
            {turn.status === "completed" && turn.answer && (
              <CopilotAnswerCard answer={turn.answer} />
            )}
            {turn.kind !== "change" && ["failed", "cancelled", "interrupted"].includes(turn.status) && (
              <div
                role="status"
                className="space-y-2 rounded-xl border border-border p-3 text-sm"
              >
                <p>
                  {turn.error ??
                    (turn.status === "cancelled"
                      ? "Stopped waiting. No result was added. Server computation may finish in the background."
                      : "This request was interrupted. It was not automatically restarted.")}
                </p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={disabled}
                  onClick={() => send(turn.question)}
                >
                  Try again
                </Button>
                {turn.runId && (
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" variant="outline" disabled={disabled}
                      onClick={() => thread.retrieve(turn)}>
                      Retrieve saved result
                    </Button>
                    {turn.status === "interrupted" && (
                      <Button type="button" size="sm" variant="ghost" disabled={disabled}
                        onClick={() => thread.cancelRun(turn)}>
                        Cancel server check
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        <div ref={anchor} />
      </div>
      {thread.turns.length > 0 && (
        <div className="px-3"><Button type="button" variant="outline" size="sm" disabled={disabled || !portfolioId}
          onClick={() => thread.openChange()}>Test a change</Button></div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
        className={
          floating
            ? "space-y-2 border-t border-border bg-background p-3"
            : "sticky bottom-[calc(5rem+env(safe-area-inset-bottom))] z-20 space-y-2 rounded-xl border border-border bg-background/95 p-3 backdrop-blur lg:bottom-4"
        }
      >
        {newResult && (
          <button
            type="button"
            className="text-xs text-primary"
            onClick={() => {
              anchor.current?.scrollIntoView?.({ behavior: "smooth" });
              setNewResult(false);
            }}
          >
            View latest result
          </button>
        )}
        <Textarea
          ref={input}
          data-testid="copilot-input"
          aria-label="Ask your Portfolio Copilot"
          placeholder="Ask a question or say ‘Check my portfolio’…"
          value={draft}
          maxLength={2000}
          rows={2}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              send(draft);
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            Analysis only · review assumptions before deciding
          </span>
          {thread.pending ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={thread.stop}
            >
              Stop waiting
            </Button>
          ) : (
            <Button
              data-testid="copilot-send"
              type="submit"
              size="sm"
              disabled={disabled || !draft.trim()}
            >
              Ask
            </Button>
          )}
        </div>
      </form>
    </div>
  );
}
