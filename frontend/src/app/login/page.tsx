"use client";

/**
 * Google-first sign-in against Supabase, with email + password fallback.
 *
 * Behaviour on success: redirect to `/portfolios`. The auth context
 * subscription will see the new session and surface the email in the
 * shell pill automatically.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";
import { AuthShell } from "@/components/marketing/auth-shell";
import { C } from "@/components/marketing/theme";

const POST_LOGIN_REDIRECT = "/portfolios";

export default function LoginPage() {
  const router = useRouter();
  const {
    user,
    configured,
    loading: authLoading,
    signIn,
    signInWithGoogle,
  } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [oauthSubmitting, setOauthSubmitting] = useState(false);

  // Already signed in? Bounce. Avoids showing the form to an authed user
  // who navigated here by accident (e.g. bookmark).
  useEffect(() => {
    if (!authLoading && user) {
      router.replace(POST_LOGIN_REDIRECT);
    }
  }, [user, authLoading, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) return;
    setError(null);
    setSubmitting(true);
    try {
      await signIn(email, password);
      router.replace(POST_LOGIN_REDIRECT);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setSubmitting(false);
    }
  }

  async function onGoogle() {
    if (!configured) return;
    setError(null);
    setOauthSubmitting(true);
    try {
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Google sign-in failed.");
      setOauthSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to your portfolio risk cockpit."
      footer={
        <>
          New here?{" "}
          <Link href="/signup" style={{ color: C.teal, textDecoration: "none" }}>
            Create an account
          </Link>
          .
        </>
      }
    >
      {!configured ? (
            // Dev-only: build lacks the NEXT_PUBLIC_SUPABASE_* env vars.
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm">
              Sign-in isn&apos;t available on this preview build. Please try again
              later.
            </div>
          ) : (
            <div className="space-y-5">
              <Button
                type="button"
                className="w-full"
                variant="outline"
                disabled={oauthSubmitting || submitting || authLoading}
                onClick={onGoogle}
              >
                <span aria-hidden="true" className="font-semibold">
                  G
                </span>
                {oauthSubmitting ? "Opening Google…" : "Continue with Google"}
              </Button>

              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="h-px flex-1 bg-border" />
                <span>Email fallback</span>
                <span className="h-px flex-1 bg-border" />
              </div>

              <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-2">
                <label
                  htmlFor="email"
                  className="text-sm text-muted-foreground"
                >
                  Email
                </label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="password"
                  className="text-sm text-muted-foreground"
                >
                  Password
                </label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {error && (
                <p className="text-sm text-destructive" role="alert">
                  {error}
                </p>
              )}
              <Button
                type="submit"
                className="w-full"
                disabled={submitting || authLoading}
              >
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
            </form>
            </div>
          )}
    </AuthShell>
  );
}
