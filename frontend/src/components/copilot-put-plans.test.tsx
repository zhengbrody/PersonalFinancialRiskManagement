import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CopilotPutPlans } from "./copilot-put-plans";
import { putResultSchema } from "@/lib/copilot-put";
import fixture from "@/test-fixtures/copilot-put.json";

const result = putResultSchema.parse({ ...fixture, receipt: { record: "signed fixture", signature: "a".repeat(64), save_available: true } });
const saved = { plan_id: fixture.result_id, portfolio_id: fixture.portfolio_id, confirmed_at: fixture.computed_at, result: fixture };
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "fixture" } }));
afterEach(() => vi.restoreAllMocks());

it("saves only after separate consent, then reviews without claiming ongoing validity", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(saved)).mockResolvedValueOnce(envelope({
    plan_id: saved.plan_id, portfolio_id: saved.portfolio_id, reviewed_at: fixture.computed_at,
    verdict: "assumptions_need_confirmation", changed_fields: [], reasons: ["Confirm current quotes again."],
    live_quote_checked: false, holdings_changed_by_review: false,
  }));
  render(<CopilotPutPlans token="test" portfolioId={fixture.portfolio_id} result={result} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Confirm save Put plan" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
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
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  await screen.findByText(/Saving was not confirmed/);
  fireEvent.click(screen.getByRole("button", { name: "Confirm save Put plan" }));
  await screen.findByText("Original calculation saved. No holdings were changed.");
  expect(fetcher.mock.calls[0][0]).toBe(fetcher.mock.calls[1][0]);
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
});
