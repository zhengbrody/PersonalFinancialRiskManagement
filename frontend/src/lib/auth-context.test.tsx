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
    signOut: vi.fn(),
  },
};

vi.mock("./supabase", () => ({
  getSupabase: () => fakeClient,
}));

import { AuthProvider, useAuth } from "./auth-context";

function Probe() {
  const { user, accessToken, loading, configured, signIn, signOut } = useAuth();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="configured">{String(configured)}</span>
      <span data-testid="user">{user?.email ?? "anon"}</span>
      <span data-testid="token">{accessToken ?? "none"}</span>
      <button onClick={() => signIn("owner@mindmarket.test", "pw")}>sign-in</button>
      <button onClick={() => signOut()}>sign-out</button>
    </div>
  );
}

beforeEach(() => {
  fakeClient.auth.getSession.mockReset();
  fakeClient.auth.onAuthStateChange.mockReset();
  fakeClient.auth.signInWithPassword.mockReset();
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
  });
});
