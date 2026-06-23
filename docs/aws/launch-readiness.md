# Launch-readiness playbook

> **Note (2026-06-23):** point-in-time checklist from 2026-06-04. Since then the
> legacy Streamlit tier was fully retired — the live stack is Next.js + FastAPI +
> Caddy only (no `/legacy`). Streamlit references below are historical. See
> CLAUDE.md §1B.

> Status (2026-06-04): the product is feature- and credibility-complete for a
> paid beta. The remaining work is **owner-gated** (systemd, DNS, Stripe keys) —
> none of it needs more code. This is the one-shot checklist to flip each
> switch. Do them in order; each is independent and reversible.

The agent does **not** touch EC2 `systemd` / `.env` / secrets / DNS — those are
your hands. Everything below is for you to run once.

---

## 1. Reboot-safe boot (the one real reliability landmine) — ~10 min

**Problem.** `systemd` unit `mindmarket.service` currently runs, on every boot:

```
ExecStartPre = git fetch + git reset --hard origin/main
ExecStart    = docker compose -f compose.aws.yml up -d --build
```

`compose.aws.yml --build` **rebuilds the legacy Streamlit `app` image on the
box**. A Streamlit/Python build needs >1 GB; the t3.micro has ~916 MB + a 1 GB
swapfile → a reboot can OOM the box (this is what downed the site twice). The
split `backend`/`frontend`/`caddy`/`app` containers are all
`restart: unless-stopped`, so they already come back on reboot **without** a
build — the `--build` is the only thing that can hurt us.

(The `git reset --hard` is fine: origin/main's `Caddyfile` is byte-identical to
the live one, so routing is preserved. Verified 2026-06-04.)

**Fix — drop the on-box build.** Edit the unit so boot pulls the GHCR images
instead of building:

```bash
sudo systemctl edit --full mindmarket.service     # opens the unit
# Replace the ExecStart line with (no --build; pull the prebuilt images):
#   ExecStart=/bin/sh -c 'cd /home/ec2-user/PersonalFinancialRiskManagement && \
#     /usr/bin/docker compose -f compose.aws.yml up -d --no-build'
# (Leave ExecStartPre as-is.)
sudo systemctl daemon-reload
# Do NOT restart now to test — just verify it parses:
systemd-analyze verify mindmarket.service || true
```

Then confirm a dry sanity check (does NOT reboot):

```bash
docker compose -f compose.aws.yml config >/dev/null && echo "compose ok"
```

**Verify after your next real reboot:** `curl -sI https://mindmarket.app/` → 200,
and `docker ps` shows backend+frontend+caddy+app `Up (healthy)` with **no**
image rebuild in `journalctl -u mindmarket --since "5 min ago"`.

> Long-term clean fix (optional): publish the Streamlit image to GHCR too and
> point systemd at `compose.split.yml` with `pull` + `--no-build`, retiring
> `compose.aws.yml`. Not required for launch.

---

## 2. Cloudflare — CDN + DDoS + TLS — ~20 min

Protects the single t3.micro and speeds static assets. DNS change is yours
(Porkbun → Cloudflare nameservers, or add the zone in Cloudflare).

1. Cloudflare → **Add site** `mindmarket.app` (Free plan is fine to start).
2. Point the domain's nameservers at the two Cloudflare gave you (at Porkbun).
3. DNS: `A  @  52.71.140.252  (Proxied / orange cloud)`; same for `www` if used.
4. SSL/TLS mode: **Full (strict)** — Caddy already serves a valid Let's Encrypt
   cert, so strict works and is the secure choice.
5. **Caching — exclude the dynamic + streaming paths** (critical, or you'll
   cache API responses / break Copilot SSE). Add Cache Rules:
   - Bypass cache for `mindmarket.app/api/*`.
   - Bypass cache for `mindmarket.app/_stcore/*` (legacy Streamlit WS).
   - (Caddy already excludes `text/event-stream` from gzip; Cloudflare's bypass
     on `/api/*` covers the Copilot stream which lives under `/api/v1/copilot`.)
6. Leave HTML caching default (Cloudflare won't cache HTML without a rule).

**Verify:** `curl -sI https://mindmarket.app/` shows a `cf-ray` header; a Copilot
chat still streams token-by-token; `/api/v1/macro/regime` still returns fresh
JSON (not cached/stale).

---

## 3. Stripe Live cutover — your business decision — ~30 min

Currently **Test mode** (no real charges). Flipping to Live is config-only but
touches secrets — entirely your hands. Checklist:

1. In the Stripe **Live** dashboard, recreate the two products/prices
   (Basic $10/mo, Pro $25/mo) → note the new `price_live_…` IDs.
2. Rotate the secret key:
   - EC2: edit `.env` → `STRIPE_SECRET_KEY=sk_live_…` (was `sk_test_…`).
   - Supabase Edge Function secret: `supabase secrets set STRIPE_SECRET_KEY=sk_live_…`.
3. Update the price IDs wherever they're configured (EC2 `.env` /
   `secrets.toml` — the catalogue the pricing cards + Checkout read).
4. Re-register the webhook **in Live mode** → endpoint
   `https://byfpmmfduteajblqpuuw.supabase.co/functions/v1/stripe-webhook`,
   events: `checkout.session.completed`,
   `customer.subscription.{created,updated,deleted}`, `invoice.payment_failed`.
   Put the new `whsec_live_…` signing secret into Supabase secrets.
5. Redeploy the webhook function:
   `supabase functions deploy stripe-webhook --no-verify-jwt --use-api`.
6. Restart the backend so it picks up the new `.env`:
   `docker compose -f compose.split.yml up -d --no-deps --force-recreate backend`.

**Verify:** `/admin → System status → Run live checks` should show **Stripe:
Connected — live mode**. Do one real low-risk subscription end-to-end, then
cancel from the Customer Portal, and confirm the `subscriptions` row + plan
flip in Supabase.

> The owner-admin live check (`/admin`) now reports Stripe **test vs live** mode
> — use it to confirm the cutover took.

---

## 4. What to watch first (decide the *next* feature from data, not guesses)

Don't build more until these tell you where to. All already wired
(prod-only, privacy-safe — no tickers / $ leave the browser).

**PostHog funnel** (us.i.posthog.com): `signed_up → portfolio_created →
csv_imported → score_viewed → copilot_message_sent → return visit`. Watch:
- Biggest drop-off step → that's the next thing to fix.
- `markets_sentiment_viewed` / `risk_diagnosis_viewed` / `quant_tab_changed` /
  `scenario_shock_selected` → which of the new depth features actually get used.
- Return rate (do the trend sparklines / "what changed" bring people back?).

**Sentry**: any real 500s / frontend errors from live users (errors-only,
prod-only).

**Rule of thumb:** ship the fix for the worst funnel step; ignore features no
one touches even if they were fun to build.
