/**
 * /signup page contract.
 *
 *   1. Setup-needed notice when Supabase env unset.
 *   2. signUp() resolving with needsConfirmation=true → "check email" UI.
 *   3. signUp() resolving with needsConfirmation=false → redirect /portfolios.
 *   4. signUp() rejecting → error rendered.
 *   5. Google OAuth starts from the primary CTA.
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

import SignupPage from "./page";

afterEach(() => {
  vi.clearAllMocks();
});

describe("SignupPage", () => {
  it("renders the setup notice when Supabase is not configured", () => {
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: false,
      signIn: vi.fn(),
      signUp: vi.fn(),
      signInWithGoogle: vi.fn(),
      signOut: vi.fn(),
    });
    render(<SignupPage />);
    expect(
      screen.getByText(/sign-up isn.t available on this preview build/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /create account/i }),
    ).not.toBeInTheDocument();
  });

  it("shows 'check your email' when confirmation is required", async () => {
    const signUp = vi
      .fn()
      .mockResolvedValue({ needsConfirmation: true });
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp,
      signInWithGoogle: vi.fn(),
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<SignupPage />);

    await user.type(screen.getByLabelText(/email/i), "new@mindmarket.test");
    await user.type(screen.getByLabelText(/password/i), "longpassword");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(signUp).toHaveBeenCalledWith("new@mindmarket.test", "longpassword");
    expect(
      await screen.findByText(/check your email/i),
    ).toBeInTheDocument();
    // No redirect when confirmation is pending.
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("redirects to /portfolios when session is immediate", async () => {
    const signUp = vi
      .fn()
      .mockResolvedValue({ needsConfirmation: false });
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp,
      signInWithGoogle: vi.fn(),
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<SignupPage />);
    await user.type(screen.getByLabelText(/email/i), "x@y.com");
    await user.type(screen.getByLabelText(/password/i), "longpassword");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(replaceMock).toHaveBeenCalledWith("/portfolios/new");
  });

  it("surfaces the error when signUp rejects", async () => {
    const signUp = vi
      .fn()
      .mockRejectedValue(new Error("User already registered"));
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp,
      signInWithGoogle: vi.fn(),
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<SignupPage />);
    await user.type(screen.getByLabelText(/email/i), "x@y.com");
    await user.type(screen.getByLabelText(/password/i), "longpassword");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/user already registered/i);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("rewrites Supabase's strict password-policy error", async () => {
    const signUp = vi.fn().mockRejectedValue(
      new Error(
        "Password should contain at least one character of each: abcdefghijklmnopqrstuvwxyz, ABCDEFGHIJKLMNOPQRSTUVWXYZ, 0123456789, !@#$%^&*()_+-=[]{};':\"|<>?,./`~.",
      ),
    );
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp,
      signInWithGoogle: vi.fn(),
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<SignupPage />);
    await user.type(screen.getByLabelText(/email/i), "x@y.com");
    await user.type(screen.getByLabelText(/password/i), "ChromeGeneratedPassword123");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/that password was rejected/i);
    expect(alert).toHaveTextContent(/use google sign-up/i);
  });

  it("starts Google OAuth from the primary CTA", async () => {
    const signInWithGoogle = vi.fn().mockResolvedValue(undefined);
    useAuthMock.mockReturnValue({
      user: null,
      accessToken: null,
      loading: false,
      configured: true,
      signIn: vi.fn(),
      signUp: vi.fn(),
      signInWithGoogle,
      signOut: vi.fn(),
    });

    const user = userEvent.setup();
    render(<SignupPage />);
    await user.click(screen.getByRole("button", { name: /continue with google/i }));

    expect(signInWithGoogle).toHaveBeenCalledOnce();
  });
});
