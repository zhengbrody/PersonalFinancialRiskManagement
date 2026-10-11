import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopilotCandidates } from "./copilot-candidates";
import { CopilotAnswerCard } from "./copilot-answer";
import type { CopilotAnswer } from "@/lib/queries";

const book = "33333333-3333-4333-8333-333333333333";
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));
beforeEach(() => sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

it("requires explicit confirmation, sends typed constraints and never starts on mount", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
    const body = JSON.parse(String(options?.body));
    return envelope({ id: body.id, portfolio_id: book, state: "completed", error_code: null, step: "done", attempts: 1,
      result: { snapshot_id: body.id, portfolio_id: book, computed_at: "2026-09-11", task: body.task, baseline: null,
        candidates: [], preferred_result_id: null, coverage: "insufficient_data", judgment: "No candidate meets constraints.", excluded: {}, limitations: [] } });
  });
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Calculate candidates" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: "500" } });
  fireEvent.change(screen.getByLabelText(/Holdings to preserve/), { target: { value: "aapl, msft" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
  await screen.findByText("No candidate meets constraints.");
  const body = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  expect(body.task).toEqual({ expected_portfolio_id: book, goal: "increase_cash", amount: 500, protected_holdings: ["AAPL", "MSFT"], confirmed: true });
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: "600" } });
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("rejects results from another account", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_url, options) => {
    const body = JSON.parse(String(options?.body));
    return envelope({ id: body.id, portfolio_id: "11111111-1111-4111-8111-111111111111", state: "failed", result: null,
      error_code: "analysis_failed", step: "done", attempts: 1 });
  });
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: "500" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("does not match this portfolio");
  expect(screen.queryByText(/Analysis: failed/)).not.toBeInTheDocument();
});

it("retrieves a stored run without silently dispatching it", async () => {
  const id = "44444444-4444-4444-8444-444444444444";
  sessionStorage.setItem("scope:candidate-run", id);
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({ id, portfolio_id: book, state: "interrupted", result: null, error_code: "execution_expired", step: "capturing", attempts: 1 }));
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  fireEvent.click(await screen.findByRole("button", { name: "Retrieve original run" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  expect(fetcher.mock.calls[0][0]).toContain(`/decision-runs/${id}`);
  expect(fetcher.mock.calls[0][1]?.method).toBe("GET");
  await screen.findByText(/Analysis: interrupted/);
});

it("shows general explanations without a misleading directional refusal banner", () => {
  const answer = { intent: "explain_metric", tickers: [], answer_markdown: "A put has assignment obligations.", evidence: [], data_only: true,
    data_confidence: { directional_allowed: false },
    decision_support: { version: 1, task: { kind: "explanation", goal: null, missing_inputs: [], confirmed_constraints: {} }, coverage: "explained", methods: [], limitations: [], save_available: false, candidate_comparison_available: false },
  } as unknown as CopilotAnswer;
  render(<CopilotAnswerCard answer={answer} />);
  expect(screen.getByText("General explanation · no account calculation")).toBeInTheDocument();
  expect(screen.queryByText(/Not enough verified data for a directional answer/)).not.toBeInTheDocument();
});

type Side = { gross_assets: number; net_equity: number; cash: number; margin: number; leverage: number; largest_position_weight: number; annual_volatility: number | null; var_1d_95_usd: number | null; cvar_1d_95_usd: number | null };
const candidateSide: Side = { gross_assets: 13000, net_equity: 8000, cash: 1000, margin: 5000, leverage: 1.625, largest_position_weight: 0.77, annual_volatility: 0.2, var_1d_95_usd: -100, cvar_1d_95_usd: -180 };
const candidateId = "44444444-4444-4444-8444-444444444444";
const failure = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ data: null, error: { code, message }, meta: { request_id: "test" } }), { status });
function completedRun(id: string, task: unknown, patch: Partial<Side> = {}, preferred = false) {
  const candidate = { result_id: candidateId, portfolio_id: book, computed_at: "2026-09-11T12:00:00Z", snapshot_digest: "fixture",
    methodology_version: "reduce-close-v1", assumptions: { expected_portfolio_id: book, ticker: "SPY", amount: 500, proceeds: "cash" },
    price_as_of: "2026-09-11", history_start: "2026-01-01", observations: 100, sources: { SPY: "fixture" },
    baseline: { ...candidateSide, ...patch }, candidate: { ...candidateSide, ...patch, cash: 1500 }, limitations: [],
    replay_receipt: { record: "signed", signature: "a".repeat(64), save_available: true } };
  return { id, portfolio_id: book, state: "completed", error_code: null, step: "done", attempts: 1,
    result: { snapshot_id: id, portfolio_id: book, computed_at: "2026-09-11T12:00:00Z", task, baseline: candidate.baseline, candidates: [candidate],
      preferred_result_id: preferred ? candidateId : null, coverage: "evaluated", judgment: "Evaluated.", excluded: {}, limitations: [] } };
}
const savedCandidate = (candidate: Record<string, unknown>) => ({ plan_id: candidateId, portfolio_id: book, result_id: candidateId,
  confirmed_at: "2026-09-11T12:01:00Z", notice: "No holdings changed.", result: candidate });
type Fetcher = { mockImplementationOnce: (fn: (url: RequestInfo | URL, options?: RequestInit) => Promise<Response>) => unknown };
async function calculateCandidate(fetcher: Fetcher, patch: Partial<Side> = {}, preferred = false) {
  fetcher.mockImplementationOnce(async (_url: RequestInfo | URL, options?: RequestInit) => {
    const body = JSON.parse(String(options?.body));
    return envelope(completedRun(body.id, body.task, patch, preferred));
  });
  render(<CopilotCandidates token="test" portfolioId={book} scope="scope" />);
  fireEvent.change(screen.getByLabelText("Reduction amount (USD)"), { target: { value: "500" } });
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Calculate candidates" }));
  await screen.findByRole("region", { name: "Change comparison" });
}
async function confirmSave() {
  fireEvent.click(screen.getByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
}

it("reports a pre-commit rejection of a candidate save as definite, not as an unknown outcome", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await calculateCandidate(fetcher);
  fetcher.mockResolvedValueOnce(failure(409, "comparison_expired", "Capture a fresh comparison before saving."));
  await confirmSave();
  expect(await screen.findByRole("alert")).toHaveTextContent("Capture a fresh comparison before saving.");
  expect(screen.queryByText(/could not be confirmed|was not confirmed|remembers a saved plan|Draft saved/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save as draft plan" })).toBeEnabled();
});

it("shows an unknown save outcome as uncertain, never as saved, and the read-back settles it", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await calculateCandidate(fetcher);
  fetcher.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  await confirmSave();
  expect(await screen.findByRole("alert")).toHaveTextContent(/Saving was not confirmed.*a draft may already exist/);
  expect(screen.queryByText(/Draft saved/)).not.toBeInTheDocument();
  const run = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  const candidate = completedRun(run.id, run.task).result.candidates[0];
  fetcher.mockResolvedValueOnce(envelope(savedCandidate(candidate)));
  fireEvent.click(screen.getByRole("button", { name: "Check saved record" }));
  await screen.findByText(/Draft saved/);
  expect(fetcher.mock.calls[2][1]?.method).toBe("GET");
});

it("drops a remembered save when the read-back says the record is gone", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await calculateCandidate(fetcher);
  const run = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  const candidate = completedRun(run.id, run.task).result.candidates[0];
  fetcher.mockResolvedValueOnce(envelope(savedCandidate(candidate)));
  await confirmSave();
  await screen.findByText(/Draft saved/);
  fetcher.mockResolvedValueOnce(failure(404, "saved_comparison_missing", "Saved comparison not found."));
  fireEvent.click(screen.getByRole("button", { name: "Check saved record" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/No saved record exists/);
  expect(screen.queryByText(/Draft saved|remembers a saved plan/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save as draft plan" })).toBeEnabled();
});

it("shows the conditional preference only when every compared risk dimension is known", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await calculateCandidate(fetcher, {}, true);
  expect(screen.getByText("Conditionally preferred among evaluated alternatives")).toBeVisible();
});

it("hides a preference for a candidate whose compared risk is unknown", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await calculateCandidate(fetcher, { annual_volatility: null, var_1d_95_usd: null, cvar_1d_95_usd: null }, true);
  expect(screen.getAllByText("Unavailable for mixed account").length).toBeGreaterThan(0);
  expect(screen.queryByText("Conditionally preferred among evaluated alternatives")).not.toBeInTheDocument();
});

it("an unknown read-back of a remembered save marks it as needing a check, not as confirmed", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  await calculateCandidate(fetcher);
  const run = JSON.parse(String(fetcher.mock.calls[0][1]?.body));
  const candidate = completedRun(run.id, run.task).result.candidates[0];
  fetcher.mockResolvedValueOnce(envelope(savedCandidate(candidate)));
  await confirmSave();
  await screen.findByText(/Draft saved/);
  fetcher.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  fireEvent.click(screen.getByRole("button", { name: "Check saved record" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/could not be read.*did not change anything/);
  expect(screen.getByText(/remembers a saved plan\. Check its server record/)).toBeVisible();
  expect(screen.queryByText(/Draft saved/)).not.toBeInTheDocument();
});
