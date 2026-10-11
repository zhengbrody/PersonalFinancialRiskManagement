import { afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { CopilotPutPlans } from "./copilot-put-plans";
import { putResultSchema } from "@/lib/copilot-put";
import fixture from "@/test-fixtures/copilot-put.json";

const result = putResultSchema.parse({ ...fixture, receipt: { record: "signed fixture", signature: "a".repeat(64), save_available: true } });
const saved = { plan_id: fixture.result_id, portfolio_id: fixture.portfolio_id, confirmed_at: fixture.computed_at, result: fixture };
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "fixture" } }));
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("saves only after separate consent, then reviews without claiming ongoing validity", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(saved)).mockResolvedValueOnce(envelope({
    plan_id: saved.plan_id, portfolio_id: saved.portfolio_id, reviewed_at: fixture.computed_at,
    verdict: "assumptions_need_confirmation", changed_fields: [], reasons: ["Confirm current quotes again."],
    live_quote_checked: false, holdings_changed_by_review: false,
  }));
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={result} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Confirm save Put plan" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /Save this original/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  await screen.findByText("Original calculation saved. No holdings were changed.");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
    expected_portfolio_id: fixture.portfolio_id, confirmed: true, receipt: result.receipt,
  });
  fireEvent.click(screen.getByText(/SPY Put · saved/));
  fireEvent.click(screen.getByRole("button", { name: "Review current assumptions" }));
  await screen.findByText("Assumptions need confirmation");
  expect(screen.getByText("Confirm current quotes again.")).toBeVisible();
});

it("an uncertain save can retry the exact original result", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Saving was not confirmed. Retry this same result."))
    .mockResolvedValueOnce(envelope(saved));
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={result} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Save this original/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  await screen.findByText(/Saving was not confirmed/);
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  await screen.findByText("Original calculation saved. No holdings were changed.");
  expect(fetcher.mock.calls[0][0]).toBe(fetcher.mock.calls[1][0]);
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
});

it("loads successive verified pages and reviews only with session consent", async () => {
  const review = { plan_id: saved.plan_id, portfolio_id: saved.portfolio_id, reviewed_at: fixture.computed_at,
    verdict: "requires_recalculation", changed_fields: ["cash_balance"], reasons: ["Confirm quotes."],
    live_quote_checked: false, holdings_changed_by_review: false };
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ plans: [], next_cursor: "next", skipped_records: 20 }))
    .mockResolvedValueOnce(envelope({ plans: [saved], next_cursor: null, skipped_records: 0 }))
    .mockResolvedValueOnce(envelope(review));
  const { unmount } = render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={null} />);
  fireEvent.click(screen.getByRole("button", { name: "Load saved Put plans" }));
  fireEvent.click(await screen.findByRole("button", { name: "Load more Put plans" }));
  await screen.findByText(/SPY Put · saved/);
  expect(String(fetcher.mock.calls[1][0])).toContain("cursor=next");
  expect(fetcher).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("checkbox", { name: /Review loaded plans/ }));
  await screen.findByText(/Saved Put assumptions changed/);
  expect(fetcher).toHaveBeenCalledTimes(3);
  unmount();
});


it("keeps unchanged reviews quiet, pauses hidden windows and stops on opt-out", async () => {
  const review = { plan_id: saved.plan_id, portfolio_id: saved.portfolio_id, reviewed_at: fixture.computed_at,
    verdict: "assumptions_need_confirmation", changed_fields: [], reasons: ["Confirm quotes."],
    live_quote_checked: false, holdings_changed_by_review: false };
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () => envelope(review));
  fetcher.mockResolvedValueOnce(envelope({ plans: [saved], next_cursor: null, skipped_records: 0 }));
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={null} />);
  fireEvent.click(screen.getByRole("button", { name: "Load saved Put plans" }));
  await screen.findByText(/SPY Put · saved/);
  vi.useFakeTimers();
  await act(async () => { fireEvent.click(screen.getByRole("checkbox", { name: /Review loaded plans/ })); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(screen.queryByText(/Saved Put assumptions changed/)).not.toBeInTheDocument();
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
  fireEvent.click(screen.getByRole("checkbox", { name: /Review loaded plans/ }));
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
});


it("does not start the next plan review after the window becomes hidden", async () => {
  const secondId = "33333333-3333-4333-8333-333333333333";
  const second = { ...saved, plan_id: secondId, result: { ...fixture, result_id: secondId } };
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope({ plans: [saved, second], next_cursor: null, skipped_records: 0 }))
    .mockImplementationOnce(async () => {
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      return envelope({ plan_id: saved.plan_id, portfolio_id: saved.portfolio_id, reviewed_at: fixture.computed_at,
        verdict: "assumptions_need_confirmation", changed_fields: [], reasons: ["Confirm quotes."],
        live_quote_checked: false, holdings_changed_by_review: false });
    });
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={null} />);
  fireEvent.click(screen.getByRole("button", { name: "Load saved Put plans" }));
  await screen.findByText(/Verified history/);
  await act(async () => { fireEvent.click(screen.getByRole("checkbox", { name: /Review loaded plans/ })); });
  expect(fetcher).toHaveBeenCalledTimes(2);
});

const rejection = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ data: null, error: { code, message }, meta: { request_id: "fixture" } }), { status });

it("a network failure during save is shown as an unknown outcome, not as its transport message", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={result} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Save this original/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  const notice = await screen.findByRole("status");
  expect(notice).toHaveTextContent(/Saving was not confirmed.*a draft may already exist/);
  expect(notice).not.toHaveTextContent("Failed to fetch");
  expect(screen.queryByText(/Original calculation saved/)).not.toBeInTheDocument();
});

it("a pre-commit rejection of a Put save is definite and carries the server's reason", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(rejection(409, "put_plan_expired", "Recalculate before saving; this capture has expired."));
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={result} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Save this original/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Recalculate before saving; this capture has expired.");
  expect(screen.queryByText(/was not confirmed/)).not.toBeInTheDocument();
});

it("a save that settles after the portfolio switched is not shown under the new book", async () => {
  let settle!: (response: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementationOnce(() => new Promise<Response>(resolve => { settle = resolve; }));
  const view = render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={result} />);
  fireEvent.click(screen.getByRole("checkbox", { name: /Save this original/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  view.rerender(<CopilotPutPlans token="test" portfolioId="22222222-2222-4222-8222-222222222222" result={result} />);
  await act(async () => { settle(envelope(saved)); });
  expect(screen.queryByText(/Original calculation saved/)).not.toBeInTheDocument();
  expect(screen.queryByText(/SPY Put · saved/)).not.toBeInTheDocument();
});
