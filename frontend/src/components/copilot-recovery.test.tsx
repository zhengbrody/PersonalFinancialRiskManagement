import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CopilotRecovery } from "./copilot-recovery";

const book = "33333333-3333-4333-8333-333333333333";
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));
afterEach(() => vi.restoreAllMocks());

it("lists only on request and requires a separate action to recover", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
    envelope({ runs: [], untrusted_records: 0, dispatched: 0, removed: 0 }));
  render(<CopilotRecovery token="test-token" portfolioId={book} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("Recent candidate analyses & recovery"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh recent analyses" }));
  await screen.findByText("0 recent analyses.");
  expect(fetcher.mock.calls[0][1]?.method).toBe("GET");
  expect(fetcher.mock.calls[0][0]).toContain(book);
  fireEvent.click(screen.getByRole("button", { name: "Recover pending analyses" }));
  await screen.findByText(/Recovery requested/);
  expect(fetcher.mock.calls[1][1]?.method).toBe("POST");
  expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({ expected_portfolio_id: book });
});

it("rejects a listing from another portfolio", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({
    runs: [{ id: book, portfolio_id: "11111111-1111-4111-8111-111111111111",
      state: "queued", step: "queued", attempts: 0, result: null, error_code: null }],
    untrusted_records: 0, dispatched: 0, removed: 0,
  }));
  render(<CopilotRecovery token="test-token" portfolioId={book} />);
  fireEvent.click(screen.getByText("Recent candidate analyses & recovery"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh recent analyses" }));
  await screen.findByText("Run portfolio mismatch.");
  expect(screen.queryByText(/attempt 0/)).not.toBeInTheDocument();
});
