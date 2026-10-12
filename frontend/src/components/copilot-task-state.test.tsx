import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { CopilotCandidates } from "./copilot-candidates";
import { openTask, type TaskStateEnvelope } from "@/lib/copilot-task-state";
import { useCopilotThread } from "@/lib/use-copilot-thread";

const book = "33333333-3333-4333-8333-333333333333";
const otherBook = "44444444-4444-4444-8444-444444444444";
const runId = "55555555-5555-4555-8555-555555555555";
const ok = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "t" } }));
const token = { record: '{"signed":true}', signature: "b".repeat(64) };

function envelope(patch: Record<string, unknown> = {}, portfolio = book): TaskStateEnvelope {
  return {
    outcome: "started", token,
    state: {
      task_id: "66666666-6666-4666-8666-666666666666", portfolio_id: portfolio, kind: "candidate_request",
      status: "needs_input", missing_inputs: ["protected_holdings"], pending_question: "protected_holdings",
      ambiguities: [], clarification_turns: 0, max_clarification_turns: 3,
      assumptions: { goal: "increase_cash", amount: 5000, protected_holdings: null },
      confirmed: null, superseded_run_ids: [], expires_at: "2999-01-01T00:00:00Z", ...patch,
    },
  } as TaskStateEnvelope;
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

it("shows chat assumptions separately from confirmed parameters and never calculates on mount", () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  render(<CopilotCandidates token="jwt" portfolioId={book} scope="s" task={envelope()} />);
  expect(screen.getByLabelText("Assumptions from chat")).toHaveTextContent("not confirmed");
  expect(screen.getByLabelText("Assumptions from chat")).toHaveTextContent("$5,000");
  expect(screen.getByLabelText("Confirmed parameters")).toHaveTextContent("None yet");
  expect(screen.getByLabelText("Reduction amount (USD)")).toHaveValue(5000);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(fetcher).not.toHaveBeenCalled();
});

it("confirms server-side first, then starts exactly the confirmed version", async () => {
  const confirmed = envelope({ status: "confirmed", confirmed: { version: 1, goal: "increase_cash", amount: 5000,
    protected_holdings: ["NVDA"], confirmed_at: "2026-10-01T00:00:00Z", run_id: runId, stale: false } });
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    if (String(url).endsWith("/task-state/confirm")) return ok({ ...confirmed, outcome: "continued" });
    return ok({ id: runId, portfolio_id: book, state: "failed", result: null, error_code: "analysis_failed", step: "done", attempts: 1 });
  });
  const onTask = vi.fn();
  render(<CopilotCandidates token="jwt" portfolioId={book} scope="s" task={envelope()} onTask={onTask} />);
  fireEvent.change(screen.getByLabelText(/Holdings to preserve/), { target: { value: "nvda" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
  await screen.findByText(/Analysis: failed/);
  const [confirmCall, startCall] = fetcher.mock.calls;
  expect(String(confirmCall[0])).toContain("/task-state/confirm");
  const confirmBody = JSON.parse(String(confirmCall[1]?.body));
  expect(confirmBody).toMatchObject({ confirmed: true, amount: 5000, protected_holdings: ["NVDA"], task_state: token });
  const startBody = JSON.parse(String(startCall[1]?.body));
  expect(startBody.id).toBe(runId);
  expect(startBody.task_state).toEqual(token);
  expect(startBody.task).toMatchObject({ amount: 5000, protected_holdings: ["NVDA"], confirmed: true });
  expect(onTask).toHaveBeenCalledWith(expect.objectContaining({ outcome: "continued" }));
});

it("restores an unconfirmed form draft after reload without confirming it", () => {
  const first = render(<CopilotCandidates token="jwt" portfolioId={book} scope="s" task={envelope()} />);
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: "7500" } });
  first.unmount();
  render(<CopilotCandidates token="jwt" portfolioId={book} scope="s" task={envelope()} />);
  expect(screen.getByLabelText("Reduction amount (USD)")).toHaveValue(7500);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByLabelText("Confirmed parameters")).toHaveTextContent("None yet");
});

it("resume reports a changed account as stale and starts nothing", async () => {
  const confirmed = { version: 1, goal: "increase_cash", amount: 5000, protected_holdings: [],
    confirmed_at: "2026-10-01T00:00:00Z", run_id: runId, stale: false };
  const task = envelope({ status: "confirmed", confirmed });
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({
    outcome: "stale_account_changed", state: { ...task.state, confirmed: { ...confirmed, stale: true } }, token, run: null, dispatched: false,
  }));
  const onTask = vi.fn();
  render(<CopilotCandidates token="jwt" portfolioId={book} scope="s" task={task} onTask={onTask} />);
  fireEvent.click(screen.getByRole("button", { name: "Resume task with current login" }));
  expect(await screen.findByText(/result is stale and was not continued/)).toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(String(fetcher.mock.calls[0][0])).toContain("/task-state/resume");
  expect(onTask.mock.calls[0][0].state.confirmed.stale).toBe(true);
});

it("only a live task for this portfolio is continued", () => {
  expect(openTask(envelope(), book)).not.toBeNull();
  expect(openTask(envelope(), otherBook)).toBeNull();
  expect(openTask(envelope({ status: "closed" }), book)).toBeNull();
  expect(openTask(envelope({ expires_at: "2000-01-01T00:00:00Z" }), book)).toBeNull();
});

it("a follow-up message echoes the open task token, restored after reload", async () => {
  const key = "mm:copilot:thread:v1:u:" + book;
  sessionStorage.setItem(key, JSON.stringify([{ id: "t1", question: "Which should I sell?", kind: "answer", status: "completed",
    answer: { intent: "action_plan", tickers: [], answer_markdown: "x", evidence: [], data_only: true, task_state: envelope() } }]));
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(ok({ intent: "action_plan", tickers: [], answer_markdown: "y", evidence: [], data_only: true }));
  const { result } = renderHook(() => useCopilotThread(key, book, "jwt"));
  await waitFor(() => expect(result.current.ready).toBe(true));
  expect(result.current.task?.turnId).toBe("t1");
  await act(async () => { await result.current.send("keep NVDA"); });
  const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  expect(body.task_state).toEqual(token);
  // Another portfolio's partition never sends this task.
  const other = renderHook(() => useCopilotThread(key, otherBook, "jwt"));
  await waitFor(() => expect(other.result.current.ready).toBe(true));
  expect(other.result.current.task).toBeNull();
});

it("a confirmed-version update from the parent does not abort the start it triggers", async () => {
  const { useState } = await import("react");
  const confirmed = envelope({ status: "confirmed", confirmed: { version: 1, goal: "increase_cash", amount: 5000,
    protected_holdings: [], confirmed_at: "2026-10-01T00:00:00Z", run_id: runId, stale: false } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    if (String(url).endsWith("/task-state/confirm")) return ok({ ...confirmed, outcome: "continued" });
    await new Promise(r => setTimeout(r, 20));
    return ok({ id: runId, portfolio_id: book, state: "failed", result: null, error_code: "analysis_failed", step: "done", attempts: 1 });
  });
  function Parent() {
    const [task, setTask] = useState<TaskStateEnvelope>(envelope());
    return <CopilotCandidates token="jwt" portfolioId={book} scope="s" task={task} onTask={setTask} />;
  }
  render(<Parent />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
  expect(await screen.findByText(/Analysis: failed/)).toBeInTheDocument();
  expect(screen.queryByText(/Stopped waiting/)).not.toBeInTheDocument();
});

it("a confirmed start refused as saved-but-not-started retries the same signed request without re-confirming", async () => {
  const confirmed = envelope({ status: "confirmed", confirmed: { version: 1, goal: "increase_cash", amount: 5000,
    protected_holdings: ["NVDA"], confirmed_at: "2026-10-01T00:00:00Z", run_id: runId, stale: false } });
  const saved = new Response(JSON.stringify({ data: null, meta: { request_id: "t" }, error: {
    code: "analysis_queue_full", message: "Saved as queued but not started: the analysis queue is full.", details: { saved: true } } }), { status: 429 });
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(ok({ ...confirmed, outcome: "continued" }))
    .mockResolvedValueOnce(saved)
    .mockResolvedValueOnce(ok({ id: runId, portfolio_id: book, state: "failed", result: null, error_code: "analysis_failed", step: "done", attempts: 1 }));
  render(<CopilotCandidates token="jwt" portfolioId={book} scope="s" task={envelope()} />);
  fireEvent.change(screen.getByLabelText(/Holdings to preserve/), { target: { value: "nvda" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
  fireEvent.click(await screen.findByRole("button", { name: "Try starting again" }));
  await screen.findByText(/Analysis: failed/);
  expect(fetcher).toHaveBeenCalledTimes(3);
  const [, first, retry] = fetcher.mock.calls;
  expect(String(retry[0])).toMatch(/\/decision-runs$/);
  expect(JSON.parse(String(retry[1]?.body))).toEqual(JSON.parse(String(first[1]?.body)));
  expect(JSON.parse(String(retry[1]?.body)).task_state).toEqual(token);
});
