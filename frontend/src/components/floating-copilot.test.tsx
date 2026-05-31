/**
 * Floating Copilot widget.
 *
 * Branches asserted:
 *   1. signed-out / unconfigured → renders nothing.
 *   2. signed in → launcher shows; clicking it opens the panel with the
 *      shared conversation (example questions visible).
 *   3. hidden on the dedicated /copilot route (no double chat).
 *
 * Auth + navigation are mocked the same way as /copilot.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithQuery } from "@/test-utils";

const pathnameMock = vi.fn(() => "/portfolios");
vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import { FloatingCopilot } from "./floating-copilot";

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

function signedOut() {
  useAuthMock.mockReturnValue({
    user: null,
    accessToken: null,
    loading: false,
    configured: true,
    signIn: vi.fn(),
    signOut: vi.fn(),
  });
}

afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
  pathnameMock.mockReturnValue("/portfolios");
});

beforeEach(() => {
  // Billing/me fires when the conversation opens; harmless empty envelope.
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
    return new Response(JSON.stringify({ data: {}, error: null, meta: {} }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
});

describe("FloatingCopilot", () => {
  it("renders nothing when signed out", () => {
    signedOut();
    const { container } = renderWithQuery(<FloatingCopilot />);
    expect(container).toBeEmptyDOMElement();
    expect(
      screen.queryByRole("button", { name: /ask copilot/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the launcher and opens the panel when signed in", async () => {
    authed();
    const user = userEvent.setup();
    renderWithQuery(<FloatingCopilot />);

    const launcher = screen.getByRole("button", { name: /ask copilot/i });
    expect(launcher).toBeInTheDocument();

    // Closed: the conversation isn't mounted yet.
    expect(
      screen.queryByRole("button", { name: /is my portfolio too risky\?/i }),
    ).not.toBeInTheDocument();

    await user.click(launcher);

    // Open: the shared conversation's example questions appear.
    expect(
      screen.getByRole("button", { name: /is my portfolio too risky\?/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: /portfolio copilot/i }),
    ).toBeInTheDocument();

    // The header close button collapses it again (the launcher also
    // matches /close/i when open, so scope the query to the dialog).
    const dialog = screen.getByRole("dialog", { name: /portfolio copilot/i });
    const { getByRole } = within(dialog);
    await user.click(getByRole("button", { name: /close copilot/i }));
    expect(
      screen.queryByRole("button", { name: /is my portfolio too risky\?/i }),
    ).not.toBeInTheDocument();
  });

  it("is hidden on the dedicated /copilot route", () => {
    authed();
    pathnameMock.mockReturnValue("/copilot");
    const { container } = renderWithQuery(<FloatingCopilot />);
    expect(container).toBeEmptyDOMElement();
  });
});
