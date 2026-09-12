"use client";

import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import { Button } from "./ui/button";
import { apiFetch } from "@/lib/api";
import { candidateRunSchema, type CandidateRun } from "@/lib/copilot-candidates";
import { CopilotChangeResult } from "./copilot-change";

const listSchema = z.object({
  runs: z.array(candidateRunSchema).max(20), untrusted_records: z.number(),
  dispatched: z.number(), removed: z.number(),
});

/** A fresh authenticated request is the recovery authority, never a stored JWT. */
export function CopilotRecovery({ token, portfolioId }: { token: string | null; portfolioId: string }) {
  const [runs, setRuns] = useState<CandidateRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  async function load(recover: boolean) {
    const abort = new AbortController();
    active.current?.abort(); active.current = abort;
    setBusy(true); setNotice("");
    try {
      const value = await apiFetch("/api/v1/copilot/decision-runs" + (recover ? "/recover" : `?expected_portfolio_id=${portfolioId}`), {
        method: recover ? "POST" : "GET", authToken: token ?? undefined, signal: abort.signal,
        schema: listSchema, ...(recover ? { body: { expected_portfolio_id: portfolioId } } : {}),
      });
      const data = listSchema.parse(value);
      if (data.runs.some(run => run.portfolio_id !== portfolioId)) throw new Error("Run portfolio mismatch.");
      if (!abort.signal.aborted) {
        setRuns(data.runs);
        setNotice(recover ? `Recovery requested for ${data.dispatched} pending analyses. Refresh to check progress.` : `${data.runs.length} recent analyses.`);
        if (data.untrusted_records) setNotice(previous => `${previous} Some records could not be verified and were not shown.`);
      }
    } catch (error) {
      if (!abort.signal.aborted) setNotice(error instanceof Error ? error.message : "Could not retrieve analyses.");
    } finally { if (active.current === abort) setBusy(false); }
  }
  return <details className="rounded-xl border border-border p-3">
    <summary className="cursor-pointer text-sm font-medium">Recent candidate analyses & recovery</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">Retrieve results with your current login, including on another device. Recovery may restart an interrupted calculation with fresh prices; it does not save a plan or change holdings.</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" disabled={busy || !token} onClick={() => void load(false)}>Refresh recent analyses</Button>
        <Button type="button" variant="outline" size="sm" disabled={busy || !token} onClick={() => void load(true)}>Recover pending analyses</Button>
      </div>
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {runs.map(run => <details key={run.id} className="rounded-lg border border-border p-3 text-sm">
        <summary className="cursor-pointer">{run.state} · {run.step} · attempt {run.attempts}</summary>
        <p className="mt-2 break-all text-xs">{run.id}</p>
        {run.result && <>
          <p className="my-2">{run.result.judgment}</p>
          {run.result.candidates.map(result => <CopilotChangeResult key={result.result_id} result={result} disabled={false}
            onRevise={() => setNotice("Start a new candidate comparison in this conversation to change the constraints.")} />)}
        </>}
      </details>)}
    </div>
  </details>;
}
