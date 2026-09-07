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

const saveReceipt = { record: "signed server snapshot", signature: "a".repeat(64), save_available: true };
const savedResult = { result, plan_id: result.result_id, result_id: result.result_id, portfolio_id: book,
  confirmed_at: "2026-09-06T12:01:00Z", notice: "No holdings changed. Historical draft plan." };

it("requires explicit consent, saves only a receipt, and restores without resubmitting", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt })).mockResolvedValueOnce(envelope(savedResult));
  const view = renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Confirm and save draft" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel save" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  await screen.findByText(/Draft saved/);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ expected_portfolio_id: book, receipt: saveReceipt, confirmed: true });
  expect(String(fetch.mock.calls[1][0])).toContain(`/${result.result_id}/confirm`);
  expect(screen.queryByRole("button", { name: "Save as draft plan" })).not.toBeInTheDocument();
  view.unmount(); renderWithQuery(<CopilotConversation />);
  await screen.findByText(/This tab remembers a saved plan/);
  expect(fetch).toHaveBeenCalledTimes(2);
  fetch.mockResolvedValueOnce(envelope(savedResult));
  fireEvent.click(screen.getByRole("button", { name: "Check saved record" }));
  await screen.findByText(/Draft saved/);
  expect(fetch.mock.calls[2][1]?.method).toBe("GET");
  expect(fetch.mock.calls[2][1]?.body).toBeUndefined();
});

it("makes uncertain saving retryable with the same result and never claims cancellation", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt })).mockRejectedValueOnce(new Error("disconnected"));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("a draft may already exist");
  expect(screen.queryByText(/Draft saved/)).not.toBeInTheDocument();
  fetch.mockResolvedValueOnce(envelope(savedResult));
  fireEvent.click(screen.getByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  await screen.findByText(/Draft saved/);
  expect(fetch.mock.calls[1][0]).toEqual(fetch.mock.calls[2][0]);
  expect(fetch.mock.calls[1][1]?.body).toEqual(fetch.mock.calls[2][1]?.body);
});

it("suppresses late saves after account switches, including after switching back", async () => {
  let resolve!: (r: Response) => void;
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }))
    .mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
  const view = renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  identity.userId = "user-b"; view.rerender(<CopilotConversation />);
  resolve(envelope(savedResult));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Change comparison" })).not.toBeInTheDocument());
  expect(screen.queryByText(/Draft saved/)).not.toBeInTheDocument();
  // The previous assertions only prove the other account's tree is gone. Come
  // back: the late response must not have been written into user-a's thread,
  // which restores as an honest unknown rather than a confirmed save.
  identity.userId = "user-a"; view.rerender(<CopilotConversation />);
  await screen.findByRole("region", { name: "Change comparison" });
  expect(screen.queryByText(/Draft saved/)).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(/did not finish/i);
});

const errorEnvelope = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ data: null, error: { code, message }, meta: { request_id: "test" } }), { status });

it("treats a post-commit server rejection as unknown, not as definite failure", async () => {
  // confirm() validates the stored row AFTER the RPC commits, so this 409 can
  // arrive with the draft already created. Reporting it as failure would tell
  // the user the opposite of what happened.
  const fetch = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }))
    .mockResolvedValueOnce(errorEnvelope(409, "untrusted_saved_comparison", "The saved calculation could not be authenticated."));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("a draft may already exist");
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("keeps a pre-write rejection definite so the user is not sent chasing a record", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }))
    .mockResolvedValueOnce(errorEnvelope(409, "comparison_stale", "Portfolio or capture changed. Run a fresh comparison before saving."));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Run a fresh comparison before saving");
  expect(screen.queryByText(/a draft may already exist/)).not.toBeInTheDocument();
});

it("recovers the save action when the saved record is definitively gone", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }))
    .mockResolvedValueOnce(envelope(savedResult))
    .mockResolvedValueOnce(errorEnvelope(404, "saved_comparison_missing", "No saved comparison was found."));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  fireEvent.click(screen.getByRole("checkbox", { name: /I confirm saving/ }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm and save draft" }));
  await screen.findByText(/Draft saved/);
  expect(screen.queryByRole("button", { name: "Save as draft plan" })).not.toBeInTheDocument();
  // The plan was deleted from the plans panel; the card must stop pointing at it.
  fireEvent.click(screen.getByRole("button", { name: "Check saved record" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("No saved record exists");
  expect(screen.queryByText(/Draft saved/)).not.toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Save as draft plan" })).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(3);
});

it("says so when this tab has dropped an older comparison's signed snapshot", async () => {
  const second = { ...result, result_id: "55555555-5555-4555-8555-555555555555" };
  const third = { ...result, result_id: "66666666-6666-4666-8666-666666666666" };
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }))
    .mockResolvedValueOnce(envelope({ ...second, replay_receipt: saveReceipt }))
    .mockResolvedValueOnce(envelope({ ...third, replay_receipt: saveReceipt }));
  renderWithQuery(<CopilotConversation />);
  // Each revision leaves the previous result mounted, so target the newest form.
  const newest = <T extends HTMLElement>(label: string) => screen.getAllByLabelText(label).at(-1) as T;
  for (let i = 0; i < 3; i += 1) {
    fireEvent.click(i === 0
      ? await screen.findByRole("button", { name: "Test a change" })
      : screen.getAllByRole("button", { name: "Revise assumption" }).at(-1)!);
    fireEvent.change(newest("Held ticker"), { target: { value: "sgov" } });
    fireEvent.change(newest("Amount to reduce (USD)"), { target: { value: "1000" } });
    fireEvent.change(newest("Use hypothetical proceeds to"), { target: { value: "repay_margin" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Compare assumptions" }).at(-1)!);
    await waitFor(() => expect(screen.getAllByRole("region", { name: "Change comparison" })).toHaveLength(i + 1));
  }
  // The oldest lost its receipt to the two-snapshot cap: explain it rather than
  // silently removing Save/Verify from that card.
  await screen.findByText(/can no longer be verified or saved/);
  expect(screen.getAllByRole("button", { name: "Save as draft plan" })).toHaveLength(2);
});

it("moves focus into the consent step and back out on cancel", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Save as draft plan" }));
  await waitFor(() => expect(screen.getByRole("checkbox", { name: /I confirm saving/ })).toHaveFocus());
  fireEvent.click(screen.getByRole("button", { name: "Cancel save" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save as draft plan" })).toHaveFocus());
});

it("restores the surviving turns when one stored turn no longer matches the schema", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(envelope({ ...result, replay_receipt: saveReceipt }));
  const view = renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  await screen.findByRole("region", { name: "Change comparison" });
  const key = Object.keys(sessionStorage).find((k) => k.includes("copilot"))!;
  const stored = JSON.parse(String(sessionStorage.getItem(key)));
  // A future schema change invalidates one older turn; the thread — and the
  // only local pointer to a saved draft — must survive it.
  sessionStorage.setItem(key, JSON.stringify([{ id: "x", kind: "wat", status: 42 }, ...stored]));
  view.unmount(); renderWithQuery(<CopilotConversation />);
  await screen.findByRole("region", { name: "Change comparison" });
});

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

it("keeps mixed-account stress and option expiry limits distinct and never turns unavailable VaR into zero", async () => {
  const mixedSide = { ...side, option_assets: 1288, option_liabilities: 860,
    annual_volatility: null, var_1d_95_usd: null, cvar_1d_95_usd: null };
  vi.spyOn(globalThis, "fetch").mockResolvedValue(envelope({ ...result,
    risk_method: "mixed_instant_stress", baseline: mixedSide, candidate: mixedSide,
    option_quote_basis: "Delayed quotes; timestamps unavailable",
    scenarios: [{ label: "Equity sell-off", shocks: { SGOV: -0.01, GOOGL: -0.2 }, iv_shift: 0.1, horizon_days: 0,
      baseline_pnl: -300, candidate_pnl: -290, baseline_equity: 7700, candidate_equity: 7710 }],
    option_groups: [{ underlying: "GOOGL", expiry: "2027-01-15", name: "Bull call spread", leg_count: 2,
      mark_basis_max_loss: 428, mark_basis_max_gain: 1572 }],
  }));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  expect(await screen.findByRole("region", { name: "Full-account stress scenarios" })).toHaveTextContent("$7,710");
  expect(screen.getAllByText("Unavailable for mixed account")).toHaveLength(6);
  fireEvent.click(screen.getByText("Unchanged option groups · expiry boundaries"));
  expect(screen.getByText(/Max loss:/)).toHaveTextContent("$428");
  expect(screen.getByText(/Option-only bounds from captured marks/)).toBeVisible();
  expect(screen.queryByText(/Unbounded in option-only expiry model/)).not.toBeInTheDocument();
  expect(screen.getAllByRole("textbox", { name: "Ask your Portfolio Copilot" })).toHaveLength(1);
});

const receipt = { record: "opaque captured calculation", signature: "a".repeat(64) };
const verification = { result, verified_at: "2026-09-06T12:05:00Z", inputs_match_now: false,
  snapshot_age_seconds: 3600, recent_capture: false, notice: "Historical calculation reproduced. Not saved." };

it("verifies only on explicit click, replaces local result with reproduced data, and distinguishes stale inputs", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, baseline: { ...side, cash: 99999 }, replay_receipt: receipt }))
    .mockResolvedValueOnce(envelope(verification));
  const { unmount } = renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  await screen.findByRole("button", { name: "Verify captured calculation" });
  unmount(); renderWithQuery(<CopilotConversation />);
  const verify = await screen.findByRole("button", { name: "Verify captured calculation" });
  expect(fetch).toHaveBeenCalledTimes(1); // Refresh must not replay or save.
  fireEvent.click(verify);
  await screen.findByText(/Original calculation reproduced/);
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(JSON.parse(String(fetch.mock.calls[1][1]?.body))).toEqual({ expected_portfolio_id: book, receipt: { ...receipt, save_available: false } });
  expect(String(fetch.mock.calls[1][0])).toContain(`/${result.result_id}/verify`);
  expect(screen.getByText(/Account inputs have changed/)).toBeVisible();
  expect(screen.getByText(/older than 15 minutes/)).toBeVisible();
  expect(screen.queryByText("$99,999.00")).not.toBeInTheDocument();
});

it("never displays successful verification for a different portfolio or tampered receipt", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, replay_receipt: receipt }))
    .mockResolvedValueOnce(envelope({ ...verification, result: { ...result, portfolio_id: "22222222-2222-4222-8222-222222222222" } }));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Verify captured calculation" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("different calculation or portfolio");
  expect(screen.queryByText(/Original calculation reproduced/)).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Change comparison" })).toBeVisible();
});

it("stopping verification keeps the original comparison without claiming a save", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(envelope({ ...result, replay_receipt: receipt }))
    .mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
  renderWithQuery(<CopilotConversation />);
  await fill(); fireEvent.click(screen.getByRole("button", { name: "Compare assumptions" }));
  fireEvent.click(await screen.findByRole("button", { name: "Verify captured calculation" }));
  fireEvent.click(await screen.findByRole("button", { name: "Stop waiting" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("nothing was saved");
  expect(screen.getByRole("region", { name: "Change comparison" })).toBeVisible();
});
