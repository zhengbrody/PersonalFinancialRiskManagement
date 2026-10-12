"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import { CopilotFunding } from "./copilot-funding";
import { CopilotChangeResult } from "./copilot-change";
import { apiFetch } from "@/lib/api";
import { candidateRunSchema, classifyRunStartFailure, type CandidateRun } from "@/lib/copilot-candidates";
import { requestRecentAnalyses } from "./copilot-recovery";
import { taskResumeSchema, taskStateEnvelopeSchema, type TaskResume, type TaskStateEnvelope } from "@/lib/copilot-task-state";
import { savedComparisonSchema, type ChangeComparison, type SavedComparison } from "@/lib/copilot-compare";
import { classifySaveFailure, COMPARISON_MISSING_CODE, COMPARISON_SETTLED_CODES } from "@/lib/copilot-save-outcome";

type Goal = "increase_cash" | "reduce_margin";
const GOAL_LABEL: Record<Goal, string> = { increase_cash: "Increase account cash", reduce_margin: "Reduce margin debt" };
type Draft = { goal: Goal; amount: string; protectedNames: string };

function readDraft(key: string): Draft | null {
  try { const raw = sessionStorage.getItem(key); return raw ? JSON.parse(raw) as Draft : null; } catch { return null; }
}

/** Initial form values: what the user typed in this form (unconfirmed draft),
 *  else the current confirmed version, else what they said in chat. */
function initialDraft(key: string, task?: TaskStateEnvelope | null): Draft {
  const stored = readDraft(key);
  if (stored) return stored;
  const confirmed = task?.state?.confirmed;
  if (confirmed && !confirmed.stale) return { goal: confirmed.goal, amount: String(confirmed.amount), protectedNames: confirmed.protected_holdings.join(", ") };
  const said = task?.state?.assumptions;
  return {
    goal: said?.goal ?? (confirmed?.goal ?? "increase_cash"),
    amount: said?.amount != null ? String(said.amount) : confirmed ? String(confirmed.amount) : "",
    protectedNames: (said?.protected_holdings ?? confirmed?.protected_holdings ?? []).join(", "),
  };
}

/** A confirmed task inside the original conversation, never a second chat input. */
export function CopilotCandidates({ token, portfolioId, scope, fundingEnabled = false, task, onTask }: {
  token: string | null; portfolioId: string; scope: string; fundingEnabled?: boolean;
  task?: TaskStateEnvelope | null; onTask?: (task: TaskStateEnvelope) => void;
}) {
  const state = task?.state ?? null;
  const taskKey = state ? `${scope}:task:${state.task_id}` : scope;
  const storageKey = `${taskKey}:candidate-run`;
  const draftKey = `${taskKey}:candidate-draft`;
  const [draft, setDraftState] = useState<Draft>(() => initialDraft(draftKey, task));
  const { goal, amount, protectedNames } = draft;
  const [confirmed, setConfirmed] = useState(false);
  const [run, setRun] = useState<CandidateRun | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Set only when the server durably queued this id but could not start it.
  // `body` is the exact request that was refused, so a retry repeats it with
  // the SAME id (and the same confirmed task) instead of reserving a second job.
  const [retryOffer, setRetryOffer] = useState<{ id: string; operation: "start" | "resume"; body?: Record<string, unknown> } | null>(null);
  const [activeElsewhere, setActiveElsewhere] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const amountInput = useRef<HTMLInputElement | null>(null);
  const base = "/api/v1/copilot/decision-runs";
  const assumptionKey = JSON.stringify(state?.assumptions ?? null);
  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(storageKey);
      const current = state?.confirmed?.run_id ?? null;
      // A run superseded by a newer confirmed version is never shown as current.
      setRunId(state ? current : stored);
    } catch { /* storage optional */ }
    setRetryOffer(null); setActiveElsewhere(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey, state?.confirmed?.run_id]);
  // Abort only on unmount: a confirmed-version change mid-request (our own
  // confirmation) must not cancel the start it is about to issue.
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    // New chat assumptions prefill the form only while the user hasn't typed here.
    if (state && !readDraft(draftKey)) setDraftState(initialDraft(draftKey, task));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assumptionKey, draftKey]);

  function edit(next: Partial<Draft>) {
    const value = { ...draft, ...next };
    setDraftState(value); setConfirmed(false); setRun(null);
    try { sessionStorage.setItem(draftKey, JSON.stringify(value)); } catch { /* optional */ }
  }
  const protectedList = protectedNames.split(/[,\s]+/).filter(Boolean).map(t => t.toUpperCase());
  const current = state?.confirmed ?? null;
  const editedSinceConfirm = !!current && (current.goal !== goal || current.amount !== Number(amount) ||
    [...current.protected_holdings].sort().join() !== [...protectedList].sort().join());

  async function poll(id: string, abort: AbortController, first: CandidateRun) {
    const accept = (value: CandidateRun) => {
      if (value.id !== id || value.portfolio_id !== portfolioId) throw new Error("Analysis does not match this portfolio.");
      if (!abort.signal.aborted) setRun(value);
    };
    accept(first);
    let runState = first.state;
    while (runState === "running" || runState === "queued") {
      await new Promise<void>((resolve, reject) => {
        const finish = () => { abort.signal.removeEventListener("abort", stop); resolve(); };
        const timer = setTimeout(finish, 2500);
        const stop = () => { clearTimeout(timer); reject(new Error("Stopped waiting")); };
        abort.signal.addEventListener("abort", stop, { once: true });
        if (abort.signal.aborted) stop();
      });
      const latest = await apiFetch<CandidateRun>(`${base}/${id}`, { authToken: token ?? undefined, signal: abort.signal, schema: candidateRunSchema });
      accept(latest); runState = latest.state;
    }
  }

  function remember(id: string | null) {
    try { if (id) sessionStorage.setItem(storageKey, id); else sessionStorage.removeItem(storageKey); } catch { /* server record still accessible */ }
  }

  async function execute(operation: "start" | "read" | "resume" | "cancel" | "task-resume" | "retry") {
    if (busy) return;
    const offer = operation === "retry" ? retryOffer : null;
    if (operation === "retry" && !offer) return;
    const previousId = runId;
    const abort = new AbortController();
    controller.current?.abort(); controller.current = abort;
    setBusy(true); setError(null); setNotice(null); setRetryOffer(null); setActiveElsewhere(false);
    // What actually went over the wire, for classifying a refusal below.
    let request: "start" | "read" | "resume" | "cancel" = "read";
    let sentId: string | null = null;
    let sentBody: Record<string, unknown> | undefined;
    const timeout = setTimeout(() => abort.abort(), 125000);
    try {
      if (operation === "task-resume" && task?.token) {
        // Re-authenticates with the CURRENT login and re-checks the account revision.
        const resumed = await apiFetch<TaskResume>("/api/v1/copilot/task-state/resume", {
          method: "POST", authToken: token ?? undefined, signal: abort.signal, schema: taskResumeSchema,
          body: { task_state: task.token, expected_portfolio_id: portfolioId },
        });
        if (resumed.state.portfolio_id !== portfolioId || resumed.state.task_id !== state?.task_id) throw new Error("Task does not match this portfolio.");
        onTask?.({ outcome: "unrelated", state: resumed.state, token: resumed.token });
        setNotice(RESUME_NOTICE[resumed.outcome]);
        if (resumed.outcome === "stale_account_changed") { setRun(null); setConfirmed(false); return; }
        if (resumed.run) { setRunId(resumed.run.id); await poll(resumed.run.id, abort, resumed.run); }
        return;
      }
      let id = operation === "start" ? crypto.randomUUID() : offer ? offer.id : runId;
      if (!id) return;
      request = offer ? offer.operation : operation as typeof request;
      let body: Record<string, unknown> | undefined = offer?.body;
      if (operation === "start") {
        const typed = { expected_portfolio_id: portfolioId, goal, amount: Number(amount), protected_holdings: protectedList, confirmed };
        if (task?.token) {
          // The typed confirmation is recorded server-side first (versioned);
          // the calculation is then bound to exactly that version.
          const next = await apiFetch<TaskStateEnvelope>("/api/v1/copilot/task-state/confirm", {
            method: "POST", authToken: token ?? undefined, signal: abort.signal, schema: taskStateEnvelopeSchema,
            body: { task_state: task.token, expected_portfolio_id: portfolioId, goal, amount: Number(amount), protected_holdings: protectedList, run_id: id, confirmed },
          });
          const version = next.state?.confirmed;
          if (!version || !next.token || next.state?.portfolio_id !== portfolioId) throw new Error("Confirmation does not match this portfolio.");
          onTask?.(next);
          try { sessionStorage.removeItem(draftKey); } catch { /* optional */ }
          id = version.run_id;
          body = { id, task: { ...typed, goal: version.goal, amount: version.amount, protected_holdings: version.protected_holdings }, task_state: next.token };
        } else {
          body = { id, task: typed };
        }
      }
      setRunId(id); remember(id);
      sentId = id; sentBody = body;
      const next = await apiFetch<CandidateRun>(request === "start" ? base : `${base}/${id}${["resume", "cancel"].includes(request) ? `/${request}` : ""}`, {
        method: request === "read" ? "GET" : "POST", authToken: token ?? undefined,
        signal: abort.signal, schema: candidateRunSchema, ...(body ? { body } : {}),
      });
      await poll(id, abort, next);
    } catch (e) {
      if (controller.current !== abort) return;
      if (abort.signal.aborted) {
        setError("Stopped waiting. Retrieve the original run to check its status; this does not cancel server computation.");
        return;
      }
      const failure = sentId && (request === "start" || request === "resume") ? classifyRunStartFailure(e) : { kind: "other" as const };
      // A refused reservation (start path only) left no record behind for this id.
      const forget = () => { const keep = request === "start" ? previousId : sentId; setRunId(keep); remember(keep); };
      if (failure.kind === "active_elsewhere") {
        if (request === "start") forget();
        setActiveElsewhere(true); setError(failure.message);
      } else if (failure.kind === "queue_full_not_saved") {
        forget(); setError(failure.message);
      } else if (failure.kind === "queued_not_started" && sentId) {
        // Never claim it is running: drop any stale state and offer the same-id retry.
        setRun(null); setRetryOffer({ id: sentId, operation: request === "start" ? "start" : "resume", body: sentBody });
        setError(failure.message);
      } else if (failure.kind === "run_conflict") {
        if (request === "start") forget();
        setRun(null); setError(failure.message);
      } else {
        setError(e instanceof Error ? e.message : "Unable to check analysis status.");
      }
    } finally { clearTimeout(timeout); if (controller.current === abort) setBusy(false); }
  }

  const said = state?.assumptions;
  const saidAnything = !!said && (said.goal != null || said.amount != null || said.protected_holdings != null);
  return <section aria-label="Candidate comparison" className="space-y-3 rounded-xl border border-border p-4">
    <h3 className="font-semibold">Compare constrained alternatives</h3>
    <p className="text-sm text-muted-foreground">Keeping the portfolio unchanged is always an option. This compares existing holdings; it does not calculate a new put or broker buying power.</p>
    {state && <div className="grid gap-2 text-sm sm:grid-cols-2">
      <div aria-label="Assumptions from chat" className="rounded-lg border border-dashed border-border p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">You said · not confirmed</p>
        {saidAnything ? <ul className="mt-1 space-y-0.5">
          {said?.goal && <li>Goal: {GOAL_LABEL[said.goal]}</li>}
          {said?.amount != null && <li>Amount: ${said.amount.toLocaleString("en-US")}</li>}
          {said?.protected_holdings != null && <li>Keep: {said.protected_holdings.join(", ") || "none"}</li>}
        </ul> : <p className="mt-1 text-muted-foreground">Nothing stated yet.</p>}
        {state.status !== "confirmed" && state.missing_inputs.length > 0 && <p className="mt-1 text-muted-foreground">Still needed: {state.missing_inputs.map(s => s.replace(/_/g, " ")).join(", ")}. Reply in the chat or fill in the form.</p>}
        <p className="mt-1 text-xs text-muted-foreground">Chat clarifications {state.clarification_turns} of {state.max_clarification_turns}.</p>
      </div>
      <div aria-label="Confirmed parameters" className="rounded-lg border border-primary/40 bg-primary/5 p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-primary">Confirmed parameters{current ? ` · version ${current.version}` : ""}</p>
        {current ? <ul className="mt-1 space-y-0.5">
          <li>Goal: {GOAL_LABEL[current.goal]}</li>
          <li>Amount: ${current.amount.toLocaleString("en-US")}</li>
          <li>Keep: {current.protected_holdings.join(", ") || "none"}</li>
        </ul> : <p className="mt-1 text-muted-foreground">None yet. Nothing is calculated until you confirm below.</p>}
        {current?.stale && <p className="mt-1 font-medium">Account changed since this version was calculated; its result is stale. Re-confirm to calculate again.</p>}
        {state.superseded_run_ids.length > 0 && <p className="mt-1 text-xs text-muted-foreground">Earlier versions are superseded and no longer shown as current.</p>}
      </div>
    </div>}
    <label className="block text-sm">Goal<select aria-label="Comparison goal" className="mt-1 block w-full rounded border bg-background p-2" value={goal} disabled={busy}
      onChange={e => edit({ goal: e.target.value as Goal })}>
      <option value="increase_cash">{GOAL_LABEL.increase_cash}</option><option value="reduce_margin">{GOAL_LABEL.reduce_margin}</option>
    </select></label>
    <label className="block text-sm">Reduction amount (USD)<input ref={amountInput} type="number" min="0.01" step="0.01" max="100000000" className="mt-1 block w-full rounded border bg-background p-2" value={amount} disabled={busy}
      onChange={e => edit({ amount: e.target.value })} /></label>
    <label className="block text-sm">Holdings to preserve (tickers, optional)<input className="mt-1 block w-full rounded border bg-background p-2" value={protectedNames} disabled={busy}
      onChange={e => edit({ protectedNames: e.target.value })} /></label>
    {editedSinceConfirm && !current?.stale && <p className="text-sm">Edited since version {current?.version}. Confirming creates version {(current?.version ?? 0) + 1}; the earlier result is then superseded.</p>}
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} />I confirm this goal, amount and holdings to preserve for this comparison.</label>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy || !confirmed || !Number.isFinite(Number(amount)) || Number(amount) <= 0 || !token} onClick={() => void execute("start")}>Calculate candidates</Button>
      {state?.confirmed && <Button size="sm" variant="outline" disabled={busy || !token} onClick={() => void execute("task-resume")}>Resume task with current login</Button>}
      {runId && <><Button size="sm" variant="outline" disabled={busy} onClick={() => void execute("read")}>Retrieve original run</Button>
        {!state && <Button size="sm" variant="outline" disabled={busy || !!run && !["queued", "interrupted"].includes(run.state)} onClick={() => void execute("resume")}>Resume with current login</Button>}
        <Button size="sm" variant="outline" disabled={busy || !!run && !["queued", "running", "interrupted"].includes(run.state)} onClick={() => void execute("cancel")}>Cancel server analysis</Button></>}
      {busy && <Button size="sm" variant="outline" onClick={() => controller.current?.abort()}>Stop waiting</Button>}
    </div>
    {notice && <p role="status" className="text-sm">{notice}</p>}
    {error && <p role="alert" className="text-sm">{error}</p>}
    {retryOffer && retryOffer.id === runId && <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" disabled={busy || !token} onClick={() => void execute("retry")}>Try starting again</Button>
      <span className="text-xs text-muted-foreground">Repeats the same request; it will not create a duplicate.</span>
    </div>}
    {activeElsewhere && <Button size="sm" variant="outline" disabled={busy} onClick={() => requestRecentAnalyses(portfolioId)}>View recent analyses</Button>}
    {run && <p role="status" className="text-sm">Analysis: {run.state}{run.error_code ? ` · ${run.error_code.replace(/_/g, " ")}` : ""}. {run.state === "queued" ? "Queued, not started yet. If it stays queued, Resume tries to start this same run again." : ""}</p>}
    {run?.result && <div className="space-y-3">
      <p className="text-xs text-muted-foreground">Captured goal: {run.result.task.goal.replace(/_/g, " ")} · reduction ${run.result.task.amount.toLocaleString("en-US")} · preserve: {run.result.task.protected_holdings.join(", ") || "none specified"}.</p>
      <p>{run.result.judgment}</p>
      <p className="text-sm font-medium">Keep unchanged: no sale, no new option obligation.</p>
      {run.result.candidates.map(result => <Candidate key={result.result_id} result={result} token={token} fundingEnabled={fundingEnabled} protectedHoldings={run.result!.task.protected_holdings} preferred={run.result?.preferred_result_id === result.result_id} onRevise={() => { setConfirmed(false); amountInput.current?.focus(); }} />)}
      <details><summary>Exclusions and limits</summary><ul className="list-disc pl-5 text-sm">
        {Object.entries(run.result.excluded).map(([t, why]) => <li key={t}>{t}: {why}</li>)}
        {run.result.limitations.map(text => <li key={text}>{text}</li>)}
      </ul></details>
    </div>}
  </section>;
}

const RESUME_NOTICE: Record<TaskResume["outcome"], string> = {
  needs_input: "Task restored. Some inputs are still needed.",
  ready_to_confirm: "Task restored. Review and confirm to calculate.",
  continuing: "Resumed with your current login. The same confirmed version is continuing.",
  completed: "Restored the result for the confirmed version. The account has not changed since it was calculated.",
  stale_account_changed: "Your account changed since this version was calculated, so its result is stale and was not continued. Re-confirm to calculate again.",
  run_missing: "No stored calculation was found for this version. Your confirmed inputs are kept; calculate again.",
  run_failed: "The calculation for this version did not complete. Calculate again when ready.",
  expired: "This task expired. Ask again to start a new one.",
  closed: "This task was closed.",
};

function Candidate({ result, token, preferred, onRevise, fundingEnabled, protectedHoldings }: { result: ChangeComparison; token: string | null; preferred: boolean; onRevise: () => void; fundingEnabled: boolean; protectedHoldings: string[] }) {
  const [saved, setSaved] = useState<SavedComparison>();
  // True only while the last write/read-back left the server state unknown;
  // a definite pre-commit rejection never marks a remembered save as doubtful.
  const [needsCheck, setNeedsCheck] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const active = useRef<AbortController | null>(null);
  // Scope change (new result, other login, other book) or unmount: stop
  // listening to the old request so a late answer can never land here.
  useEffect(() => () => { active.current?.abort(); active.current = null; setPending(false); },
    [result.result_id, result.portfolio_id, token]);
  async function save(read = false) {
    if (pending) return;
    const abort = new AbortController();
    active.current?.abort(); active.current = abort;
    setPending(true); setError(undefined);
    const base = `/api/v1/copilot/compare-change/${result.result_id}`;
    try {
      const response = await apiFetch(read ? `${base}/saved?expected_portfolio_id=${result.portfolio_id}` : `${base}/confirm`, {
        method: read ? "GET" : "POST", authToken: token ?? undefined, schema: savedComparisonSchema, signal: abort.signal,
        ...(!read ? { body: { expected_portfolio_id: result.portfolio_id, receipt: result.replay_receipt, confirmed: true } } : {}),
      });
      const checked = savedComparisonSchema.parse(response);
      if (checked.result_id !== result.result_id || checked.portfolio_id !== result.portfolio_id || checked.plan_id !== result.result_id || checked.result.result_id !== result.result_id) throw new Error("Saved result scope mismatch.");
      if (abort.signal.aborted) return;
      setSaved(checked); setNeedsCheck(false);
    } catch (e) {
      if (abort.signal.aborted) return;
      const failure = classifySaveFailure(e, {
        settled: COMPARISON_SETTLED_CODES, missing: COMPARISON_MISSING_CODE, retrieve: read,
        uncertainSave: "Saving was not confirmed. Check the saved record or retry this same result; a draft may already exist.",
        uncertainRead: "The saved record could not be read. Check again; this did not change anything.",
        vanished: "No saved record exists for this calculation. It may have been deleted with its plan. Save again while the capture is still valid.",
      });
      if (failure.vanished) setSaved(undefined);
      setNeedsCheck(!failure.definite && !!saved);
      setError(failure.message);
    }
    finally { if (active.current === abort) { active.current = null; setPending(false); } }
  }
  // A conditional preference is only meaningful when every compared risk
  // dimension is known on both sides; a mixed book reports some as null.
  const comparable = [result.baseline, result.candidate].every(side => side.annual_volatility !== null && side.var_1d_95_usd !== null && side.cvar_1d_95_usd !== null);
  return <div className="space-y-2">
    {preferred && comparable && <p className="text-sm font-medium">Conditionally preferred among evaluated alternatives</p>}
    <CopilotChangeResult result={result} disabled={pending} onRevise={onRevise}
      onSave={result.replay_receipt?.save_available ? () => void save() : undefined}
      onRetrieveSaved={() => void save(true)} saved={saved} savePending={pending} saveError={error} savedNeedsCheck={needsCheck} />
    {fundingEnabled && result.replay_receipt && <CopilotFunding source={result} token={token} protectedHoldings={protectedHoldings} />}
  </div>;
}
