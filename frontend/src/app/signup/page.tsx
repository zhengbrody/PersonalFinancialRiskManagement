"use client";

/**
 * Email + password sign-up against Supabase.
 *
 * On success:
 *   * If Supabase project has email confirmation ON → show "check your
 *     email" copy. User clicks confirm link, lands on /login.
 *   * If auto-confirm is on → session is attached immediately, redirect
 *     to /portfolios.
 *
 * Phase 6 scope: email + password only. Google OAuth lands in a
 * later phase once the Supabase redirect URL is wired to the
 * production hostname.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth-context";

const POST_SIGNUP_REDIRECT = "/portfolios";

export default function SignupPage() {
  const router = useRouter();
  const { user, configured, loading: authLoading, signUp } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
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
      if (needsConfirmation) {
        setConfirmationSent(true);
        return;
      }
      router.replace(POST_SIGNUP_REDIRECT);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-up failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <CardHeader>
          <CardTitle>Create your account</CardTitle>
          <CardDescription>
            Free during beta. Already have one?{" "}
            <Link href="/login" className="text-primary hover:underline">
              Sign in
            </Link>
            .
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!configured ? (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm">
              Supabase is not configured on this build. Set{" "}
              <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> +{" "}
              <code className="font-mono">NEXT_PUBLIC_SUPABASE_ANON_KEY</code>{" "}
              and rebuild.
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
                <p className="text-[11px] text-muted-foreground">
                  At least 8 characters.
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
