/**
 * `/login` page contract.
 *
 * Branches asserted:
 *   1. Supabase env unset → the form is hidden, setup notice shown.
 *   2. signIn() resolves → we navigate to /portfolios.
 *   3. signIn() rejects → the error message renders in an alert.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const useAuthMock = vi.fn();
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => useAuthMock(),
}));

import LoginPage from "./page";

afterEach(() => {
  vi.clearAllMocks();
});

describe("LoginPage", () => {
  it("renders the setup notice when Supabase env is missing", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: false,
      signIn: vi.fn(),
      signOut: vi.fn(),
    });

    render(<LoginPage />);
    expect(screen.getByText(/supabase is not configured/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sign in/i }),
    ).not.toBeInTheDocument();
  });

  it("calls signIn and redirects to /portfolios on success", async () => {
    const signIn = vi.fn().mockResolvedValue(undefined);
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn,
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<LoginPage />);

    await user.type(screen.getByLabelText(/email/i), "owner@mindmarket.test");
    await user.type(screen.getByLabelText(/password/i), "hunter2");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(signIn).toHaveBeenCalledWith("owner@mindmarket.test", "hunter2");
    expect(replaceMock).toHaveBeenCalledWith("/portfolios");
  });

  it("surfaces the error message when signIn rejects", async () => {
    const signIn = vi.fn().mockRejectedValue(new Error("Invalid login credentials"));
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn,
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<LoginPage />);
    await user.type(screen.getByLabelText(/email/i), "x@y.com");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/invalid login credentials/i);
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
