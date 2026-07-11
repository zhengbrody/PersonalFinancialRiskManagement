"use client";

/**
 * Google-first sign-up against Supabase, with email + password fallback.
 *
 * On success:
 *   * If Supabase project has email confirmation ON → show "check your
 *     email" copy. User clicks confirm link, lands on /login.
 *   * If auto-confirm is on → session is attached immediately, redirect
 *     to /portfolios.
 *
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { track } from "@/lib/analytics";
import { useAuth } from "@/lib/auth-context";
import { AuthShell } from "@/components/marketing/auth-shell";
import { C } from "@/components/marketing/theme";

const POST_SIGNUP_REDIRECT = "/portfolios/new"; // new users go straight to guided creation

export default function SignupPage() {
  const router = useRouter();
  const {
    user,
    configured,
    loading: authLoading,
    signUp,
    signInWithGoogle,
  } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [oauthSubmitting, setOauthSubmitting] = useState(false);
  const [confirmationSent, setConfirmationSent] = useState(false);

  useEffect(() => {
    // Already signed in? Bounce; signup is irrelevant.
    if (!authLoading && user) {
      router.replace(POST_SIGNUP_REDIRECT);
    }
  }, [user, authLoading, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) return;
    setError(null);
    setSubmitting(true);
    try {
      const { needsConfirmation } = await signUp(email, password);
      track("signed_up", { needs_confirmation: needsConfirmation });
      if (needsConfirmation) {
        setConfirmationSent(true);
        return;
      }
      router.replace(POST_SIGNUP_REDIRECT);
    } catch (err) {
      setError(formatSignupError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onGoogle() {
    if (!configured) return;
    setError(null);
    setOauthSubmitting(true);
    try {
      track("signup_oauth_started", { provider: "google" });
      await signInWithGoogle();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Google sign-up failed.");
      setOauthSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Free during beta — your first Health Score is a minute away."
      footer={
        <>
          Already have one?{" "}
          <Link href="/login" style={{ color: C.teal, textDecoration: "none" }}>
            Sign in
          </Link>
          .
        </>
      }
    >
      {!configured ? (
            // Dev-only: build lacks the NEXT_PUBLIC_SUPABASE_* env vars.
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm">
              Sign-up isn&apos;t available on this preview build. Please try again
              later.
            </div>
          ) : confirmationSent ? (
            <div className="rounded-md border border-primary/30 bg-primary/10 p-4 text-sm">
              <p className="font-medium text-primary">Check your email.</p>
              <p className="mt-2 text-muted-foreground">
                We sent a confirmation link to{" "}
                <span className="font-mono">{email}</span>. Click it, then{" "}
                <Link href="/login" className="text-primary hover:underline">
                  sign in
                </Link>
                .
              </p>
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
                  autoComplete="new-password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  At least 8 characters. Password-manager generated passwords
                  are supported.
                </p>
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
                {submitting ? "Creating account…" : "Create account"}
              </Button>
            </form>
            </div>
          )}
    </AuthShell>
  );
}

function formatSignupError(err: unknown): string {
  const message = err instanceof Error ? err.message : "Sign-up failed.";
  if (/password should contain|password.*character of each/i.test(message)) {
    return (
      "That password was rejected. " +
      "Use Google sign-up, or try a password with at least 8 characters."
    );
  }
  return message;
}
