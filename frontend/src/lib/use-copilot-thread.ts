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
import { changeComparisonSchema, changeDraftSchema, emptyChange, isChangeRequest, comparisonVerificationSchema, comparisonVerificationSummarySchema, savedComparisonSchema, savedComparisonSummarySchema, type ChangeDraft } from "./copilot-compare";

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
  verification: comparisonVerificationSummarySchema.optional(),
  verificationPending: z.boolean().optional(),
  verificationError: z.string().optional(),
  saved: savedComparisonSummarySchema.optional(),
  savePending: z.boolean().optional(),
  saveError: z.string().optional(),
  savedNeedsCheck: z.boolean().optional(),
  runId: z.string().uuid().optional(),
  activity: z.enum(["retrieve", "cancel"]).optional(),
  answer: copilotAnswerSchema.optional(),
  check: riskCheckSchema.optional(),
  error: z.string().optional(),
  // Set when this tab dropped the turn's signed receipt to bound local storage.
  receiptEvicted: z.boolean().optional(),
});
export type CopilotTurn = z.infer<typeof turnSchema>;

function restore(key: string): CopilotTurn[] {
  const stored = readSession<unknown>(key);
  // Parse per item: a schema change that invalidates ONE turn must not discard
  // the rest of the thread, which may hold the only local pointer to a saved
  // draft plan. Unknown/blank shapes simply yield an empty thread.
  const kept = Array.isArray(stored)
    ? stored.flatMap((item) => { const r = turnSchema.safeParse(item); return r.success ? [r.data] : []; })
    : [];
  return kept.map((turn) => ({ ...turn,
    status: turn.status === "running" ? "interrupted" : turn.status,
    verificationPending: false,
    savePending: false,
    savedNeedsCheck: !!turn.saved,
    saveError: turn.savePending ? "The last save or check did not finish. Check the saved record before retrying; no automatic request was sent." : turn.saveError,
    verificationError: turn.verificationPending ? "Verification was interrupted. Verify again; no automatic request was sent." : turn.verificationError,
  }));
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
      const recent = next.slice(-30);
      // Full price snapshots are much larger than summary turns. Bound local retention.
      const receipts = new Set(recent.filter((t) => t.comparison?.replay_receipt).slice(-2).map((t) => t.id));
      const retained = recent.map((t) => t.comparison?.replay_receipt && !receipts.has(t.id)
        // Flag the eviction: without the receipt the Save/Verify actions
        // disappear, and the card must explain that rather than going silent.
        ? { ...t, receiptEvicted: true, comparison: { ...t.comparison, replay_receipt: null } } : t);
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

  async function verifyComparison(turn: CopilotTurn) {
    const comparison = turn.comparison;
    if (active.current || !ready || !portfolioId || !comparison?.replay_receipt) return;
    const ac = new AbortController();
    active.current = ac;
    patch(turn.id, { verificationPending: true, verificationError: undefined, verification: undefined });
    const timeout = setTimeout(() => ac.abort("timeout"), 120_000);
    try {
      const verification = await apiFetch(`/api/v1/copilot/compare-change/${comparison.result_id}/verify`, {
        method: "POST", authToken: token ?? undefined, signal: ac.signal,
        body: { expected_portfolio_id: portfolioId, receipt: comparison.replay_receipt }, schema: comparisonVerificationSchema,
      });
      if (verification.result.result_id !== comparison.result_id || verification.result.portfolio_id !== portfolioId)
        throw new ApiError(409, "comparison_mismatch", "Verified result belongs to a different calculation or portfolio.");
      const { result, ...summary } = verification;
      // Replace display data with the server-reproduced original, not a locally edited summary.
      if (!ac.signal.aborted) patch(turn.id, { comparison: { ...result, replay_receipt: comparison.replay_receipt }, verification: summary });
    } catch (error) {
      if (!ac.signal.aborted) patch(turn.id, { verificationError: error instanceof ApiError ? error.message : "Verification failed. No plan or holdings were saved." });
    } finally {
      clearTimeout(timeout);
      patch(turn.id, { verificationPending: false, ...(ac.signal.aborted ? { verificationError: "Verification did not finish. The previous result remains unconfirmed; nothing was saved." } : {}) });
      if (active.current === ac) active.current = null;
    }
  }

  async function saveComparison(turn: CopilotTurn, retrieve = false) {
    const comparison = turn.comparison;
    if (active.current || !ready || !portfolioId || !comparison || (!retrieve && !comparison.replay_receipt?.save_available)) return;
    const ac = new AbortController();
    active.current = ac;
    patch(turn.id, { savePending: true, saveError: undefined });
    const timeout = setTimeout(() => ac.abort("timeout"), 120_000);
    try {
      const saved = await apiFetch(`/api/v1/copilot/compare-change/${comparison.result_id}/${retrieve ? `saved?expected_portfolio_id=${encodeURIComponent(portfolioId)}` : "confirm"}`, {
        method: retrieve ? "GET" : "POST", authToken: token ?? undefined, signal: ac.signal,
        ...(retrieve ? {} : { body: { expected_portfolio_id: portfolioId, receipt: comparison.replay_receipt, confirmed: true } }),
        schema: savedComparisonSchema,
      });
      if (saved.portfolio_id !== portfolioId || saved.result_id !== comparison.result_id || saved.plan_id !== comparison.result_id || saved.result.result_id !== comparison.result_id || saved.result.portfolio_id !== portfolioId)
        throw new ApiError(409, "comparison_mismatch", "Saved result belongs to a different calculation or portfolio.");
      const { result, ...summary } = saved;
      if (!ac.signal.aborted) patch(turn.id, { comparison: { ...result, replay_receipt: comparison.replay_receipt }, saved: summary, savedNeedsCheck: false });
    } catch (error) {
      // Deny-list, not an allow-list: assume the write MAY have happened unless
      // the code provably precedes it. confirm() validates the stored row AFTER
      // the RPC commits, so untrusted_saved_comparison / comparison_conflict can
      // arrive with a draft plan already created — reporting those as definite
      // failure would tell the user the opposite of what happened.
      const settled = ["confirmation_required", "analysis_busy", "comparison_expired", "comparison_stale",
        "portfolio_changed", "comparison_snapshot_too_large", "comparison_save_unavailable",
        "saved_comparison_missing", "unauthorized", "forbidden"];
      const uncertain = !(error instanceof ApiError) || !settled.includes(error.code);
      // A definite 404 on the read path means the plan is gone (e.g. deleted from
      // the plans panel). Drop the remembered save so the card stops pointing at
      // a record that no longer exists and Save becomes reachable again.
      const vanished = retrieve && error instanceof ApiError && error.code === "saved_comparison_missing";
      if (!ac.signal.aborted) patch(turn.id, {
        ...(vanished ? { saved: undefined, savedNeedsCheck: false } : { savedNeedsCheck: !!turn.saved }),
        saveError: vanished
          ? "No saved record exists for this calculation. It may have been deleted with its plan. Save again while the capture is still valid."
          : uncertain
            ? (retrieve
                ? "The saved record could not be read. Check again; this did not change anything."
                : "Saving was not confirmed. Check the saved record or retry this same result; a draft may already exist.")
            : error.message,
      });
    } finally {
      clearTimeout(timeout);
      patch(turn.id, { savePending: false, ...(ac.signal.aborted ? { saveError: retrieve
        ? "Stopped waiting for the saved record. Nothing was sent or changed; check again."
        : "Stopped waiting, not cancelled. Check the saved record or retry the same result; the server may have saved it." } : {}) });
      if (active.current === ac) active.current = null;
    }
  }

  return {
    turns,
    ready,
    pending: turns.some((t) => t.status === "running" || t.verificationPending || t.savePending),
    send,
    openChange,
    compare,
    verifyComparison,
    saveComparison,
    editChange: (id: string, change: ChangeDraft) => { if (!active.current) patch(id, { change, error: undefined }); },
    retrieve: (turn: CopilotTurn) => recover(turn, "retrieve"),
    cancelRun: (turn: CopilotTurn) => recover(turn, "cancel"),
    stop: () => active.current?.abort(),
  };
}
