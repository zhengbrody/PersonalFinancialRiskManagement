/**
 * `AuthProvider` / `useAuth` contract.
 *
 * Mocks the Supabase singleton so we can drive the auth state machine
 * by hand. No real network/Supabase touch.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient } from "@tanstack/react-query";
import { renderWithQuery } from "../test-utils";

type AuthChangeCb = (
  evt: string,
  session: { access_token: string; user: { id: string; email: string } } | null,
) => void;

const fakeClient = {
  auth: {
    getSession: vi.fn(),
    onAuthStateChange: vi.fn(),
    signInWithPassword: vi.fn(),
    signInWithOAuth: vi.fn(),
    signUp: vi.fn(),
    signOut: vi.fn(),
  },
};

vi.mock("./supabase", () => ({
  getSupabase: () => fakeClient,
}));

const clearUserScopedStorage = vi.fn();
const syncUserScopedStorage = vi.fn();
vi.mock("./user-scoped-storage", () => ({
  clearUserScopedStorage: () => clearUserScopedStorage(),
  syncUserScopedStorage: (id: string | null) => syncUserScopedStorage(id),
}));

import { AuthProvider, useAuth } from "./auth-context";

function Probe() {
  const {
    user,
    accessToken,
    loading,
    configured,
    signIn,
    signInWithGoogle,
    signOut,
  } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="configured">{String(configured)}</span>
      <span data-testid="user">{user?.email ?? "anon"}</span>
      <span data-testid="token">{accessToken ?? "none"}</span>
      <button onClick={() => signIn("owner@mindmarket.test", "pw")}>sign-in</button>
      <button onClick={() => signInWithGoogle()}>google</button>
      <button onClick={() => signOut()}>sign-out</button>
    </div>
  );
}

beforeEach(() => {
  fakeClient.auth.getSession.mockReset();
  fakeClient.auth.onAuthStateChange.mockReset();
  fakeClient.auth.signInWithPassword.mockReset();
  fakeClient.auth.signInWithOAuth.mockReset();
  fakeClient.auth.signUp.mockReset();
  fakeClient.auth.signOut.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("AuthProvider", () => {
  it("starts loading, resolves to signed-out when no session", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({ data: { session: null } });
    fakeClient.auth.onAuthStateChange.mockReturnValueOnce({
      data: { subscription: { unsubscribe: vi.fn() } },
    });

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );
    expect(screen.getByTestId("user").textContent).toBe("anon");
    expect(screen.getByTestId("token").textContent).toBe("none");
    expect(screen.getByTestId("configured").textContent).toBe("true");
  });

  it("surfaces the user + access token when a session exists", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({
      data: {
        session: {
          access_token: "jwt-abc",
          user: { id: "u-1", email: "owner@mindmarket.test" },
        },
      },
    });
    fakeClient.auth.onAuthStateChange.mockReturnValueOnce({
      data: { subscription: { unsubscribe: vi.fn() } },
    });

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("user").textContent).toBe(
        "owner@mindmarket.test",
      ),
    );
    expect(screen.getByTestId("token").textContent).toBe("jwt-abc");
  });

  it("re-renders when onAuthStateChange fires", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({ data: { session: null } });
    let storedCb: AuthChangeCb | null = null;
    fakeClient.auth.onAuthStateChange.mockImplementationOnce((cb: AuthChangeCb) => {
      storedCb = cb;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );
    expect(screen.getByTestId("user").textContent).toBe("anon");

    act(() => {
      storedCb!("SIGNED_IN", {
        access_token: "jwt-after",
        user: { id: "u-2", email: "new@mindmarket.test" },
      });
    });

    await waitFor(() =>
      expect(screen.getByTestId("user").textContent).toBe(
        "new@mindmarket.test",
      ),
    );
  });

  it("signIn forwards email + password to supabase", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({ data: { session: null } });
    fakeClient.auth.onAuthStateChange.mockReturnValueOnce({
      data: { subscription: { unsubscribe: vi.fn() } },
    });
    fakeClient.auth.signInWithPassword.mockResolvedValueOnce({ error: null });

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );

    const user = userEvent.setup();
    await user.click(screen.getByText("sign-in"));

    expect(fakeClient.auth.signInWithPassword).toHaveBeenCalledWith({
      email: "owner@mindmarket.test",
      password: "pw",
    });
  });

  it("signInWithGoogle starts the Supabase Google OAuth flow", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({ data: { session: null } });
    fakeClient.auth.onAuthStateChange.mockReturnValueOnce({
      data: { subscription: { unsubscribe: vi.fn() } },
    });
    fakeClient.auth.signInWithOAuth.mockResolvedValueOnce({ error: null });

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );

    const user = userEvent.setup();
    await user.click(screen.getByText("google"));

    expect(fakeClient.auth.signInWithOAuth).toHaveBeenCalledWith({
      provider: "google",
      options: {
        redirectTo: expect.stringContaining("/portfolios"),
      },
    });
  });

  it("signOut clears the React Query cache (data-isolation boundary)", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({ data: { session: null } });
    fakeClient.auth.onAuthStateChange.mockReturnValueOnce({
      data: { subscription: { unsubscribe: vi.fn() } },
    });
    fakeClient.auth.signOut.mockResolvedValueOnce({ error: null });
    const clearSpy = vi.spyOn(QueryClient.prototype, "clear");

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );

    const user = userEvent.setup();
    await user.click(screen.getByText("sign-out"));

    await waitFor(() => expect(fakeClient.auth.signOut).toHaveBeenCalled());
    expect(clearSpy).toHaveBeenCalled();
    // …and the per-user browser storage half of the isolation boundary.
    expect(clearUserScopedStorage).toHaveBeenCalled();
  });

  it("syncs per-user storage once auth resolves (identity-change wipe)", async () => {
    fakeClient.auth.getSession.mockResolvedValueOnce({
      data: { session: { access_token: "t", user: { id: "user-42", email: "a@b.c" } } },
    });
    fakeClient.auth.onAuthStateChange.mockReturnValueOnce({
      data: { subscription: { unsubscribe: vi.fn() } },
    });

    renderWithQuery(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading").textContent).toBe("false"),
    );
    // Resolved with a real user id → sync is called with it (never during the
    // transient loading=true null, which would wipe a returning user's state).
    expect(syncUserScopedStorage).toHaveBeenCalledWith("user-42");
    expect(syncUserScopedStorage).not.toHaveBeenCalledWith(null);
  });
});
