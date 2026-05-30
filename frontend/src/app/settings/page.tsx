"use client";

/**
 * /settings — authed page. Shows the user's current plan + Stripe
 * subscription summary and offers a single button to open the Stripe
 * Customer Portal where they manage card, plan switch, cancel, etc.
 *
 * No portfolio management here yet — Phase 6's /portfolios is the
 * right home for that. This page is billing-only.
 */

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useBillingMe, useStartPortal } from "@/lib/queries";

export default function SettingsPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <SettingsPageInner />
    </Suspense>
  );
}

function SettingsPageInner() {
  const router = useRouter();
  const search = useSearchParams();
  const { user, loading: authLoading, configured } = useAuth();
  const billing = useBillingMe();
  const portal = useStartPortal();

  useEffect(() => {
    if (!configured) return;
    if (!authLoading && !user) router.replace("/login");
  }, [user, authLoading, configured, router]);

  if (!configured || authLoading || !user || billing.isLoading) {
    return <PageSkeleton />;
  }

  if (billing.isError) {
    return (
      <ErrorPanel error={billing.error as Error} title="Could not load billing" />
    );
  }

  const me = billing.data!;
  const isPaid = me.plan === "basic" || me.plan === "pro";
  const justReturned = search.get("checkout") === "success";

  async function openPortal() {
    try {
      const { portal_url } = await portal.mutateAsync();
      window.location.href = portal_url;
    } catch {
      /* error surfaces via portal.error below */
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          GET /api/v1/billing/me
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Signed in as <span className="font-mono">{me.email ?? me.user_id}</span>.
        </p>
      </header>

      {justReturned && (
        <Card className="border-primary/30">
          <CardHeader>
            <CardTitle className="text-base">Welcome to your new plan</CardTitle>
            <CardDescription>
              Your subscription is being provisioned — refresh in a few
              seconds if the badge below still says Free.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Current plan */}
      <Card>
        <CardHeader>
          <CardTitle>Current plan</CardTitle>
          <CardDescription>
            Plan and quota are synced via the Stripe webhook into the
            Supabase profiles table.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">Plan</span>
            <span className="rounded-full border border-primary/40 bg-primary/10 px-3 py-1 text-xs font-medium uppercase tracking-wide text-primary">
              {me.plan}
            </span>
          </div>
          {me.subscription && (
            <div className="grid grid-cols-2 gap-3 text-xs">
              <Field label="Status" value={me.subscription.status ?? "—"} />
              <Field
                label="Renews"
                value={me.subscription.current_period_end ?? "—"}
              />
              <Field
                label="Stripe customer"
                value={me.subscription.stripe_customer_id ?? "—"}
                mono
              />
              <Field
                label="Stripe subscription"
                value={me.subscription.stripe_subscription_id ?? "—"}
                mono
              />
              <Field
                label="Cancels at period end"
                value={
                  me.subscription.cancel_at_period_end ? "yes" : "no"
                }
              />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Action: portal or upgrade */}
      <Card>
        <CardHeader>
          <CardTitle>
            {isPaid ? "Manage subscription" : "Upgrade your plan"}
          </CardTitle>
          <CardDescription>
            {isPaid
              ? "Card, invoices, plan switch, and cancel all live in Stripe's hosted portal."
              : "Go to the pricing page to subscribe — checkout is handled by Stripe."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isPaid ? (
            <Button
              type="button"
              onClick={openPortal}
              disabled={portal.isPending}
            >
              {portal.isPending ? "Opening…" : "Open Stripe Portal"}
            </Button>
          ) : (
            <Link href="/pricing">
              <Button type="button">Compare paid plans</Button>
            </Link>
          )}
          {portal.isError && (
            <p className="mt-3 text-sm text-destructive">
              {(portal.error as Error)?.message ?? "Could not open the portal."}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="space-y-1">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className={mono ? "font-mono text-xs" : "text-xs"}>{value}</p>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="h-40" />
      <Skeleton className="h-32" />
    </div>
  );
}

function ErrorPanel({ error, title }: { error: Error; title: string }) {
  const isApi = error instanceof ApiError;
  return (
    <Card className="border-destructive/50">
      <CardHeader>
        <CardTitle className="text-destructive">{title}</CardTitle>
        {isApi && (
          <CardDescription className="font-mono text-xs">
            {error.status} · {error.code}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <p className="text-sm">{error.message}</p>
      </CardContent>
    </Card>
  );
}
