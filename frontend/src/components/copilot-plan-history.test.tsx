import { afterEach, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { CopilotPlanHistory, PERIODIC_INTERVAL_MS } from "./copilot-plan-history";
import { metricReviewSchema, savedPlanDetailSchema, savedPlanPageSchema } from "@/lib/plan-history";
// Generated from the real backend services (see report), not hand-written shapes.
import fixture from "@/test-fixtures/plan-history.json";

const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "fixture" } }));
const portfolio = fixture.page.plans[0].portfolio_id;
const planId = fixture.page.plans[0].plan_id;
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("backend fixtures satisfy the frontend contract", () => {
  expect(savedPlanPageSchema.parse(fixture.page).plans).toHaveLength(1);
  expect(savedPlanDetailSchema.parse(fixture.detail).item.kind).toBe("comparison");
  expect(metricReviewSchema.parse(fixture.review).status).toBe("comparable");
  expect(() => savedPlanDetailSchema.parse({ ...fixture.detail, item: { ...fixture.detail.item, kind: "cash_secured_put" } })).toThrow();
});

it("loads history only on request, opens evidence and shows labelled decomposition", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope(fixture.page))
    .mockResolvedValueOnce(envelope(fixture.detail))
    .mockResolvedValueOnce(envelope(fixture.review));
  render(<CopilotPlanHistory token="jwt" portfolioId={portfolio} />);
  fireEvent.click(screen.getByText("Saved plans"));
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Load saved plans" }));
  await screen.findByText(/Hypothetical reduction of SPY/);
  expect(String(fetcher.mock.calls[0][0])).toContain(`saved-plans?expected_portfolio_id=${portfolio}`);
  expect(screen.getByText(/1 record\(s\) could not be verified/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Open original evidence" }));
  const evidence = await screen.findByLabelText("Original evidence");
  expect(within(evidence).getAllByText("$8,000")).toHaveLength(2); // equity conserved on both sides
  fireEvent.click(screen.getByRole("button", { name: "Run review" }));
  const review = await screen.findByLabelText("Plan review");
  expect(within(review).getByText("Same method: changes since saving")).toBeVisible();
  expect(within(review).getByText("+$800")).toBeVisible(); // market change, net equity
  expect(within(review).getByText("+$1,300")).toBeVisible(); // account change
  expect(within(review).getByText(/does not attribute realised returns/)).toBeVisible();
  expect(JSON.parse(String(fetcher.mock.calls[2][1]?.body))).toEqual({ expected_portfolio_id: portfolio });
});

it("method change is shown separately and never totalled", async () => {
  const changed = { ...fixture.review, status: "method_changed",
    metrics: fixture.review.metrics.map(m => ({ ...m, total_change: null, method_change: 0 })) };
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(fixture.page)).mockResolvedValueOnce(envelope(changed));
  render(<CopilotPlanHistory token="jwt" portfolioId={portfolio} />);
  fireEvent.click(screen.getByText("Saved plans"));
  fireEvent.click(screen.getByRole("button", { name: "Load saved plans" }));
  fireEvent.click(await screen.findByRole("button", { name: "Run review" }));
  const review = await screen.findByLabelText("Plan review");
  expect(within(review).getByText(/Calculation method changed/)).toBeVisible();
  expect(within(review).getAllByText("Not reported")).toHaveLength(fixture.review.metrics.length);
});

it("rejects a page for another portfolio", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope(fixture.page));
  render(<CopilotPlanHistory token="jwt" portfolioId="99999999-9999-4999-8999-999999999999" />);
  fireEvent.click(screen.getByText("Saved plans"));
  fireEvent.click(screen.getByRole("button", { name: "Load saved plans" }));
  await screen.findByText(/Saved portfolio mismatch/);
  expect(screen.queryByText(/Hypothetical reduction/)).toBeNull();
});

it("periodic review is opt-in, bounded to the interval and notifies only on change", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const moved = { ...fixture.review, metrics: fixture.review.metrics.map(m => ({ ...m, market_change: (m.market_change ?? 0) + 1 })) };
  const fetcher = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope(fixture.page))
    .mockResolvedValueOnce(envelope(fixture.review))
    .mockResolvedValueOnce(envelope(fixture.review))
    .mockResolvedValueOnce(envelope(moved));
  render(<CopilotPlanHistory token="jwt" portfolioId={portfolio} />);
  fireEvent.click(screen.getByText("Saved plans"));
  fireEvent.click(screen.getByRole("button", { name: "Load saved plans" }));
  const box = await screen.findByRole("checkbox", { name: /every 15 minutes/ });
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(box);
  await act(async () => { await vi.advanceTimersByTimeAsync(10); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(PERIODIC_INTERVAL_MS - 1000); });
  expect(fetcher).toHaveBeenCalledTimes(2);
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(screen.queryByText(/review changed/)).toBeNull(); // unchanged -> no repeat notice
  await act(async () => { await vi.advanceTimersByTimeAsync(PERIODIC_INTERVAL_MS); });
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(await screen.findByText(/A saved plan's review changed/)).toBeVisible();
  expect(String(fetcher.mock.calls[3][0])).toContain(`${planId}/metric-review`);
});
