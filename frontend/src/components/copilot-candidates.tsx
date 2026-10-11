"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import { CopilotFunding } from "./copilot-funding";
import { CopilotChangeResult } from "./copilot-change";
import { apiFetch } from "@/lib/api";
import { candidateRunSchema, classifyRunStartFailure, type CandidateRun, type CandidateTask } from "@/lib/copilot-candidates";
import { requestRecentAnalyses } from "./copilot-recovery";
import { savedComparisonSchema, type ChangeComparison, type SavedComparison } from "@/lib/copilot-compare";
import { classifySaveFailure, COMPARISON_MISSING_CODE, COMPARISON_SETTLED_CODES } from "@/lib/copilot-save-outcome";

/** A confirmed task inside the original conversation, never a second chat input. */
export function CopilotCandidates({ token, portfolioId, scope, fundingEnabled = false }: {
  token: string | null; portfolioId: string; scope: string; fundingEnabled?: boolean;
}) {
  const [goal, setGoal] = useState<"increase_cash" | "reduce_margin">("increase_cash");
  const [amount, setAmount] = useState("");
  const [protectedNames, setProtectedNames] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [run, setRun] = useState<CandidateRun | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set only when the server durably queued this id but could not start it.
  const [retryOffer, setRetryOffer] = useState<{ id: string; operation: "start" | "resume"; task?: CandidateTask } | null>(null);
  const [activeElsewhere, setActiveElsewhere] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const amountInput = useRef<HTMLInputElement | null>(null);
  const storageKey = `${scope}:candidate-run`;
  const base = "/api/v1/copilot/decision-runs";
  useEffect(() => {
    try { setRunId(sessionStorage.getItem(storageKey)); } catch { /* storage optional */ }
    setRetryOffer(null); setActiveElsewhere(false);
    return () => controller.current?.abort();
  }, [storageKey]);
  function remember(id: string | null) {
    try { if (id) sessionStorage.setItem(storageKey, id); else sessionStorage.removeItem(storageKey); } catch { /* server record still accessible */ }
  }

  async function execute(operation: "start" | "read" | "resume" | "cancel" | "retry") {
    if (busy) return;
    const offer = operation === "retry" ? retryOffer : null;
    if (operation === "retry" && !offer) return;
    const id = operation === "start" ? crypto.randomUUID() : offer ? offer.id : runId;
    if (!id) return;
    // What actually goes over the wire: a retry repeats the refused request with
    // the SAME id (and, for a start, the SAME captured task) so the server treats
    // it idempotently instead of reserving a second job.
    const request = offer ? offer.operation : operation as Exclude<typeof operation, "retry">;
    const task: CandidateTask | undefined = request !== "start" ? undefined : offer?.task ?? {
      expected_portfolio_id: portfolioId, goal, amount: Number(amount),
      protected_holdings: protectedNames.split(/[,\s]+/).filter(Boolean).map(t => t.toUpperCase()), confirmed,
    };
    const previousId = runId;
    const abort = new AbortController();
    controller.current?.abort(); controller.current = abort;
    setBusy(true); setError(null); setRunId(id); setRetryOffer(null); setActiveElsewhere(false);
    remember(id);
    const timeout = setTimeout(() => abort.abort(), 125000);
    try {
      const next = await apiFetch<CandidateRun>(request === "start" ? base : `${base}/${id}${["resume", "cancel"].includes(request) ? `/${request}` : ""}`, {
        method: request === "read" ? "GET" : "POST", authToken: token ?? undefined,
        signal: abort.signal, schema: candidateRunSchema,
        ...(request === "start" ? { body: { id, task } } : {}),
      });
      const accept = (value: CandidateRun) => {
        if (value.id !== id || value.portfolio_id !== portfolioId) throw new Error("Analysis does not match this portfolio.");
        if (!abort.signal.aborted) setRun(value);
      };
      accept(next);
      let state = next.state;
      while (state === "running" || state === "queued") {
        await new Promise<void>((resolve, reject) => {
          const finish = () => { abort.signal.removeEventListener("abort", stop); resolve(); };
          const timer = setTimeout(finish, 2500);
          const stop = () => { clearTimeout(timer); reject(new Error("Stopped waiting")); };
          abort.signal.addEventListener("abort", stop, { once: true });
          if (abort.signal.aborted) stop();
        });
        const latest = await apiFetch<CandidateRun>(`${base}/${id}`, { authToken: token ?? undefined, signal: abort.signal, schema: candidateRunSchema });
        accept(latest); state = latest.state;
      }
    } catch (e) {
      if (controller.current !== abort) return;
      if (abort.signal.aborted) {
        setError("Stopped waiting. Retrieve the original run to check its status; this does not cancel server computation.");
        return;
      }
      const failure = request === "start" || request === "resume" ? classifyRunStartFailure(e) : { kind: "other" as const };
      // A refused reservation (start path only) left no record behind for this id.
      const forget = () => { const keep = operation === "start" ? previousId : null; setRunId(keep); remember(keep); };
      if (failure.kind === "active_elsewhere") {
        if (request === "start") forget();
        setActiveElsewhere(true); setError(failure.message);
      } else if (failure.kind === "queue_full_not_saved") {
        forget(); setError(failure.message);
      } else if (failure.kind === "queued_not_started") {
        // Never claim it is running: drop any stale state and offer the same-id retry.
        setRun(null); setRetryOffer({ id, operation: request === "start" ? "start" : "resume", task });
        setError(failure.message);
      } else if (failure.kind === "run_conflict") {
        forget(); setRun(null); setError(failure.message);
      } else {
        setError(e instanceof Error ? e.message : "Unable to check analysis status.");
      }
    } finally { clearTimeout(timeout); if (controller.current === abort) setBusy(false); }
  }

  return <section aria-label="Candidate comparison" className="space-y-3 rounded-xl border border-border p-4">
    <h3 className="font-semibold">Compare constrained alternatives</h3>
    <p className="text-sm text-muted-foreground">Keeping the portfolio unchanged is always an option. This compares existing holdings; it does not calculate a new put or broker buying power.</p>
    <label className="block text-sm">Goal<select aria-label="Comparison goal" className="mt-1 block w-full rounded border bg-background p-2" value={goal} disabled={busy}
      onChange={e => { setGoal(e.target.value as typeof goal); setConfirmed(false); setRun(null); }}>
      <option value="increase_cash">Increase account cash</option><option value="reduce_margin">Reduce margin debt</option>
    </select></label>
    <label className="block text-sm">Reduction amount (USD)<input ref={amountInput} type="number" min="0.01" step="0.01" max="100000000" className="mt-1 block w-full rounded border bg-background p-2" value={amount} disabled={busy}
      onChange={e => { setAmount(e.target.value); setConfirmed(false); setRun(null); }} /></label>
    <label className="block text-sm">Holdings to preserve (tickers, optional)<input className="mt-1 block w-full rounded border bg-background p-2" value={protectedNames} disabled={busy}
      onChange={e => { setProtectedNames(e.target.value); setConfirmed(false); setRun(null); }} /></label>
    <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e => setConfirmed(e.target.checked)} />I confirm this goal, amount and holdings to preserve for this comparison.</label>
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy || !confirmed || !Number.isFinite(Number(amount)) || Number(amount) <= 0 || !token} onClick={() => void execute("start")}>Calculate candidates</Button>
      {runId && <><Button size="sm" variant="outline" disabled={busy} onClick={() => void execute("read")}>Retrieve original run</Button>
        <Button size="sm" variant="outline" disabled={busy || !!run && !["queued", "interrupted"].includes(run.state)} onClick={() => void execute("resume")}>Resume with current login</Button>
        <Button size="sm" variant="outline" disabled={busy || !!run && !["queued", "running", "interrupted"].includes(run.state)} onClick={() => void execute("cancel")}>Cancel server analysis</Button></>}
      {busy && <Button size="sm" variant="outline" onClick={() => controller.current?.abort()}>Stop waiting</Button>}
    </div>
    {error && <p role="alert" className="text-sm">{error}</p>}
    {retryOffer && retryOffer.id === runId && <div className="flex flex-wrap items-center gap-2">
      <Button size="sm" disabled={busy || !token} onClick={() => void execute("retry")}>Try starting again</Button>
      {retryOffer.task && <span className="text-xs text-muted-foreground">Same request: {retryOffer.task.goal.replace(/_/g, " ")} · ${retryOffer.task.amount.toLocaleString("en-US")} · preserve {retryOffer.task.protected_holdings.join(", ") || "none"}.</span>}
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
