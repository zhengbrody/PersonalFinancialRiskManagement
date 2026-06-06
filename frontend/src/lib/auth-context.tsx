"use client";

/**
 * Auth context — single source of truth for "who is the current user
 * and what JWT do we have for them" in the browser bundle.
 *
 * Why a context (not a hook over Supabase directly):
 *
 *   * Components that need the JWT should read it synchronously
 *     from React state, not via `await supabase.auth.getSession()` on
 *     every render. The context caches it and re-renders on change.
 *   * One subscription point. `supabase.auth.onAuthStateChange` is a
 *     stream; subscribing in 10 different hooks fans out badly.
 *
 * The provider is null-safe: when Supabase env is unconfigured,
 * `user` stays null and `loading` flips to false immediately so
 * pages can still render their public/signed-out branch.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Session, User } from "@supabase/supabase-js";
import { getSupabase } from "./supabase";

export type AuthState = {
  /** Current Supabase user, or null when signed out / no env. */
  user: User | null;
  /** Raw JWT — pass into `apiFetch({ authToken })` for protected calls. */
  accessToken: string | null;
  /** True until the initial session load resolves. */
  loading: boolean;
  /** True when Supabase env is configured (i.e. login is even possible). */
  configured: boolean;
  /** Sign in with email + password. Resolves on success; throws on failure. */
  signIn: (email: string, password: string) => Promise<void>;
  /**
   * Sign up with email + password.
   *
   * Resolves to ``{ needsConfirmation: true }`` when the Supabase
   * project has email confirmation enabled — the UI should show
   * "check your email" copy. Resolves to ``{ needsConfirmation: false }``
   * when the session is immediately active (auto-confirm).
   * Throws on failure (e.g. weak password, email already registered).
   */
  signUp: (
    email: string,
    password: string,
  ) => Promise<{ needsConfirmation: boolean }>;
  /**
   * Start Google OAuth sign-in/sign-up.
   *
   * Supabase handles account creation when the Google identity is new,
   * then redirects back to the app with a browser session.
   */
  signInWithGoogle: () => Promise<void>;
  /** Sign the current user out. No-op when already signed out. */
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const supabase = getSupabase();
  const configured = supabase !== null;
  const queryClient = useQueryClient();

  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState<boolean>(configured);

  useEffect(() => {
    // No client → nothing to subscribe to. Surface "loaded, signed out".
    if (!supabase) {
      setLoading(false);
      return;
    }

    let alive = true;
    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (!alive) return;
        setSession(data.session ?? null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    const { data: sub } = supabase.auth.onAuthStateChange((_evt, sess) => {
      if (!alive) return;
      setSession(sess ?? null);
    });

    return () => {
      alive = false;
      sub.subscription.unsubscribe();
    };
  }, [supabase]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      if (!supabase) {
        throw new Error("Sign-in is not configured on this build.");
      }
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        // Supabase's error.message is user-safe ("Invalid login credentials").
        throw new Error(error.message);
      }
    },
    [supabase],
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      if (!supabase) {
        throw new Error("Sign-up is not configured on this build.");
      }
      const { data, error } = await supabase.auth.signUp({ email, password });
      if (error) {
        throw new Error(error.message);
      }
      // When confirmation is required Supabase returns a user but no
      // session — the user must click an email link before they can
      // sign in. When auto-confirm is on (or already confirmed), the
      // session is attached and we're effectively signed in.
      const needsConfirmation = !data.session;
      return { needsConfirmation };
    },
    [supabase],
  );

  const signInWithGoogle = useCallback(async () => {
    if (!supabase) {
      throw new Error("Google sign-in is not configured on this build.");
    }
    const origin =
      typeof window === "undefined" ? undefined : window.location.origin;
    const redirectTo = origin ? `${origin}/portfolios` : undefined;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: redirectTo ? { redirectTo } : undefined,
    });
    if (error) {
      throw new Error(error.message);
    }
  }, [supabase]);

  const signOut = useCallback(async () => {
    if (!supabase) return;
    await supabase.auth.signOut();
    // Drop every cached query. Without this, the previous user's
    // portfolios / billing data lingers in the React Query cache and is
    // visible to the next person on a shared machine (via back-button
    // or devtools) before a refetch replaces it. Clearing on sign-out
    // is the data-isolation boundary.
    queryClient.clear();
  }, [supabase, queryClient]);

  const value: AuthState = useMemo(
    () => ({
      user: session?.user ?? null,
      accessToken: session?.access_token ?? null,
      loading,
      configured,
      signIn,
      signUp,
      signInWithGoogle,
      signOut,
    }),
    [session, loading, configured, signIn, signUp, signInWithGoogle, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}
