"use client";

/** User/book timeline with optional saved-run recovery; chat stays session-local. */
import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";
import { apiFetch, ApiError } from "./api";
import { copilotAnswerSchema, type CopilotAnswer } from "./queries";
import {
  isRiskCheckRequest,
  riskCheckSchema,
  type RiskCheck,
} from "./risk-check";
import { readSession, writeSession } from "./use-session-state";
import { loadSavedRun, savedRunsEnabled, type SavedRun } from "./copilot-runs";
import { changeComparisonSchema, changeDraftSchema, emptyChange, isChangeRequest, type ChangeDraft } from "./copilot-compare";

const turnSchema = z.object({
  id: z.string(),
  question: z.string(),
  status: z.enum([
    "running",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "needs_input",
  ]),
  kind: z.enum(["check", "answer", "change"]),
  change: changeDraftSchema.optional(),
  comparison: changeComparisonSchema.optional(),
  runId: z.string().uuid().optional(),
  activity: z.enum(["retrieve", "cancel"]).optional(),
  answer: copilotAnswerSchema.optional(),
  check: riskCheckSchema.optional(),
  error: z.string().optional(),
});
export type CopilotTurn = z.infer<typeof turnSchema>;

function restore(key: string): CopilotTurn[] {
  const parsed = z.array(turnSchema).safeParse(readSession<unknown>(key));
  if (!parsed.success) return [];
  return parsed.data.map((turn) =>
    turn.status === "running" ? { ...turn, status: "interrupted" } : turn,
  );
}

export function useCopilotThread(
  key: string,
  portfolioId: string | null,
  token: string | null,
) {
  const [turns, setTurns] = useState<CopilotTurn[]>([]);
  const [ready, setReady] = useState(false);
  const active = useRef<AbortController | null>(null);
  const alive = useRef(true);
  const turnsRef = useRef<CopilotTurn[]>([]);

  const commit = useCallback(
    (next: CopilotTurn[]) => {
      const retained = next.slice(-30);
      turnsRef.current = retained;
      setTurns(retained);
      writeSession(key, retained);
    },
    [key],
  );

  useEffect(() => {
    alive.current = true;
    const stored = restore(key);
    turnsRef.current = stored;
    setTurns(stored);
    setReady(true);
    return () => {
      alive.current = false;
      active.current?.abort();
    };
  }, [key]);

  function patch(id: string, fields: Partial<CopilotTurn>) {
    if (!alive.current) return;
    commit(
      turnsRef.current.map((t) => (t.id === id ? { ...t, ...fields } : t)),
    );
  }

  function acceptRun(id: string, run: SavedRun) {
    patch(id, {
      status: run.state === "running" ? "interrupted" : run.state,
      check: run.result ?? undefined,
      activity: undefined,
      error: run.state === "cancelled"
        ? "Check cancelled. Any computation already running may finish, but its result will not be published."
        : run.state === "failed"
          ? "The server could not complete this check. Start a new check when inputs are available."
          : run.state === "interrupted"
            ? "This server run expired. It was not restarted. You can start a new check."
            : undefined,
    });
  }

  async function recover(turn: CopilotTurn, operation: "retrieve" | "cancel") {
    if (!turn.runId || !portfolioId || active.current || !ready) return;
    const ac = new AbortController();
    active.current = ac;
    patch(turn.id, { status: "running", error: undefined, activity: operation });
    const timeout = setTimeout(() => ac.abort("timeout"), 120_000);
    try {
      const run = await loadSavedRun(turn.runId, portfolioId, token, ac.signal, operation);
      if (!ac.signal.aborted) acceptRun(turn.id, run);
    } catch (error) {
      if (!ac.signal.aborted) patch(turn.id, {
        status: "interrupted",
        error: operation === "cancel"
          ? "Cancellation was not confirmed. Retrieve the saved result to check its state."
          : error instanceof ApiError ? error.message : "Could not retrieve this check. No new analysis was started.",
      });
    } finally {
      clearTimeout(timeout);
      if (ac.signal.aborted) patch(turn.id, {
        status: "interrupted",
        error: "Stopped waiting. Retrieve the saved result to check the server's state.",
      });
      if (active.current === ac) active.current = null;
    }
  }

  async function send(question: string) {
    const text = question.trim();
    if (!text || text.length > 2000 || active.current || !ready) return;
    if (isChangeRequest(text)) { openChange(); return; }
    const kind = isRiskCheckRequest(text) ? "check" : "answer";
    const id = crypto.randomUUID();
    const durable = kind === "check" && savedRunsEnabled() && !!portfolioId;
    const ac = new AbortController();
    active.current = ac;
    commit([
      ...turnsRef.current,
      { id, question: text, kind, status: "running", ...(durable ? { runId: id } : {}) },
    ]);
    const timeout = setTimeout(() => ac.abort("timeout"), 120_000);
    try {
      if (kind === "check") {
        if (!portfolioId)
          throw new ApiError(
            422,
            "no_active_portfolio",
            "Select a portfolio with holdings before running a risk check.",
          );
        if (durable) {
          const run = await loadSavedRun(id, portfolioId, token, ac.signal, "start");
          if (!ac.signal.aborted) acceptRun(id, run);
          return;
        }
        const report = await apiFetch<{ copilot_check: RiskCheck }>(
          "/api/v1/risk/report_from_active",
          {
            method: "POST",
            authToken: token ?? undefined,
            signal: ac.signal,
            body: {
              expected_portfolio_id: portfolioId,
              include_copilot_check: true,
            },
            schema: z.object({ copilot_check: riskCheckSchema }),
          },
        );
        if (report.copilot_check.portfolio_id !== portfolioId)
          throw new ApiError(
            409,
            "portfolio_changed",
            "The result belongs to another portfolio. Please run a fresh check.",
          );
        if (!ac.signal.aborted)
          patch(id, { status: "completed", check: report.copilot_check });
      } else {
        const answer = await apiFetch<CopilotAnswer>("/api/v1/copilot/ask", {
          method: "POST",
          authToken: token ?? undefined,
          signal: ac.signal,
          body: {
            message: text,
            route: "/copilot",
            expected_portfolio_id: portfolioId,
          },
          schema: copilotAnswerSchema,
        });
        if (!ac.signal.aborted) patch(id, { status: "completed", answer });
      }
    } catch (error) {
      if (!ac.signal.aborted) {
        const notStarted = durable && error instanceof ApiError && [
          "no_active_portfolio", "portfolio_changed", "analysis_busy",
          "runs_unavailable", "invalid_run_inputs", "run_too_large",
        ].includes(error.code);
        patch(id, {
          status: durable && !notStarted ? "interrupted" : "failed",
          ...(notStarted ? { runId: undefined } : {}),
          error:
            error instanceof ApiError
              ? error.message
              : durable ? "Connection interrupted. Retrieve the saved result before starting another check." : "The request failed. Please try again.",
        });
      }
    } finally {
      clearTimeout(timeout);
      if (ac.signal.aborted)
        patch(id, {
          status: durable || ac.signal.reason === "timeout" ? "interrupted" : "cancelled",
          error:
            durable
              ? "Stopped waiting. Retrieve the saved result or cancel the server run below."
              : ac.signal.reason === "timeout"
              ? "This request took too long. No completed result was received."
              : undefined,
        });
      if (active.current === ac) active.current = null;
    }
  }

  function openChange(change: ChangeDraft = emptyChange) {
    if (active.current || !ready) return;
    commit([...turnsRef.current, { id: crypto.randomUUID(), question: "Test a change", kind: "change", status: "needs_input", change: { ...change } }]);
  }

  async function compare(turn: CopilotTurn) {
    if (active.current || !ready || !portfolioId || !turn.change || turn.status !== "needs_input") return;
    const { ticker, amount, proceeds } = turn.change;
    if (!/^[A-Z][A-Z0-9.\-]{0,11}$/.test(ticker) || !/^\d+(\.\d{1,2})?$/.test(amount) || Number(amount) <= 0) {
      patch(turn.id, { error: "Enter a held ticker and a positive dollar amount with at most two decimal places." });
      return;
    }
    const ac = new AbortController();
    active.current = ac;
    patch(turn.id, { status: "running", error: undefined });
    const timeout = setTimeout(() => ac.abort("timeout"), 120_000);
    try {
      const comparison = await apiFetch("/api/v1/copilot/compare-change", {
        method: "POST", authToken: token ?? undefined, signal: ac.signal,
        body: { expected_portfolio_id: portfolioId, ticker, amount: Number(amount), proceeds }, schema: changeComparisonSchema,
      });
      if (comparison.portfolio_id !== portfolioId || comparison.assumptions.expected_portfolio_id !== portfolioId || comparison.assumptions.ticker !== ticker || comparison.assumptions.amount !== Number(amount) || comparison.assumptions.proceeds !== proceeds)
        throw new ApiError(409, "comparison_mismatch", "The comparison does not match this portfolio and assumption. Please try again.");
      if (!ac.signal.aborted) patch(turn.id, { status: "completed", comparison });
    } catch (error) {
      if (!ac.signal.aborted) patch(turn.id, { status: "needs_input", error: error instanceof ApiError ? error.message : "Comparison failed. No holdings changed. Try again when data is available." });
    } finally {
      clearTimeout(timeout);
      if (ac.signal.aborted) patch(turn.id, { status: "needs_input", error: "Stopped waiting. No result was accepted. Submit again to calculate a fresh comparison." });
      if (active.current === ac) active.current = null;
    }
  }

  return {
    turns,
    ready,
    pending: turns.some((t) => t.status === "running"),
    send,
    openChange,
    compare,
    editChange: (id: string, change: ChangeDraft) => { if (!active.current) patch(id, { change, error: undefined }); },
    retrieve: (turn: CopilotTurn) => recover(turn, "retrieve"),
    cancelRun: (turn: CopilotTurn) => recover(turn, "cancel"),
    stop: () => active.current?.abort(),
  };
}
