# Stripe Webhook — Supabase Edge Function

Syncs Stripe subscription state into Postgres so the app's quota layer
(`libs/billing/usage.py` → `profiles.plan`) reflects what users actually
paid for.

## What it does

Receives Stripe webhook events, verifies the signature, and writes to:
- `public.subscriptions` — full Stripe state (customer_id, sub_id, period, status)
- `public.profiles.plan` — mirrored plan tier (so quota reads stay one-table cheap)

Handled events:
- `checkout.session.completed` — first paid checkout
- `customer.subscription.created` / `updated` — plan change, cancel toggle
- `customer.subscription.deleted` — sub ended
- `invoice.payment_failed` — card decline (marks `past_due`)

## Deploy (one-time setup)

### 1. Install the Supabase CLI
```bash
brew install supabase/tap/supabase
supabase login         # opens browser
```

### 2. Link the local repo to your Supabase project
```bash
# From repo root. Find your <project-ref> in Supabase dashboard URL:
# https://supabase.com/dashboard/project/<project-ref>
supabase link --project-ref <project-ref>
```

### 3. Set the function's secrets
```bash
# Stripe secret key (sk_test_... in test mode, sk_live_... in prod)
supabase secrets set STRIPE_SECRET_KEY=sk_test_xxx

# Stripe webhook signing secret — generated in step 5 below.
# You'll come back and set this once the webhook endpoint is created.
supabase secrets set STRIPE_WEBHOOK_SIGNING_SECRET=whsec_xxx

# Stripe price IDs — same as the Streamlit app uses. Found in Stripe
# Dashboard → Products → click product → copy the price's ID
# (starts with `price_...`).
supabase secrets set STRIPE_BASIC_PRICE_ID=price_xxx
supabase secrets set STRIPE_PRO_PRICE_ID=price_xxx

# SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are auto-injected by the
# Edge runtime — you do NOT need to set them.
```

### 4. Deploy the function
```bash
# --no-verify-jwt is REQUIRED because Stripe doesn't send a Supabase JWT.
# We authenticate the request via Stripe's own signature instead.
supabase functions deploy stripe-webhook --no-verify-jwt
```

The function URL will be:
```
https://<project-ref>.supabase.co/functions/v1/stripe-webhook
```

### 5. Register the URL in Stripe

1. Go to https://dashboard.stripe.com/test/webhooks (or `/webhooks` for live)
2. Click **+ Add endpoint**
3. **Endpoint URL**: paste the function URL from step 4
4. **Events to send** — select:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
5. Click **Add endpoint**
6. On the endpoint detail page, **Reveal** the **Signing secret** (`whsec_...`)
7. Set it as the secret you stubbed in step 3:
   ```bash
   supabase secrets set STRIPE_WEBHOOK_SIGNING_SECRET=whsec_xxx_from_dashboard
   ```
8. Re-deploy so the function picks up the new secret:
   ```bash
   supabase functions deploy stripe-webhook --no-verify-jwt
   ```

## Test

In the Stripe Dashboard webhook page, click **Send test webhook** and
pick `checkout.session.completed`. The function should return 200 and
you'll see a log entry in Supabase Dashboard → Edge Functions → stripe-webhook → Logs.

End-to-end test:
```bash
# Use Stripe's CLI to forward live events to a local test deploy:
stripe trigger checkout.session.completed
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| 400 "Bad signature" | Wrong `STRIPE_WEBHOOK_SIGNING_SECRET` | Copy from Dashboard; re-deploy |
| 500 "Handler error" | Likely RLS or schema mismatch | Check function logs in Supabase Dashboard |
| Event received but plan didn't update | Missing `user_id` in subscription metadata | The app sets it in `libs/billing/stripe_checkout.py`; verify checkout sessions include `client_reference_id` |
| Multiple firings on one payment | Stripe retries on 5xx — that's intentional | The handlers are idempotent (UPSERT keyed by user_id) so duplicates converge |
