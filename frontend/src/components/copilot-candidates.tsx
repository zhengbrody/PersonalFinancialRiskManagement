"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import { CopilotFunding } from "./copilot-funding";
import { CopilotChangeResult } from "./copilot-change";
import { apiFetch } from "@/lib/api";
import { candidateRunSchema, type CandidateRun } from "@/lib/copilot-candidates";
import { savedComparisonSchema, type ChangeComparison, type SavedComparison } from "@/lib/copilot-compare";

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
  const controller = useRef<AbortController | null>(null);
  const storageKey = `${scope}:candidate-run`;
  const base = "/api/v1/copilot/decision-runs";
  useEffect(() => {
    try { setRunId(sessionStorage.getItem(storageKey)); } catch { /* storage optional */ }
    return () => controller.current?.abort();
  }, [storageKey]);

  async function execute(operation: "start" | "read" | "resume" | "cancel") {
    if (busy) return;
    const id = operation === "start" ? crypto.randomUUID() : runId;
    if (!id) return;
    const abort = new AbortController();
    controller.current?.abort(); controller.current = abort;
    setBusy(true); setError(null); setRunId(id);
    try { sessionStorage.setItem(storageKey, id); } catch { /* server record still accessible */ }
    const timeout = setTimeout(() => abort.abort(), 125000);
    try {
      const next = await apiFetch<CandidateRun>(operation === "start" ? base : `${base}/${id}${["resume", "cancel"].includes(operation) ? `/${operation}` : ""}`, {
        method: operation === "read" ? "GET" : "POST", authToken: token ?? undefined,
        signal: abort.signal, schema: candidateRunSchema,
        ...(operation === "start" ? { body: { id, task: {
          expected_portfolio_id: portfolioId, goal, amount: Number(amount),
          protected_holdings: protectedNames.split(/[,\s]+/).filter(Boolean).map(t => t.toUpperCase()), confirmed,
        } } } : {}),
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
      if (controller.current === abort) setError(abort.signal.aborted
        ? "Stopped waiting. Retrieve the original run to check its status; this does not cancel server computation."
        : e instanceof Error ? e.message : "Unable to check analysis status.");
    } finally { clearTimeout(timeout); if (controller.current === abort) setBusy(false); }
  }

  return <section aria-label="Candidate comparison" className="space-y-3 rounded-xl border border-border p-4">
    <h3 className="font-semibold">Compare constrained alternatives</h3>
    <p className="text-sm text-muted-foreground">Keeping the portfolio unchanged is always an option. This compares existing holdings; it does not calculate a new put or broker buying power.</p>
    <label className="block text-sm">Goal<select aria-label="Comparison goal" className="mt-1 block w-full rounded border bg-background p-2" value={goal} disabled={busy}
      onChange={e => { setGoal(e.target.value as typeof goal); setConfirmed(false); setRun(null); }}>
      <option value="increase_cash">Increase account cash</option><option value="reduce_margin">Reduce margin debt</option>
    </select></label>
    <label className="block text-sm">Reduction amount (USD)<input type="number" min="0.01" step="0.01" max="100000000" className="mt-1 block w-full rounded border bg-background p-2" value={amount} disabled={busy}
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
    {run && <p role="status" className="text-sm">Analysis: {run.state}{run.error_code ? ` · ${run.error_code.replace(/_/g, " ")}` : ""}. {run.state === "queued" ? "Waiting for capacity. Resume can redispatch this same run after an interruption." : ""}</p>}
    {run?.result && <div className="space-y-3">
      <p className="text-xs text-muted-foreground">Captured goal: {run.result.task.goal.replace(/_/g, " ")} · reduction ${run.result.task.amount.toLocaleString("en-US")} · preserve: {run.result.task.protected_holdings.join(", ") || "none specified"}.</p>
      <p>{run.result.judgment}</p>
      <p className="text-sm font-medium">Keep unchanged: no sale, no new option obligation.</p>
      {run.result.candidates.map(result => <Candidate key={result.result_id} result={result} token={token} fundingEnabled={fundingEnabled} protectedHoldings={run.result!.task.protected_holdings} preferred={run.result?.preferred_result_id === result.result_id} onRevise={() => { setConfirmed(false); document.querySelector<HTMLInputElement>('[aria-label="Candidate comparison"] input[type="number"]')?.focus(); }} />)}
      <details><summary>Exclusions and limits</summary><ul className="list-disc pl-5 text-sm">
        {Object.entries(run.result.excluded).map(([t, why]) => <li key={t}>{t}: {why}</li>)}
        {run.result.limitations.map(text => <li key={text}>{text}</li>)}
      </ul></details>
    </div>}
  </section>;
}

function Candidate({ result, token, preferred, onRevise, fundingEnabled, protectedHoldings }: { result: ChangeComparison; token: string | null; preferred: boolean; onRevise: () => void; fundingEnabled: boolean; protectedHoldings: string[] }) {
  const [saved, setSaved] = useState<SavedComparison>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  async function save(read = false) {
    if (pending) return;
    setPending(true); setError(undefined);
    const base = `/api/v1/copilot/compare-change/${result.result_id}`;
    try {
      const response = await apiFetch(read ? `${base}/saved?expected_portfolio_id=${result.portfolio_id}` : `${base}/confirm`, {
        method: read ? "GET" : "POST", authToken: token ?? undefined, schema: savedComparisonSchema,
        ...(!read ? { body: { expected_portfolio_id: result.portfolio_id, receipt: result.replay_receipt, confirmed: true } } : {}),
      });
      const checked = savedComparisonSchema.parse(response);
      if (checked.result_id !== result.result_id || checked.portfolio_id !== result.portfolio_id) throw new Error("Saved result scope mismatch.");
      setSaved(checked);
    } catch { setError("Save status could not be confirmed. Check the saved result before retrying."); }
    finally { setPending(false); }
  }
  return <div className="space-y-2">
    {preferred && <p className="text-sm font-medium">Conditionally preferred among evaluated alternatives</p>}
    <CopilotChangeResult result={result} disabled={pending} onRevise={onRevise}
      onSave={result.replay_receipt?.save_available ? () => void save() : undefined}
      onRetrieveSaved={() => void save(true)} saved={saved} savePending={pending} saveError={error} savedNeedsCheck={!!error} />
    {fundingEnabled && result.replay_receipt && <CopilotFunding source={result} token={token} protectedHoldings={protectedHoldings} />}
  </div>;
}
