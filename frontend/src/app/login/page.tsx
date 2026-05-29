"use client";

/**
 * Email + password sign-in against Supabase.
 *
 * Scope (Phase 3): no sign-up here — users register via the existing
 * Streamlit flow at mindmarket.app/Login; the Supabase user is shared.
 * Google OAuth lands in Phase 4 once we wire the redirect URL on the
 * Supabase project.
 *
 * Behaviour on success: redirect to `/portfolios`. The auth context
 * subscription will see the new session and surface the email in the
 * shell pill automatically.
 */

import { useEffect, useState } from "react";
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

const POST_LOGIN_REDIRECT = "/portfolios";

export default function LoginPage() {
  const router = useRouter();
  const { user, configured, loading: authLoading, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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

  return (
    <div className="mx-auto max-w-md py-12">
      <Card>
        <CardHeader>
          <CardTitle>Sign in</CardTitle>
          <CardDescription>
            Use your MindMarket account. New here?{" "}
            <a
              href="https://mindmarket.app"
              className="text-primary hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              Sign up on mindmarket.app
            </a>
            .
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!configured ? (
            <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm">
              Supabase is not configured on this build. Set{" "}
              <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
              <code className="font-mono">NEXT_PUBLIC_SUPABASE_ANON_KEY</code>{" "}
              in <code className="font-mono">.env.local</code>, then restart{" "}
              <code className="font-mono">npm run dev</code>.
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}
