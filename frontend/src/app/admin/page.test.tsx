/**
 * /admin owner dashboard: renders the usage aggregates + the new System status
 * section (integration config), and runs live checks on demand. Both endpoints
 * are mocked via a URL-routing fetch spy.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt-here",
    configured: true,
    loading: false,
  }),
}));

import AdminPage from "./page";

function mockJson(body: Record<string, unknown>) {
  return new Response(JSON.stringify({ ...body, meta: { request_id: "r" } }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

const USAGE = {
  data: {
    since: "2026-06-01",
    totals: { events: 12, cost_usd: 1.23, credits: 123, tokens_in: 1000, tokens_out: 2000 },
    by_kind: { chat: { events: 12, cost_usd: 1.23, credits: 123 } },
    users: [{ user_id: "user-abcdef12", events: 12, cost_usd: 1.23, credits: 123 }],
  },
  error: null,
};

function statusBody(live: boolean) {
  return {
    data: {
      live,
      integrations: [
        {
          name: "Claude (Anthropic)",
          state: live ? "Connected" : "Configured",
          detail: live ? "Key valid — API reachable." : "Server-side secret is present.",
          configured: true,
        },
        { name: "Stripe", state: "Missing", detail: "Missing: STRIPE_SECRET_KEY", configured: false },
      ],
    },
    error: null,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AdminPage", () => {
  it("renders usage + system status, and runs live checks on demand", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/admin/usage")) return Promise.resolve(mockJson(USAGE));
      if (url.includes("/admin/status?live=true")) return Promise.resolve(mockJson(statusBody(true)));
      if (url.includes("/admin/status")) return Promise.resolve(mockJson(statusBody(false)));
      return Promise.resolve(mockJson({ data: {}, error: null }));
    });

    const user = userEvent.setup();
    renderWithQuery(<AdminPage />);

    // Usage aggregate + system status both render.
    expect(await screen.findByText("Usage & cost")).toBeInTheDocument();
    expect(screen.getByText(/Month to date \(since Jun 1, 2026 UTC\)/)).toBeInTheDocument();
    expect(screen.getByText(/1 cost unit = \$0.01/)).toBeInTheDocument();
    expect(screen.getAllByText("Cost units").length).toBeGreaterThan(0);
    expect(await screen.findByText("System status")).toBeInTheDocument();
    expect(await screen.findByText("Claude (Anthropic)")).toBeInTheDocument();
    expect(screen.getByText("Configured")).toBeInTheDocument();
    expect(screen.getByText("Missing")).toBeInTheDocument();

    // Run live checks → state flips to Connected.
    await user.click(screen.getByRole("button", { name: /run live checks/i }));
    expect(await screen.findByText("Connected")).toBeInTheDocument();
  });
});
