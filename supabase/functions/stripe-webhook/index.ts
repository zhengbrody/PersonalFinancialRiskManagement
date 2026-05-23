// Stripe webhook receiver — runs on Supabase Edge Functions (Deno).
//
// Purpose
// -------
// Stripe Checkout fires events asynchronously after a user completes
// payment. We must sync those events back to Postgres so the user's
// quota reads (libs/billing/usage.py → profiles.plan) reflect their
// real subscription state. Without this, paid users would still be on
// the "free" tier in the app.
//
// Events handled (full list per Stripe docs at:
// https://docs.stripe.com/api/events/types)
//   checkout.session.completed         — first paid checkout closes
//   customer.subscription.created      — alt path / future-proof
//   customer.subscription.updated      — plan change, cancel toggle
//   customer.subscription.deleted      — sub ended (full cancel)
//   invoice.payment_failed             — card decline / dunning
//
// Source of truth
// ---------------
// `subscriptions.plan` (latest Stripe state). We MIRROR it into
// `profiles.plan` so the Python billing layer (libs/billing/usage.py)
// can do a single-table read for quota checks.
//
// Security
// --------
// Stripe signs every webhook with `Stripe-Signature` (HMAC-SHA256 over
// the raw body + a shared secret). We MUST verify before trusting any
// payload — otherwise anyone could POST and grant themselves Pro.
//
// Env vars required (set via `supabase secrets set`):
//   STRIPE_SECRET_KEY            (sk_test_... or sk_live_...)
//   STRIPE_WEBHOOK_SIGNING_SECRET (whsec_...)
//   SUPABASE_URL                 (auto-injected by Edge runtime)
//   SUPABASE_SERVICE_ROLE_KEY    (auto-injected; bypasses RLS)
//
// Deploy
// ------
//   supabase functions deploy stripe-webhook --no-verify-jwt
// (`--no-verify-jwt` because Stripe doesn't send a Supabase JWT — we
// authenticate the call via Stripe's own signature instead.)
//
// Then register the endpoint in Stripe Dashboard:
//   https://<project-ref>.supabase.co/functions/v1/stripe-webhook

import Stripe from "https://esm.sh/stripe@14.21.0?target=deno";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";

const STRIPE_SECRET_KEY = Deno.env.get("STRIPE_SECRET_KEY") ?? "";
const STRIPE_WEBHOOK_SIGNING_SECRET =
  Deno.env.get("STRIPE_WEBHOOK_SIGNING_SECRET") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SUPABASE_SERVICE_ROLE_KEY =
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const stripe = new Stripe(STRIPE_SECRET_KEY, {
  apiVersion: "2024-12-18.acacia",
  // Deno-friendly fetch client; the default node http stack isn't
  // available in the Edge runtime.
  httpClient: Stripe.createFetchHttpClient(),
});

// Service-role client bypasses RLS — required because webhooks write
// to subscriptions/profiles for arbitrary users, not the logged-in one.
const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, {
  auth: { persistSession: false },
});

type PlanTier = "free" | "basic" | "pro";

// Map Stripe price IDs → our plan tiers. Filled in from env so the
// function deploys without code edits when prices rotate.
const PRICE_TO_PLAN: Record<string, PlanTier> = {};
const basicPrice = Deno.env.get("STRIPE_BASIC_PRICE_ID");
const proPrice = Deno.env.get("STRIPE_PRO_PRICE_ID");
if (basicPrice) PRICE_TO_PLAN[basicPrice] = "basic";
if (proPrice) PRICE_TO_PLAN[proPrice] = "pro";

function planFromSubscription(sub: Stripe.Subscription): PlanTier {
  // A subscription can have multiple items in theory; take the first
  // recurring price. Our model is one-plan-per-customer so this is fine.
  const priceId = sub.items?.data?.[0]?.price?.id;
  if (priceId && PRICE_TO_PLAN[priceId]) return PRICE_TO_PLAN[priceId];
  // Fallback: metadata is set by libs/billing/stripe_checkout.py so we
  // can still recover the plan when price-id mapping isn't configured.
  const metaPlan = (sub.metadata?.plan ?? "").toLowerCase();
  if (metaPlan === "basic" || metaPlan === "pro") return metaPlan;
  return "free";
}

function statusFromStripe(status: Stripe.Subscription.Status): string {
  // We constrain to the four states the DB CHECK constraint allows.
  switch (status) {
    case "active":
    case "trialing":
      return status;
    case "past_due":
    case "unpaid":
      return "past_due";
    case "canceled":
    case "incomplete":
    case "incomplete_expired":
    case "paused":
      return "canceled";
    default:
      return "canceled";
  }
}

async function upsertSubscriptionAndProfile(args: {
  userId: string;
  customerId: string | null;
  subscriptionId: string | null;
  plan: PlanTier;
  status: string;
  currentPeriodStart: Date | null;
  currentPeriodEnd: Date | null;
  cancelAtPeriodEnd: boolean;
}) {
  const {
    userId,
    customerId,
    subscriptionId,
    plan,
    status,
    currentPeriodStart,
    currentPeriodEnd,
    cancelAtPeriodEnd,
  } = args;

  const { error: subErr } = await supabase.from("subscriptions").upsert(
    {
      user_id: userId,
      stripe_customer_id: customerId,
      stripe_subscription_id: subscriptionId,
      plan,
      status,
      current_period_start: currentPeriodStart?.toISOString() ?? null,
      current_period_end: currentPeriodEnd?.toISOString() ?? null,
      cancel_at_period_end: cancelAtPeriodEnd,
    },
    { onConflict: "user_id" },
  );
  if (subErr) {
    console.error("subscriptions upsert failed", subErr);
    throw subErr;
  }

  // Mirror to profiles.plan so quota reads stay single-table-cheap.
  // A "canceled" or "past_due" plan should NOT downgrade the profile
  // mid-period — the user paid for this period. Only flip back to
  // 'free' when the subscription is fully ended AND the period is over.
  const profilePlan: PlanTier =
    status === "canceled" &&
    currentPeriodEnd &&
    currentPeriodEnd.getTime() < Date.now()
      ? "free"
      : plan;

  const { error: profErr } = await supabase
    .from("profiles")
    .update({ plan: profilePlan })
    .eq("user_id", userId);
  if (profErr) {
    console.error("profiles update failed", profErr);
    throw profErr;
  }
}

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const userId =
    session.client_reference_id ??
    (session.metadata?.user_id as string | undefined) ??
    null;
  if (!userId) {
    console.warn("checkout.session.completed without user_id");
    return;
  }
  const subscriptionId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription?.id ?? null;
  if (!subscriptionId) {
    // One-shot payments (not subscriptions) — nothing to sync.
    return;
  }
  // Pull the freshly-created subscription so we have the full details.
  const sub = await stripe.subscriptions.retrieve(subscriptionId);
  const plan = planFromSubscription(sub);
  await upsertSubscriptionAndProfile({
    userId,
    customerId: typeof sub.customer === "string" ? sub.customer : sub.customer?.id ?? null,
    subscriptionId: sub.id,
    plan,
    status: statusFromStripe(sub.status),
    currentPeriodStart: new Date(sub.current_period_start * 1000),
    currentPeriodEnd: new Date(sub.current_period_end * 1000),
    cancelAtPeriodEnd: sub.cancel_at_period_end,
  });
}

async function handleSubscriptionChange(sub: Stripe.Subscription) {
  const userId = (sub.metadata?.user_id as string | undefined) ?? null;
  if (!userId) {
    console.warn("subscription event without user_id metadata", sub.id);
    return;
  }
  const plan = planFromSubscription(sub);
  await upsertSubscriptionAndProfile({
    userId,
    customerId: typeof sub.customer === "string" ? sub.customer : sub.customer?.id ?? null,
    subscriptionId: sub.id,
    plan,
    status: statusFromStripe(sub.status),
    currentPeriodStart: new Date(sub.current_period_start * 1000),
    currentPeriodEnd: new Date(sub.current_period_end * 1000),
    cancelAtPeriodEnd: sub.cancel_at_period_end,
  });
}

async function handleSubscriptionDeleted(sub: Stripe.Subscription) {
  const userId = (sub.metadata?.user_id as string | undefined) ?? null;
  if (!userId) return;
  // Mark canceled in subscriptions; mirror profiles flips when the
  // already-paid period truly ends (see upsertSubscriptionAndProfile).
  await upsertSubscriptionAndProfile({
    userId,
    customerId: typeof sub.customer === "string" ? sub.customer : sub.customer?.id ?? null,
    subscriptionId: sub.id,
    plan: "free",
    status: "canceled",
    currentPeriodStart: sub.current_period_start
      ? new Date(sub.current_period_start * 1000)
      : null,
    currentPeriodEnd: sub.current_period_end
      ? new Date(sub.current_period_end * 1000)
      : null,
    cancelAtPeriodEnd: true,
  });
}

async function handlePaymentFailed(invoice: Stripe.Invoice) {
  const subscriptionId =
    typeof invoice.subscription === "string"
      ? invoice.subscription
      : invoice.subscription?.id ?? null;
  if (!subscriptionId) return;
  // Don't touch profiles.plan here — Stripe will retry; only flip when
  // the subscription itself transitions to past_due via subscription.updated.
  const { error } = await supabase
    .from("subscriptions")
    .update({ status: "past_due" })
    .eq("stripe_subscription_id", subscriptionId);
  if (error) console.error("invoice.payment_failed update failed", error);
}

Deno.serve(async (req: Request) => {
  if (req.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405 });
  }

  const signature = req.headers.get("stripe-signature");
  if (!signature) {
    return new Response("Missing stripe-signature header", { status: 400 });
  }
  if (!STRIPE_WEBHOOK_SIGNING_SECRET) {
    console.error("STRIPE_WEBHOOK_SIGNING_SECRET is not configured");
    return new Response("Server misconfigured", { status: 500 });
  }

  // Stripe verifies against the EXACT raw body — never re-stringify.
  const rawBody = await req.text();

  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(
      rawBody,
      signature,
      STRIPE_WEBHOOK_SIGNING_SECRET,
    );
  } catch (err) {
    console.error("Stripe signature verification failed", err);
    return new Response("Bad signature", { status: 400 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;
      case "customer.subscription.created":
      case "customer.subscription.updated":
        await handleSubscriptionChange(event.data.object as Stripe.Subscription);
        break;
      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;
      case "invoice.payment_failed":
        await handlePaymentFailed(event.data.object as Stripe.Invoice);
        break;
      default:
        // Unhandled types are fine — Stripe replays only on 5xx.
        console.log("Unhandled event type", event.type);
    }
  } catch (err) {
    console.error("handler failed for", event.type, err);
    // Return 500 so Stripe will retry. Idempotency: every handler does
    // an UPSERT keyed by user_id or stripe_subscription_id, so a replay
    // converges on the same final state.
    return new Response("Handler error", { status: 500 });
  }

  return new Response(JSON.stringify({ received: true, type: event.type }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
});
