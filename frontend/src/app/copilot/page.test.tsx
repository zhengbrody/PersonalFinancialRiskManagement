/**
 * `/copilot` Portfolio Copilot chat state-machine.
 *
 * Branches asserted:
 *   1. empty state shows the three example questions.
 *   2. sending a message renders the assistant's plain-language reply.
 *   3. "The numbers behind this" surfaces a grounded fact.
 *   4. a quota_exceeded error renders the friendly upgrade prompt.
 *
 * Auth + navigation are mocked the same way as /portfolios.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import CopilotPage from "./page";

function authed() {
  useAuthMock.mockReturnValue({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "test-jwt",
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signOut: vi.fn(),
  });
}

function envelope(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const billingEnvelope = {
  data: {
    user_id: "u-1",
    email: "owner@mindmarket.test",
    plan: "free",
    subscription: null,
    plans: [],
  },
  error: null,
  meta: { request_id: "r-billing" },
};

/** One Server-Sent Event frame. */
function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/**
 * A minimal streaming Response stand-in: the copilot conversation reads
 * `res.body.getReader()` and decodes SSE frames. We feed the frames as
 * encoded chunks. (Real `Response` streaming bodies aren't reliable under
 * jsdom, so we mock the shape the component actually uses.)
 */
function sseResponse(frames: string[]): Response {
  const enc = new TextEncoder();
  let i = 0;
  const reader = {
    read: () =>
      i < frames.length
        ? Promise.resolve({ done: false, value: enc.encode(frames[i++]) })
        : Promise.resolve({ done: true, value: undefined }),
  };
  return {
    ok: true,
    status: 200,
    body: { getReader: () => reader },
  } as unknown as Response;
}

/**
 * Route fetch by URL: the billing/me query fires on mount (JSON) and the
 * copilot/chat/stream call fires on send (SSE). Ordering is racy, so we
 * dispatch on the request path instead of `mockResolvedValueOnce`.
 */
function routeFetch(chatFrames: string[]) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/copilot/chat")) {
        return sseResponse(chatFrames);
      }
      return envelope(billingEnvelope);
    });
}

beforeEach(() => {
  authed();
});

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("CopilotPage", () => {
  it("renders the empty state with example questions", () => {
    routeFetch([]);
    renderWithQuery(<CopilotPage />);

    expect(
      screen.getByRole("heading", { name: /portfolio copilot/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /is my portfolio too risky\?/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /biggest risk/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /protect against a crash/i }),
    ).toBeInTheDocument();
  });

  it("renders the assistant reply and the grounded numbers", async () => {
    routeFetch([
      sseFrame("status", { phase: "writing" }),
      sseFrame("delta", {
        text: "Your portfolio leans aggressive for a beginner. Consider trimming margin.",
      }),
      sseFrame("done", {
        agent_name: "Portfolio Analyzer",
        grounded_in: { overall_score: 612, annual_volatility: 0.18 },
        draft_trades: [],
      }),
    ]);

    const user = userEvent.setup();
    renderWithQuery(<CopilotPage />);

    await user.click(
      screen.getByRole("button", { name: /is my portfolio too risky\?/i }),
    );

    expect(
      await screen.findByText(/leans aggressive for a beginner/i),
    ).toBeInTheDocument();

    // The numbers are collapsed behind a disclosure, then visible inside.
    const disclosure = screen.getByText(/the numbers behind this/i);
    await user.click(disclosure);

    expect(screen.getByText(/health score/i)).toBeInTheDocument();
    expect(screen.getByText("612 / 1000")).toBeInTheDocument();
    expect(screen.getByText(/volatility/i)).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
  });

  it("shows the friendly upgrade message on quota_exceeded", async () => {
    routeFetch([
      sseFrame("error", {
        code: "quota_exceeded",
        message: "Monthly chat quota exhausted.",
      }),
    ]);

    const user = userEvent.setup();
    renderWithQuery(<CopilotPage />);

    await user.type(
      screen.getByRole("textbox", { name: /ask your portfolio copilot/i }),
      "Help me",
    );
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    expect(
      await screen.findByText(/used your chat quota this month/i),
    ).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /see plans/i });
    expect(link).toHaveAttribute("href", "/pricing");
  });
});
