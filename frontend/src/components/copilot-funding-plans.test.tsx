import { afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopilotFundingPlans } from "./copilot-funding-plans";
import { fundingResultSchema } from "@/lib/copilot-funding";
import fixture from "@/test-fixtures/copilot-funding.json";

const result = fundingResultSchema.parse({ ...fixture.result, receipt: { record: "signed synthetic", signature: "a".repeat(64), save_available: true } });
const saved = { plan_id: result.result_id, portfolio_id: result.portfolio_id, confirmed_at: result.computed_at, result: { ...result, receipt: null } };
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "fixture" } }));
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("requires separate save confirmation, retries original evidence and reviews without outcome claims", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce(envelope(saved)).mockResolvedValueOnce(envelope({
      plan_id: result.result_id, portfolio_id: result.portfolio_id, reviewed_at: result.computed_at,
      verdict: "requires_recalculation", changed_fields: ["cash_balance"], reasons: ["Reconfirm quotes and account assumptions."],
      live_quote_checked: false, holdings_changed_by_review: false,
    }));
  render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Confirm save funding plan" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  await screen.findByText(/Save status is unconfirmed/);
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
  fireEvent.click(screen.getByRole("button", { name: "Review funding assumptions" }));
  await screen.findByText("Recalculate funding scenario");
  expect(screen.getByText(/Changed: cash_balance/)).toBeVisible();
});

it("rejects saved evidence from a different account and clears consent on scope change", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({ ...saved, portfolio_id: "22222222-2222-4222-8222-222222222222" }));
  const view = render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByRole("status");
  expect(screen.queryByRole("button", { name: "Review funding assumptions" })).not.toBeInTheDocument();
  view.rerender(<CopilotFundingPlans result={result} token="other-login" portfolioId={result.portfolio_id} />);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
});

it("opens a signed saved plan by id without inventing a new calculation", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(saved));
  render(<CopilotFundingPlans planId={result.result_id} token="fixture" portfolioId={result.portfolio_id} />);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  expect(fetcher.mock.calls[0][1]?.method).toBe("GET");
});


const checked = { plan_id: result.result_id, portfolio_id: result.portfolio_id, reviewed_at: result.computed_at,
  verdict: "assumptions_need_confirmation", changed_fields: [], reasons: ["Confirm quotes."],
  live_quote_checked: false, holdings_changed_by_review: false };

it("funding session review stays quiet when unchanged and pauses hidden windows", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => envelope(checked));
  fetcher.mockResolvedValueOnce(envelope(saved));
  render(<CopilotFundingPlans planId={result.result_id} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  expect(fetcher).toHaveBeenCalledTimes(1);
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole("checkbox", { name: /Review this funding plan/ })); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(screen.queryByText(/Saved funding assumptions changed/)).not.toBeInTheDocument();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("funding changes show once and explicit opt-out stops subsequent requests", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => envelope({ ...checked, verdict: "requires_recalculation", changed_fields: ["cash_balance"] }));
  fetcher.mockResolvedValueOnce(envelope(saved));
  render(<CopilotFundingPlans planId={result.result_id} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole("checkbox", { name: /Review this funding plan/ })); });
  expect(screen.getByText(/Saved funding assumptions changed/)).toBeVisible();
  expect(screen.getByText("Recalculate funding scenario")).toBeVisible();
  fireEvent.click(screen.getByRole("checkbox", { name: /Review this funding plan/ }));
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("funding session consent expires on login change and unmount aborts monitoring", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => envelope(checked));
  fetcher.mockResolvedValueOnce(envelope(saved));
  const view = render(<CopilotFundingPlans planId={result.result_id} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole("checkbox", { name: /Review this funding plan/ })); });
  const signal = fetcher.mock.calls[1][1]?.signal;
  view.rerender(<CopilotFundingPlans planId={result.result_id} token="new-login" portfolioId={result.portfolio_id} />);
  expect(signal?.aborted).toBe(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  view.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

const rejection = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ data: null, error: { code, message }, meta: { request_id: "fixture" } }), { status });

it("reports a pre-commit rejection of a funding save with the server's reason, not as unconfirmed", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(rejection(409, "funding_plan_expired", "Capture new scenarios before saving."));
  render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Capture new scenarios before saving.");
  expect(screen.queryByText(/unconfirmed|Verified original funding plan/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Review funding assumptions" })).not.toBeInTheDocument();
});

it("keeps a post-commit or unknown failure uncertain instead of echoing it as definite", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(rejection(409, "untrusted_funding_plan", "Saved funding evidence could not be authenticated."));
  render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  expect(await screen.findByRole("status")).toHaveTextContent(/Save status is unconfirmed.*a draft may already exist/);
});

it("stops claiming a saved funding plan once the read-back reports it missing", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(saved));
  render(<CopilotFundingPlans planId={result.result_id} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  expect(screen.getByRole("button", { name: "Review funding assumptions" })).toBeVisible();
  fetcher.mockResolvedValueOnce(rejection(404, "funding_plan_missing", "Saved funding plan not found."));
  fireEvent.click(screen.getByRole("button", { name: "Retrieve saved funding plan" }));
  await screen.findByText(/No saved funding plan exists/);
  expect(screen.queryByRole("button", { name: "Review funding assumptions" })).not.toBeInTheDocument();
  expect(screen.queryByText(/^Saved /)).not.toBeInTheDocument();
});

it("a save that settles after the login or portfolio changed is not shown in the new scope", async () => {
  let settle!: (response: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise<Response>(resolve => { settle = resolve; }));
  const view = render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  view.rerender(<CopilotFundingPlans result={result} token="other-login" portfolioId={result.portfolio_id} />);
  await act(async () => { settle(envelope(saved)); });
  expect(screen.queryByText("Verified original funding plan. No holdings or orders changed.")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Review funding assumptions" })).not.toBeInTheDocument();
});

const rejected = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ data: null, error: { code, message }, meta: { request_id: "fixture" } }), { status });

it("moves focus to the save outcome instead of dropping it to the page body", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(saved));
  render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  const outcome = await screen.findByText("Verified original funding plan. No holdings or orders changed.");
  await waitFor(() => expect(outcome).toHaveFocus());
});

it("treats an expired capture as a definite refusal and focuses it", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(rejected(409, "funding_plan_expired", "Capture new scenarios before saving."));
  render(<CopilotFundingPlans result={result} token="fixture" portfolioId={result.portfolio_id} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save funding plan" }));
  const outcome = await screen.findByText("Capture new scenarios before saving.");
  await waitFor(() => expect(outcome).toHaveFocus());
  expect(screen.queryByText(/Save status is unconfirmed/)).not.toBeInTheDocument();
});
