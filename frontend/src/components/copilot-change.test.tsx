import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

const book = "33333333-3333-4333-8333-333333333333";
const identity = { portfolioId: book, userId: "user-a" };
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { id: identity.userId }, accessToken: "jwt" }) }));
vi.mock("@/lib/portfolio-context", () => ({ usePortfolioContext: () => ({ activePortfolioId: identity.portfolioId, current: { name: identity.portfolioId } }) }));
import { CopilotConversation } from "./copilot-conversation";

const side = { gross_assets: 13000, net_equity: 8000, cash: 1000, margin: 5000, leverage: 1.625, largest_position_weight: 0.77, annual_volatility: 0.2, var_1d_95_usd: 100, cvar_1d_95_usd: 180 };
const result = {
  result_id: "44444444-4444-4444-8444-444444444444", portfolio_id: book, computed_at: "2026-09-06T12:00:00Z",
  snapshot_digest: "fingerprint", methodology_version: "reduce-close-v1", price_as_of: "2026-09-04", history_start: "2026-01-01", observations: 100,
  assumptions: { expected_portfolio_id: book, ticker: "SGOV", amount: 1000, proceeds: "repay_margin" },
  sources: { SGOV: "fixture" }, baseline: side, candidate: { ...side, gross_assets: 12000, margin: 4000, leverage: 1.5 },
  limitations: ["No guarantee against a margin call."],
};
const envelope = (data: unknown) => new Response(JSON.stringify({ data, error: null, meta: { request_id: "test" } }));
async function fill() {
  fireEvent.click(await screen.findByRole("button", { name: "Test a change" }));
  fireEvent.change(screen.getByLabelText("Held ticker"), { target: { value: "sgov" } });
  fireEvent.change(screen.getByLabelText("Amount to reduce (USD)"), { target: { value: "1000" } });
  fireEvent.change(screen.getByLabelText("Use hypothetical proceeds to"), { target: { value: "repay_margin" } });
}
beforeEach(() => { sessionStorage.clear(); identity.portfolioId = book; identity.userId = "user-a"; });
afterEach(() => vi.restoreAllMocks());

it("clarifies inline without network, then compares explicit assumptions in one composer", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope(result));
  renderWithQuery(<CopilotConversation />);
  await fill();
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.getAllByRole("textbox", { name: "Ask your Portfolio Copilot" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  await screen.findByRole("region", { name: "Change comparison" });
  expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual(result.assumptions);
  expect(String(fetch.mock.calls[0][0])).toContain("/api/v1/copilot/compare-change");
  fireEvent.click(screen.getByRole("button", { name: "Revise assumption" }));
  expect(screen.getByLabelText("Amount to reduce (USD)")).toHaveValue(1000);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("region", { name: "Change comparison" })).toBeInTheDocument();
});

it("restores unfinished clarification without automatically running", async () => {
  const fetch = vi.spyOn(globalThis, "fetch");
  const { unmount } = renderWithQuery(<CopilotConversation />);
  await fill();
  unmount();
  renderWithQuery(<CopilotConversation />);
  expect(await screen.findByLabelText("Held ticker")).toHaveValue("SGOV");
  expect(screen.getByLabelText("Amount to reduce (USD)")).toHaveValue(1000);
  expect(fetch).not.toHaveBeenCalled();
});

it("returns failed comparison to editable inputs and preserves the server explanation", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: null, error: { code: "unsupported_comparison", message: "No positions were removed or treated as zero risk." }, meta: { request_id: "t" } }), { status: 422 }));
  renderWithQuery(<CopilotConversation />);
  await fill();
  fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No positions were removed");
  expect(screen.getByLabelText("Held ticker")).toHaveValue("SGOV");
  expect(screen.queryByRole("region", { name: "Change comparison" })).not.toBeInTheDocument();
});

it("rejects response assumptions that do not match the submitted version", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({ ...result, assumptions: { ...result.assumptions, amount: 2000 } }));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
});

it("suppresses a late comparison after switching portfolios", async () => {
  let resolve!: (r: Response) => void;
  vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise((r) => { resolve = r; }));
  const { rerender } = renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  identity.portfolioId = "22222222-2222-4222-8222-222222222222";
  rerender(<CopilotConversation />);
  resolve(envelope(result));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Change comparison" })).not.toBeInTheDocument());
  expect(screen.queryByLabelText("Held ticker")).not.toBeInTheDocument();
});

it("stopping a comparison restores the assumptions without retrying", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  }));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Stop waiting" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Stopped waiting");
  expect(screen.getByLabelText("Held ticker")).toHaveValue("SGOV");
  expect(fetch).toHaveBeenCalledTimes(1);
});
