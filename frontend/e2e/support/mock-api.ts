/**
 * Deterministic backend stub for E2E.
 *
 * Every `/api/v1/*` call the frontend makes is fulfilled here with canned,
 * schema-valid envelopes — so the suite never touches the real FastAPI backend,
 * Supabase, an LLM, or any paid/streaming API. External hosts (Supabase auth,
 * PostHog, Sentry) are stubbed too so nothing leaves the machine.
 *
 * Playwright matches routes in REVERSE registration order (last-registered wins),
 * so the broad catch-all is registered FIRST and the specific routes LAST.
 */

import type { Page } from "@playwright/test";
import { E2E_USER } from "./auth";

// The frontend validates the wrapper on every response: `meta.request_id` is a
// required string (see src/lib/api.ts envelopeSchema), so the stub must include it.
const envelope = (data: unknown) =>
  JSON.stringify({ data, error: null, meta: { request_id: "e2e-stub", elapsed_ms: 0 } });

/** Drives the dashboard hero + /score. Matches scoreResponseSchema. */
const SCORE = {
  overall_score: 782,
  risk_preference: 3,
  risk_target: { label: "Balanced growth", annual_volatility: 0.14, beta: 0.8 },
  metrics: {
    annual_return: 0.11,
    annual_volatility: 0.18,
    sharpe_ratio: 0.92,
    max_drawdown: -0.22,
    var_95_daily: -0.021,
    cvar_95_daily: -0.03,
    beta_to_benchmark: 1.04,
    total_value: 100000,
    net_equity: 100000,
    cash_balance: 5000,
    margin_loan: 0,
    leverage: 1,
    cash_weight: 0.05,
    data_coverage: 1.0,
    observations: 252,
    data_quality_notes: [],
  },
  dimensions: {
    risk_match: { name: "Risk match", score: 6, status: "ok", detail: "Vol near your target." },
    risk_adjusted_return: {
      name: "Risk-adjusted return",
      score: 7,
      status: "ok",
      detail: "Paid for the risk.",
    },
    downside_protection: {
      name: "Downside protection",
      score: 5,
      status: "watch",
      detail: "Drawdown is meaningful.",
    },
  },
  concentration: {
    num_holdings: 8,
    top_holding_ticker: "AAPL",
    top_holding_weight: 0.22,
    top5_weight: 0.71,
    hhi: 0.16,
    effective_holdings: 6.2,
    sectors: [
      { sector: "Technology", weight: 0.55 },
      { sector: "Healthcare", weight: 0.25 },
      { sector: "Energy", weight: 0.2 },
    ],
    top_sector: "Technology",
    top_sector_weight: 0.55,
  },
};

/** Structured /copilot/ask answer (matches copilotAnswerSchema — PR2's
 * six-section contract, so the section renderer is what e2e exercises). */
const COPILOT_ANSWER = {
  intent: "portfolio_diagnosis",
  tickers: [],
  answer_markdown:
    "**Direct answer**\nYour health score is 720/1000.\n\n**Evidence**\n- [E1] Health score: 720/1000",
  evidence: [
    {
      label: "Health score",
      value: "720/1000",
      source: "engine",
      source_type: "derived",
      id: "E1",
      tool: "portfolio_score",
    },
  ],
  data_only: false,
  model: "e2e-stub",
  conviction: "medium",
  language: "en",
  disclaimer: "Educational analysis, not financial advice.",
  sections: [
    {
      key: "direct_answer",
      title: "Direct answer",
      markdown: "Your health score is 720/1000.",
      ai_generated: true,
    },
    {
      key: "portfolio_relevance",
      title: "Why this matters for your portfolio",
      markdown: "These figures are computed from your own current holdings.",
      ai_generated: false,
    },
    { key: "evidence", title: "Evidence", markdown: "- [E1] Health score: 720/1000" },
    {
      key: "data_confidence",
      title: "Data confidence & missing data",
      markdown: "Data confidence: **high**.",
    },
    {
      key: "what_would_change",
      title: "What would change this conclusion",
      markdown: "Fresher price data or a change in your holdings.",
    },
    {
      key: "simulation",
      title: "Simulation",
      markdown:
        "- [E2] Simulated market shock (default what-if assumption): -10%",
    },
  ],
};

/** Confirmed-preferences roundtrip state (in-memory per page). */
const PREFS_EMPTY = {
  confirmed: false,
  risk_tolerance: null,
  investment_horizon: null,
  liquidity_need: null,
  concentration_limit: null,
  margin_limit: null,
  metadata: {},
  confirmed_at: null,
  updated_at: null,
};

/** One deterministic proactive insight for the strip. */
const INSIGHTS = {
  insights: [
    {
      id: "concentration:SPY",
      kind: "concentration",
      severity: "watch",
      what_changed: "A single position is 100.0% of your book.",
      why_it_matters:
        "Above the one-quarter-of-book line, one name's bad day moves your whole portfolio.",
      evidence: [
        {
          label: "Largest position weight",
          value: "100.0%",
          source: "engine",
          id: "E1",
          tool: "concentration",
        },
      ],
      confidence: "high",
      as_of: "2026-07-14T00:00:00+00:00",
      missing_data: [],
      suggested_next_analysis: {
        label: "Review concentration in the Risk Report",
        href: "/risk",
      },
    },
  ],
  as_of: "2026-07-14T00:00:00+00:00",
  portfolio_available: true,
  missing_data: [],
};

/** Server-Sent-Events frames for the streaming /copilot/chat/stream path. The
 * deltas concatenate into the assistant bubble; `done` carries the metadata. */
const SSE_STREAM = [
  "event: delta",
  'data: {"text":"Your portfolio looks reasonably "}',
  "",
  "event: delta",
  'data: {"text":"balanced for your current risk level."}',
  "",
  "event: done",
  'data: {"agent_name":"Portfolio Copilot","grounded_in":{"overall_score":782},"ai_generated":true}',
  "",
  "",
].join("\n");

export async function mockBackend(page: Page): Promise<void> {
  // ── external hosts: never reach the network ──────────────────────
  await page.route(
    /(\.supabase\.co|posthog\.com|sentry\.io|i\.posthog\.com)/,
    (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );

  // ── catch-all backend: empty-but-well-formed envelope (registered
  //    first so the specific routes below override it) ──────────────
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope({}) }),
  );

  // ── secondary reads → empty-but-valid so their widgets render quietly
  await page.route("**/api/v1/risk/snapshot_history**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope({ snapshots: [] }) }),
  );
  await page.route("**/api/v1/risk/alerts", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope({ alerts: [] }) }),
  );
  await page.route("**/api/v1/risk/score_changes", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope({
      window: "previous", available: false, current_score: SCORE.overall_score,
      component_deltas: [], input_changes: [], top_drivers: [], data_quality_changes: [],
      holdings_changes: { added: [], removed: [], reweighted: [] },
      summary: "A second snapshot is needed to compare changes.",
    }) }),
  );
  await page.route("**/api/v1/macro/regime", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope({
      vix: { current: 18.2, change: 0.012, level: "Normal" },
      fear_greed: { score: 52, rating: "Neutral" },
      yield_curve: { status: "Normal", spread_3m_10y: 0.45, inverted: false },
    }) }),
  );

  // ── the surfaces under test ──────────────────────────────────────
  await page.route("**/api/v1/risk/score_from_active", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope(SCORE) }),
  );
  // A default portfolio so the portfolio context + Analyze workspace resolve a book.
  await page.route("**/api/v1/portfolios/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: envelope({
        user_id: E2E_USER.id,
        email: E2E_USER.email,
        portfolios: [
          { id: "pf1", user_id: E2E_USER.id, name: "My Portfolio", holdings: { SPY: { shares: 10 } }, is_default: true,
            margin_loan: 0, contributed_capital: 95000, cash_balance: 5000, created_at: null, updated_at: null },
        ],
      }),
    }),
  );
  // Empty saved plans → the Action Plan stage shows its empty state, not an error.
  await page.route("**/api/v1/risk/plans**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope({ plans: [] }) }),
  );
  await page.route("**/api/v1/copilot/ask", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope(COPILOT_ANSWER) }),
  );
  // Preferences: PUT confirms (echo back confirmed), GET starts unconfirmed,
  // DELETE clears — enough for the confirm/clear UI flow.
  await page.route("**/api/v1/copilot/preferences", (route) => {
    const method = route.request().method();
    if (method === "PUT") {
      const sent = route.request().postDataJSON() as Record<string, unknown>;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope({
          ...PREFS_EMPTY,
          ...sent,
          confirmed: true,
          confirmed_at: "2026-07-14T00:00:00+00:00",
          updated_at: "2026-07-14T00:00:00+00:00",
        }),
      });
    }
    if (method === "DELETE") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope({ cleared: true }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: envelope(PREFS_EMPTY),
    });
  });
  await page.route("**/api/v1/copilot/insights", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope(INSIGHTS) }),
  );
  await page.route("**/api/v1/copilot/chat/stream", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: SSE_STREAM }),
  );
}
