/**
 * /institutions page: renders smart-money signals for the user's holdings and
 * the fund picker. SEC data is mocked via a URL-routing fetch spy.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u-1", email: "owner@mindmarket.test" },
    accessToken: "jwt-here",
    loading: false,
    configured: true,
  }),
}));

import InstitutionsPage from "./page";

function mockJson(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

const SMART_MONEY = {
  data: {
    signals: [
      {
        ticker: "NVDA",
        num_institutions: 18,
        crowding_score: 0.9,
        top_holders: ["Berkshire", "Bridgewater"],
        signal: "HIGH_CONVICTION",
      },
    ],
  },
  error: null,
  meta: { request_id: "r" },
};

const TOP = {
  data: { institutions: [{ name: "Berkshire Hathaway", cik: "0001067983" }] },
  error: null,
  meta: { request_id: "r" },
};

describe("InstitutionsPage", () => {
  it("renders smart-money signals + the fund picker", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/institutions/smart_money")) return Promise.resolve(mockJson(SMART_MONEY));
      if (url.includes("/institutions/top")) return Promise.resolve(mockJson(TOP));
      return Promise.resolve(mockJson({ data: null, error: { code: "x", message: url }, meta: { request_id: "r" } }));
    });

    renderWithQuery(<InstitutionsPage />);

    expect(await screen.findByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText(/high conviction/i)).toBeInTheDocument();
    expect(screen.getByText(/18 funds hold it/i)).toBeInTheDocument();
    // Fund picker option from /top.
    expect(await screen.findByRole("option", { name: "Berkshire Hathaway" })).toBeInTheDocument();
  });

  it("shows a friendly empty state when there are no signals", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/institutions/smart_money"))
        return Promise.resolve(mockJson({ data: { signals: [] }, error: null, meta: { request_id: "r" } }));
      return Promise.resolve(mockJson(TOP));
    });

    renderWithQuery(<InstitutionsPage />);
    expect(await screen.findByText(/no institutional signals yet/i)).toBeInTheDocument();
  });
});
