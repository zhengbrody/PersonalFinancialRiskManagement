"use client";

/**
 * AI Portfolio Copilot — the full-page chat.
 *
 * This route is a thin shell: an auth gate (same client-side pattern as
 * /portfolios — skeleton while the Supabase session probes, redirect to
 * /login when signed out) + a header, wrapped around the shared
 * <CopilotConversation /> that owns ALL the chat logic. The exact same
 * conversation component powers the app-wide floating widget, so there
 * is a single source of truth for message-state, send logic, grounded
 * facts, draft trades, the "Thinking…" skeleton and friendly errors.
 */

import { useEffect } from "react";
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
import { Skeleton } from "@/components/ui/skeleton";
import { CopilotConversation } from "@/components/copilot-conversation";
import { CopilotAsk } from "@/components/copilot-ask";
import { useAuth } from "@/lib/auth-context";
import { useBillingMe } from "@/lib/queries";

export default function CopilotPage() {
  const router = useRouter();
  const { user, loading: authLoading, configured } = useAuth();
  const billing = useBillingMe();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, configured, router]);

  if (!configured) {
    return <ConfigureSupabaseNotice />;
  }

  if (authLoading || !user) {
    return <PageSkeleton />;
  }

  const planLabel = billing.data?.plan;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-3xl font-semibold tracking-tight">
            Portfolio Copilot
          </h1>
          {planLabel && (
            <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              {planLabel}
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          Ask anything about your portfolio in plain English. Your Copilot
          explains the risk first — the hard numbers are always one tap away.
        </p>
      </header>

      <CopilotAsk />

      <CopilotConversation variant="page" />
    </div>
  );
}

function ConfigureSupabaseNotice() {
  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle>Supabase not configured</CardTitle>
        <CardDescription>
          The Copilot needs an authenticated Supabase session.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Set <code className="font-mono">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code className="font-mono">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in{" "}
          <code className="font-mono">.env.local</code>, then restart the dev
          server.
        </p>
        <Link href="/score">
          <Button variant="outline">Try the public /score demo</Button>
        </Link>
      </CardContent>
    </Card>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-40 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  );
}
