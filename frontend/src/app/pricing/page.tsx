"use client";

/**
 * Public pricing page. Lists Free / Basic / Pro tiers from the
 * backend (single source of truth: PLAN_PRICING + PLAN_LIMITS in
 * libs/billing/usage.py). The "Subscribe" buttons redirect the user
 * to Stripe Checkout via the backend's /billing/checkout_session.
 *
 * Anonymous visitors see the table but the Subscribe buttons route
 * them to /signup first.
 */

import { Suspense, useEffect, useState } from "react";
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
import {
  type PlanCard,
  useBillingMe,
  useStartCheckout,
} from "@/lib/queries";

export default function PricingPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PricingPageInner />
    </Suspense>
  );
}

function PricingPageInner() {
  const router = useRouter();
  const search = useSearchParams();
  const { user, accessToken, loading: authLoading } = useAuth();
  const billing = useBillingMe();
  const checkout = useStartCheckout();
  const [error, setError] = useState<string | null>(null);

  // Stripe redirected back here with ?checkout=cancelled — show a
  // friendly notice (the backend's default cancel_url).
  const checkoutBanner = search.get("checkout");

  useEffect(() => {
    // Surface the mutation's own error in a stable place rather than
    // alerting per click.
    if (checkout.error) {
      setError((checkout.error as Error).message);
    }
  }, [checkout.error]);

  const plans: PlanCard[] = billing.data?.plans ?? FALLBACK_PLANS;
  const currentPlan = billing.data?.plan ?? null;

  async function onSubscribe(plan: "basic" | "pro") {
    setError(null);
    // Anonymous → send through signup first, return here.
    if (!accessToken) {
      router.push("/signup");
      return;
    }
    try {
      const { checkout_url } = await checkout.mutateAsync({ plan });
      // External redirect; Stripe handles everything from here.
      window.location.href = checkout_url;
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.code === "billing_not_configured"
            ? "Billing is not enabled on this build."
            : err.code === "email_required"
              ? "Sign in with email + password before subscribing."
              : err.message
          : (err as Error)?.message ?? "Could not start checkout.";
      setError(msg);
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <header className="space-y-2 text-center">
        <p className="text-xs font-medium uppercase tracking-widest text-primary">
          GET /api/v1/billing/me
        </p>
        <h1 className="text-4xl font-semibold tracking-tight">
          Simple pricing
        </h1>
        <p className="text-sm text-muted-foreground">
          Built on real quant + real market data. Cancel any time from
          Settings.
        </p>
      </header>

      {checkoutBanner === "cancelled" && (
        <Card className="border-warning/30">
          <CardHeader>
            <CardTitle className="text-base">Checkout cancelled</CardTitle>
            <CardDescription>
              You can resume any time — your free plan keeps working.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {error && (
        <Card className="border-destructive/50">
          <CardHeader>
            <CardTitle className="text-base text-destructive">
              Could not start checkout
            </CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((p) => (
          <PlanColumn
            key={p.plan}
            plan={p}
            isCurrent={currentPlan === p.plan}
            disabled={checkout.isPending || authLoading}
            onSubscribe={() => {
              if (p.plan === "basic" || p.plan === "pro") {
                onSubscribe(p.plan);
              }
            }}
            anonymous={!user}
          />
        ))}
      </div>

      <p className="text-center text-xs text-muted-foreground">
        Already paying?{" "}
        <Link href="/settings" className="text-primary hover:underline">
          Manage subscription
        </Link>
        .
      </p>
    </div>
  );
}

function PlanColumn({
  plan,
  isCurrent,
  disabled,
  onSubscribe,
  anonymous,
}: {
  plan: PlanCard;
  isCurrent: boolean;
  disabled: boolean;
  onSubscribe: () => void;
  anonymous: boolean;
}) {
  const isPaid = plan.plan === "basic" || plan.plan === "pro";

  return (
    <Card
      className={
        isCurrent
          ? "border-primary/60 ring-1 ring-primary/40"
          : plan.plan === "pro"
            ? "border-primary/30"
            : ""
      }
    >
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{plan.label}</CardTitle>
          {isCurrent && (
            <span className="rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
              current
            </span>
          )}
        </div>
        <p className="font-mono text-3xl">
          ${plan.price_usd_per_month}
          <span className="ml-1 text-xs text-muted-foreground">/mo</span>
        </p>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <Bullet>
          <span className="font-mono">{plan.monthly_credits ?? 0}</span> AI
          credits / month
        </Bullet>
        <Bullet>
          <span className="text-muted-foreground">
            ≈ {plan.monthly_chat} Copilot chats or {plan.monthly_analysis} deep
            analyses — heavier answers use more
          </span>
        </Bullet>
        <Bullet>Real market data + macro panel</Bullet>
        <Bullet>VaR / CVaR / factor analysis · scenarios · backtests</Bullet>
        {isPaid ? (
          <Button
            type="button"
            className="w-full"
            disabled={disabled || isCurrent}
            onClick={onSubscribe}
          >
            {isCurrent
              ? "Current plan"
              : anonymous
                ? "Sign up to subscribe"
                : `Subscribe to ${plan.label}`}
          </Button>
        ) : (
          <Button type="button" className="w-full" variant="outline" disabled>
            {isCurrent ? "Current plan" : "Free for everyone"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

function Bullet({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="mt-1 inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-primary" />
      <span>{children}</span>
    </div>
  );
}

function PageSkeleton() {
  return (
    <div className="mx-auto max-w-5xl space-y-8">
      <Skeleton className="mx-auto h-12 w-96" />
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  );
}

// Static fallback used while the /billing/me query loads. Mirrors
// libs/billing/usage.py:PLAN_PRICING + PLAN_LIMITS so the layout
// doesn't reflow on data arrival.
const FALLBACK_PLANS: PlanCard[] = [
  {
    plan: "free",
    label: "Free",
    price_usd_per_month: 0,
    monthly_analysis: 2,
    monthly_chat: 2,
    monthly_credits: 25,
  },
  {
    plan: "basic",
    label: "Basic",
    price_usd_per_month: 10,
    monthly_analysis: 30,
    monthly_chat: 100,
    monthly_credits: 300,
  },
  {
    plan: "pro",
    label: "Pro",
    price_usd_per_month: 25,
    monthly_analysis: 100,
    monthly_chat: 300,
    monthly_credits: 800,
  },
];
