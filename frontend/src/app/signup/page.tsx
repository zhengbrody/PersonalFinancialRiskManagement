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
import { getFirstTouchUtm, track } from "@/lib/analytics";
import { ANALYTICS_EVENTS } from "@/lib/analytics-events";
import { useAuth } from "@/lib/auth-context";
import { AuthShell } from "@/components/marketing/auth-shell";
import { C } from "@/components/marketing/theme";
import {
  authHref,
  consumeAuthRedirect,
  readAuthRedirect,
  rememberAuthRedirect,
} from "@/lib/auth-redirect";

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
  const [redirectPath, setRedirectPath] = useState(POST_SIGNUP_REDIRECT);
  const [redirectReady, setRedirectReady] = useState(false);

  useEffect(() => {
    const next = readAuthRedirect(POST_SIGNUP_REDIRECT);
    setRedirectPath(rememberAuthRedirect(next, POST_SIGNUP_REDIRECT));
    setRedirectReady(true);
  }, []);

  useEffect(() => {
    // Already signed in? Bounce; signup is irrelevant.
    if (redirectReady && !authLoading && user) {
      router.replace(consumeAuthRedirect(POST_SIGNUP_REDIRECT));
    }
  }, [user, authLoading, redirectReady, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) return;
    setError(null);
    setSubmitting(true);
    track(ANALYTICS_EVENTS.signup_started, { method: "email" });
    try {
      const { needsConfirmation } = await signUp(email, password, redirectPath);
      track(ANALYTICS_EVENTS.signup_completed, {
        method: "email",
        needs_confirmation: needsConfirmation,
        ...getFirstTouchUtm(),
      });
      if (needsConfirmation) {
        setConfirmationSent(true);
        return;
      }
      router.replace(consumeAuthRedirect(POST_SIGNUP_REDIRECT));
    } catch (err) {
      // Record only the error CATEGORY — never the message (may echo input).
      track(ANALYTICS_EVENTS.signup_failed, { method: "email", error_category: signupErrorCategory(err) });
      setError(formatSignupError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onGoogle() {
    if (!configured) return;
    setError(null);
    setOauthSubmitting(true);
    track(ANALYTICS_EVENTS.signup_started, { method: "google" });
    try {
      track(ANALYTICS_EVENTS.signup_oauth_started, { provider: "google" });
      await signInWithGoogle(redirectPath);
    } catch (err) {
      track(ANALYTICS_EVENTS.signup_failed, { method: "google", error_category: "oauth" });
      setError(err instanceof Error ? err.message : "Google sign-up failed.");
      setOauthSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Create one portfolio, then move from today's priority to a testable risk plan."
      highlights={[
        "Add tickers and shares or import a supported CSV.",
        "Open Today to see the highest-priority risk first.",
        "Use Analyze to test a change without touching real holdings.",
      ]}
      footer={
        <>
          Already have one?{" "}
          <Link href={authHref("/login", redirectPath)} style={{ color: C.teal, textDecoration: "none" }}>
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
                <span className="font-mono">{email}</span>. Open it, then return to this original
                tab and{" "}
                <Link href={authHref("/login", redirectPath)} className="text-primary hover:underline">
                  sign in
                </Link>
                . This keeps your private portfolio handoff in this tab.
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

/** Coarse error CATEGORY for analytics — never the raw message (may echo the
 * email/password). */
function signupErrorCategory(err: unknown): string {
  const m = (err instanceof Error ? err.message : "").toLowerCase();
  if (/already registered|already exists|user already/.test(m)) return "already_registered";
  if (/password/.test(m)) return "weak_password";
  if (/email|valid/.test(m)) return "invalid_email";
  if (/rate|too many/.test(m)) return "rate_limited";
  if (/network|fetch|timeout/.test(m)) return "network";
  return "unknown";
}
