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

/** Structured /copilot/ask answer (matches copilotAnswerSchema). */
const COPILOT_ANSWER = {
  intent: "risk_overview",
  tickers: [],
  answer_markdown:
    "**Conclusion:** Your book looks reasonably balanced for your stated risk level.",
  evidence: [],
  data_only: false,
  model: "e2e-stub",
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

  // ── the surfaces under test ──────────────────────────────────────
  await page.route("**/api/v1/risk/score_from_active", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope(SCORE) }),
  );
  await page.route("**/api/v1/copilot/ask", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: envelope(COPILOT_ANSWER) }),
  );
  await page.route("**/api/v1/copilot/chat/stream", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: SSE_STREAM }),
  );
}
