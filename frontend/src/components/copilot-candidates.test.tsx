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
