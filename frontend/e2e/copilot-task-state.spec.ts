import { test, expect } from "./support/fixtures";
import { seedSession, E2E_USER } from "./support/auth";

const book = "33333333-3333-4333-8333-333333333333";
const runId = "55555555-5555-4555-8555-555555555555";
const taskId = "66666666-6666-4666-8666-666666666666";
const envelope = (data: unknown) => ({ data, error: null, meta: { request_id: "fixture" } });
const tokenA = { record: '{"turn":0}', signature: "a".repeat(64) };
const tokenB = { record: '{"turn":1}', signature: "b".repeat(64) };
const tokenC = { record: '{"confirmed":1}', signature: "c".repeat(64) };
const base = {
  task_id: taskId, portfolio_id: book, kind: "candidate_request", ambiguities: [], max_clarification_turns: 3,
  superseded_run_ids: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", expires_at: "2999-01-01T00:00:00Z",
};
const answer = (markdown: string, task_state: unknown, decision = false) => ({
  intent: "action_plan", tickers: [], answer_markdown: markdown, evidence: [], data_only: true, task_state,
  ...(decision ? { decision_support: { version: 1, task: { kind: "candidate_request", goal: null, missing_inputs: ["goal", "budget", "protected_holdings"], confirmed_constraints: {} },
    coverage: "insufficient_data", methods: [], limitations: [], save_available: false, candidate_comparison_available: true } } : {}),
});

test("a follow-up continues the task; confirmation is typed; reload resumes with the current login", async ({ page }) => {
  await seedSession(page);
  await page.route("**/api/v1/portfolios/me", route => route.fulfill({ json: envelope({ user_id: E2E_USER.id, email: E2E_USER.email,
    portfolios: [{ id: book, user_id: E2E_USER.id, name: "Task portfolio", holdings: { SPY: { shares: 10 } }, is_default: true,
      margin_loan: 0, cash_balance: 1000, contributed_capital: 2000, created_at: null, updated_at: null }] }) }));
  const asks: Array<Record<string, unknown>> = [];
  await page.route("**/api/v1/copilot/ask", route => {
    const body = route.request().postDataJSON();
    asks.push(body);
    if (!body.task_state) return route.fulfill({ json: envelope(answer("Confirm your goal, amount and holdings to keep.", {
      outcome: "started", token: tokenA, state: { ...base, status: "needs_input", missing_inputs: ["protected_holdings"], pending_question: "protected_holdings",
        clarification_turns: 0, assumptions: { goal: "increase_cash", amount: 5000, protected_holdings: null, stated_at_turn: { goal: 0, amount: 0 } }, confirmed: null } }, true)) });
    expect(body.task_state).toEqual(tokenA);
    return route.fulfill({ json: envelope(answer("Recorded as an assumption, not a confirmed parameter: holdings to keep.", {
      outcome: "continued", token: tokenB, state: { ...base, status: "ready_to_confirm", missing_inputs: [], pending_question: null,
        clarification_turns: 1, assumptions: { goal: "increase_cash", amount: 5000, protected_holdings: ["NVDA"], stated_at_turn: { goal: 0, amount: 0, protected_holdings: 1 } }, confirmed: null } })) });
  });
  const confirmedState = { ...base, status: "confirmed", missing_inputs: [], pending_question: null, clarification_turns: 1,
    assumptions: { goal: "increase_cash", amount: 5000, protected_holdings: ["NVDA"] },
    confirmed: { version: 1, goal: "increase_cash", amount: 5000, protected_holdings: ["NVDA"], confirmed_at: "2026-10-01T00:00:00Z", run_id: runId, stale: false } };
  let confirms = 0;
  await page.route("**/api/v1/copilot/task-state/confirm", route => {
    confirms++;
    const body = route.request().postDataJSON();
    expect(body).toMatchObject({ confirmed: true, task_state: tokenB, amount: 5000, protected_holdings: ["NVDA"] });
    return route.fulfill({ json: envelope({ outcome: "continued", token: tokenC, state: confirmedState }) });
  });
  const run = { id: runId, portfolio_id: book, state: "queued", error_code: null, attempts: 0, step: "queued", result: null };
  let starts = 0;
  await page.route("**/api/v1/copilot/decision-runs", route => {
    starts++;
    const body = route.request().postDataJSON();
    expect(body.id).toBe(runId);
    expect(body.task_state).toEqual(tokenC);
    return route.fulfill({ json: envelope({ ...run, state: "interrupted", error_code: "execution_expired", step: "capturing", attempts: 1 }) });
  });
  await page.route("**/api/v1/copilot/decision-runs?*", route =>
    route.fulfill({ json: envelope({ runs: [], untrusted_records: 0, dispatched: 0, removed: 0 }) }));
  let resumes = 0;
  await page.route("**/api/v1/copilot/task-state/resume", route => {
    resumes++;
    expect(route.request().headers()["authorization"]).toMatch(/^Bearer /);
    return route.fulfill({ json: envelope({ outcome: "stale_account_changed", token: tokenC,
      state: { ...confirmedState, confirmed: { ...confirmedState.confirmed, stale: true } }, run: null, dispatched: false }) });
  });

  await page.goto("/copilot");
  await expect(page.getByRole("button", { name: "Task portfolio", exact: true })).toBeVisible();
  await page.getByTestId("copilot-input").fill("Which stocks should I sell to raise $5,000 in cash?");
  await page.getByTestId("copilot-send").click();
  const said = page.getByLabel("Assumptions from chat");
  await expect(said).toContainText("not confirmed");
  await expect(said).toContainText("$5,000");
  await page.getByTestId("copilot-input").fill("keep NVDA");
  await page.getByTestId("copilot-send").click();
  await expect(page.getByLabel("Assumptions from chat")).toContainText("Keep: NVDA");
  await expect(page.getByLabel("Confirmed parameters")).toContainText("None yet");
  expect(await page.getByRole("region", { name: "Candidate comparison" }).count()).toBe(1);
  await expect(page.getByLabel("Reduction amount (USD)")).toHaveValue("5000");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Calculate candidates" }).click();
  await expect(page.getByLabel("Confirmed parameters")).toContainText("version 1");
  await expect(page.getByText(/Analysis: interrupted/)).toBeVisible();
  expect([confirms, starts]).toEqual([1, 1]);
  await page.reload();
  await expect(page.getByLabel("Confirmed parameters")).toContainText("version 1");
  expect(starts).toBe(1);
  await page.getByRole("button", { name: "Resume task with current login" }).click();
  await expect(page.getByText(/result is stale and was not continued/)).toBeVisible();
  await expect(page.getByLabel("Confirmed parameters")).toContainText("Account changed");
  expect([resumes, starts]).toEqual([1, 1]);
  expect(asks.length).toBe(2);
  await expect(page.getByTestId("copilot-input")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("region", { name: "Candidate comparison", exact: true }).screenshot({ path: test.info().outputPath("task-state.png") });
});
