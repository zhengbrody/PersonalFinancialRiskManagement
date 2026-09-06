import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test-utils";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("q=Explain%20my%20risk"),
}));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { id: "u1" },
    accessToken: "token",
    configured: true,
    loading: false,
  }),
}));
vi.mock("@/components/copilot-insights", () => ({
  CopilotInsightsStrip: () => null,
}));
vi.mock("@/components/copilot-preferences", () => ({
  CopilotPreferencesCard: () => null,
}));
vi.mock("@/components/credits-badge", () => ({ CreditsBadge: () => null }));
vi.mock("@/lib/portfolio-context", () => ({
  usePortfolioContext: () => ({
    activePortfolioId: "p1",
    current: { name: "My book" },
  }),
}));
import CopilotPage from "./page";
afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});
describe("Copilot single-window shell", () => {
  it("has exactly one composer and preserves prefill without auto-running", () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ data: {}, error: null, meta: { request_id: "t" } }),
        ),
      );
    renderWithQuery(<CopilotPage />);
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByLabelText("Ask your Portfolio Copilot")).toHaveValue(
      "Explain my risk",
    );
    expect(
      screen.queryByRole("button", { name: "Get answer" }),
    ).not.toBeInTheDocument();
    expect(
      fetch.mock.calls.some(([url]) => String(url).includes("/copilot/ask")),
    ).toBe(false);
  });
});
