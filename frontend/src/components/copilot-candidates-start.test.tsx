import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopilotCandidates } from "./copilot-candidates";
import { CopilotRecovery } from "./copilot-recovery";

const book = "33333333-3333-4333-8333-333333333333";
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));
const failure = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ data: null, error: { code, message }, meta: { request_id: "test" } }), { status });
const SAVED = "Saved as queued but not started: the analysis queue is full. Retry this same request shortly; it will not be duplicated.";
const NOT_SAVED = "The analysis queue is full. Nothing was saved; try again shortly.";
const done = (id: string, task: unknown) => ({ id, portfolio_id: book, state: "completed", error_code: null, step: "done", attempts: 1,
  result: { snapshot_id: id, portfolio_id: book, computed_at: "2026-09-11", task, baseline: null, candidates: [], preferred_result_id: null,
    coverage: "insufficient_data", judgment: "No candidate meets constraints.", excluded: {}, limitations: [] } });
beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

function start(amount = "500") {
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: amount } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
}

it("a queued-but-not-started run keeps its id and retries the SAME request, never claiming it runs", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(failure(429, "analysis_queue_full", SAVED));
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  start();
  expect(await screen.findByRole("alert")).toHaveTextContent(/Saved as queued, but not started/);
  expect(screen.queryByText(/Analysis: (queued|running)/)).not.toBeInTheDocument();
  const first = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  expect(sessionStorage.getItem("scope:candidate-run")).toBe(first.id);
  // Editing the form must not change what the retry sends.
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: "900" } });
  fetcher.mockImplementationOnce(async (_url, options) => {
    const body = JSON.parse(String(options?.body));
    return envelope(done(body.id, body.task));
  });
  fireEvent.click(screen.getByRole("button", { name: "Try starting again" }));
  await screen.findByText("No candidate meets constraints.");
  const retry = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
  expect(fetcher.mock.calls[1][0]).toMatch(/\/decision-runs$/);
  expect(retry.id).toBe(first.id);
  expect(retry.task).toEqual(first.task);
  expect(screen.queryByRole("button", { name: "Try starting again" })).not.toBeInTheDocument();
});

it("a resume refused as queued-not-started drops the stale state and retries the same resume", async () => {
  const id = "44444444-4444-4444-8444-444444444444";
  sessionStorage.setItem("scope:candidate-run", id);
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ id, portfolio_id: book, state: "interrupted", result: null, error_code: "execution_expired", step: "capturing", attempts: 1 }))
    .mockResolvedValueOnce(failure(429, "analysis_queue_full", SAVED))
    .mockResolvedValueOnce(envelope(done(id, { expected_portfolio_id: book, goal: "increase_cash", amount: 5, protected_holdings: [], confirmed: true })));
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  fireEvent.click(await screen.findByRole("button", { name: "Retrieve original run" }));
  await screen.findByText(/Analysis: interrupted/);
  fireEvent.click(screen.getByRole("button", { name: "Resume with current login" }));
  await screen.findByRole("button", { name: "Try starting again" });
  // The server moved it to queued-but-not-dispatched; "interrupted" would now be false.
  expect(screen.queryByText(/Analysis: /)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Try starting again" }));
  await screen.findByText("No candidate meets constraints.");
  expect(fetcher.mock.calls.slice(1).map(call => call[0])).toEqual([
    expect.stringContaining(`/decision-runs/${id}/resume`), expect.stringContaining(`/decision-runs/${id}/resume`),
  ]);
});

it("queue full with nothing saved says so, offers no same-id retry and forgets the unreserved id", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(failure(429, "analysis_queue_full", NOT_SAVED));
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  start();
  expect(await screen.findByRole("alert")).toHaveTextContent(/Nothing was saved and nothing is running/);
  expect(screen.queryByRole("button", { name: "Try starting again" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Retrieve original run" })).not.toBeInTheDocument();
  expect(sessionStorage.getItem("scope:candidate-run")).toBeNull();
});

it("another active analysis is named and opens the recent-analyses panel for this portfolio", async () => {
  const previous = "55555555-5555-4555-8555-555555555555";
  sessionStorage.setItem("scope:candidate-run", previous);
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => String(url).includes("expected_portfolio_id=")
    ? envelope({ runs: [], untrusted_records: 0, dispatched: 0, removed: 0 })
    : failure(429, "too_many_active_runs", "You already have a background analysis queued or running."));
  render(<><CopilotCandidates token="test" portfolioId={book} scope="scope" /><CopilotRecovery token="test" portfolioId={book} /></>);
  await screen.findByRole("button", { name: "Retrieve original run" });
  start();
  expect(await screen.findByRole("alert")).toHaveTextContent(/Another background analysis is already queued or running for your account/);
  // The refused id had no record: the previously remembered run stays the one to retrieve.
  expect(sessionStorage.getItem("scope:candidate-run")).toBe(previous);
  const panel = screen.getByText("Recent candidate analyses & recovery").closest("details")!;
  expect(panel.open).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "View recent analyses" }));
  await screen.findByText("0 recent analyses.");
  expect(panel.open).toBe(true);
  expect(fetcher.mock.calls.at(-1)?.[1]?.method).toBe("GET");
});

it("the recent-analyses request is scoped to its portfolio", () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  render(<CopilotRecovery token="test" portfolioId={book} />);
  act(() => { window.dispatchEvent(new CustomEvent("mindmarket:copilot-view-recent-analyses", { detail: { portfolioId: "11111111-1111-4111-8111-111111111111" } })); });
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByText("Recent candidate analyses & recovery").closest("details")!.open).toBe(false);
});

it("a refused record is a definite conflict: no retry, start fresh", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(failure(409, "run_conflict", "This analysis record cannot be reused. Start a new one."));
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  start();
  expect(await screen.findByRole("alert")).toHaveTextContent(/cannot be reused.*Start a fresh calculation/);
  expect(screen.queryByRole("button", { name: "Try starting again" })).not.toBeInTheDocument();
  expect(sessionStorage.getItem("scope:candidate-run")).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "Calculate candidates" })).toBeEnabled());
});
