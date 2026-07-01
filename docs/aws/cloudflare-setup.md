# Cloudflare in front of EC2 — setup runbook

> Goal: put Cloudflare's network in front of the single t3.micro origin so the
> real IP is hidden, DDoS/L7 floods are absorbed at the edge, static assets are
> CDN-cached, and a WAF + edge rate-limiting protects the public endpoints —
> **zero application code changes, zero downtime**.
>
> Owner-executed: this touches the Cloudflare account, the Porkbun nameservers,
> and the AWS Security Group — none of which the agent can reach. Follow top to
> bottom; each step is reversible.

## Current state (what we're protecting)

| Thing | Value |
|-------|-------|
| Domain | `mindmarket.app` (registrar: Porkbun) |
| Origin | AWS EC2 **t3.micro**, Elastic IP `52.71.140.252` |
| TLS today | Caddy + Let's Encrypt (HTTP-01 on :80), config `Caddyfile` (the mounted, canonical file) |
| Risk | DNS A record exposes the real IP → anyone can bypass and flood the box directly; one small instance, RAM-bound (`next build` has OOM'd it before) |

The whole point: after this, public DNS resolves to **Cloudflare** IPs, the real
`52.71.140.252` is firewalled to accept 80/443 **only from Cloudflare**, so the
origin can no longer be hit directly.

---

## Step 1 — Add the site to Cloudflare (Free plan)

1. Sign up / log in at dash.cloudflare.com → **Add a site** → `mindmarket.app`.
2. Choose the **Free** plan (covers unmetered DDoS, CDN, basic WAF, 5 rate-limit
   rules — enough for now).
3. Cloudflare scans existing DNS records and shows two assigned **nameservers**
   (e.g. `xxx.ns.cloudflare.com`, `yyy.ns.cloudflare.com`). Note them.

## Step 2 — Set DNS records in Cloudflare (BEFORE switching nameservers)

In Cloudflare → **DNS** → make sure these exist, both **Proxied (orange cloud)**:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `mindmarket.app` (apex/`@`) | `52.71.140.252` | **Proxied** 🟧 |
| CNAME | `www` | `mindmarket.app` | **Proxied** 🟧 |

Orange cloud = traffic flows through Cloudflare (hides IP, enables WAF/CDN). Grey
cloud = DNS-only (no protection). Anything that must reach the origin directly
(none here) would be grey.

## Step 3 — Pick the TLS mode + origin certificate

Cloudflare → **SSL/TLS** → Overview → set encryption mode to **Full (Strict)**
(encrypted edge→origin, origin cert validated). Do **not** use Flexible (that
leaves edge→origin in plaintext).

Caddy's Let's Encrypt HTTP-01 renewal gets fragile once it's behind the proxy.
The clean, maintenance-free fix is a **Cloudflare Origin CA certificate** (free,
15-year) on the origin instead of Let's Encrypt:

1. Cloudflare → **SSL/TLS → Origin Server → Create Certificate** (default
   RSA, hostnames `mindmarket.app`, `*.mindmarket.app`). Save the **cert** and
   **private key** PEMs.
2. On EC2, drop them where Caddy can read them, e.g.
   `/srv/tls/origin.pem` + `/srv/tls/origin.key`, and mount that dir into the
   caddy service in `compose.aws.yml` (caddy's canonical compose file).
3. In the live `Caddyfile`, pin the cert so Caddy stops trying to issue via
   ACME — replace the automatic-TLS site with an explicit `tls`:

   ```caddyfile
   {$SITE_HOST}, www.{$SITE_HOST} {
       tls /srv/tls/origin.pem /srv/tls/origin.key   # Cloudflare Origin CA (15yr)
       encode gzip
       # … rest of the config unchanged …
   }
   ```

   > Alternative if you'd rather keep Let's Encrypt: leave TLS automatic and make
   > sure the Security Group (Step 4) allows Cloudflare on **:80** so the HTTP-01
   > challenge can still reach the origin. The Origin CA path above avoids ACME
   > behind the proxy entirely and is the recommended one.

## Step 4 — Lock the AWS Security Group to Cloudflare only

This is the step that actually makes hiding the IP meaningful. EC2 → Security
Groups → the instance's SG → **Inbound rules**. Replace the open
`0.0.0.0/0` rules on 80/443 with the Cloudflare ranges below (HTTPS 443 is what
Full-Strict uses; add 80 too if you kept Let's Encrypt).

**Cloudflare IPv4** (verify against <https://www.cloudflare.com/ips-v4/> — they
change rarely):

```
173.245.48.0/20    103.21.244.0/22    103.22.200.0/22    103.31.4.0/22
141.101.64.0/18    108.162.192.0/18   190.93.240.0/20    188.114.96.0/20
197.234.240.0/22   198.41.128.0/17    162.158.0.0/15     104.16.0.0/13
104.24.0.0/14      172.64.0.0/13      131.0.72.0/22
```

**Cloudflare IPv6** (<https://www.cloudflare.com/ips-v6/>):

```
2400:cb00::/32   2606:4700::/32   2803:f800::/32   2405:b500::/32
2405:8100::/32   2a06:98c0::/29   2c0f:f248::/32
```

- **Keep SSH (:22) restricted to your own IP** — unchanged, never open to
  Cloudflare/world.
- Tip: a managed prefix list keeps this list maintainable, but plain SG rules are
  fine to start. Cloudflare also publishes the list as JSON for automation.

## Step 5 — Switch nameservers at Porkbun

Porkbun → `mindmarket.app` → **Authoritative Nameservers** → replace Porkbun's
with the two Cloudflare nameservers from Step 1. Propagation: minutes to a few
hours. Cloudflare emails you when the zone goes **Active**.

> Do this only after Steps 2–4 are in place, so when DNS cuts over the records +
> firewall are already correct.

## Step 6 — Make Caddy log the real client IP (after cutover)

Once proxied, every request arrives from a Cloudflare IP. Cloudflare passes the
real client IP in `CF-Connecting-IP` (and appends to `X-Forwarded-For`). The
backend (uvicorn `--proxy-headers`) already reads `X-Forwarded-For`, which
Cloudflare populates with the true client — so app-level logic is unaffected.
To fix **Caddy's own access logs**, add a global options block at the top of
the live `Caddyfile` (the mounted, canonical routing file — validate with
ci.yml's `validate-config` job / `caddy validate` before reloading):

```caddyfile
{
    servers {
        client_ip_headers CF-Connecting-IP
        # Trust only Cloudflare to set that header (same ranges as Step 4):
        trusted_proxies static 173.245.48.0/20 103.21.244.0/22 103.22.200.0/22 \
            103.31.4.0/22 141.101.64.0/18 108.162.192.0/18 190.93.240.0/20 \
            188.114.96.0/20 197.234.240.0/22 198.41.128.0/17 162.158.0.0/15 \
            104.16.0.0/13 104.24.0.0/14 172.64.0.0/13 131.0.72.0/22 \
            2400:cb00::/32 2606:4700::/32 2803:f800::/32 2405:b500::/32 \
            2405:8100::/32 2a06:98c0::/29 2c0f:f248::/32
    }
}
```

Then reload Caddy (config-only, no rebuild):

```bash
docker exec personalfinancialriskmanagement-caddy-1 \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec personalfinancialriskmanagement-caddy-1 \
  caddy reload   --config /etc/caddy/Caddyfile --adapter caddyfile
```

## Step 7 — Edge protections (free tier)

In Cloudflare:

- **SSL/TLS → Edge Certificates**: turn on *Always Use HTTPS* + *Automatic HTTPS
  Rewrites*; min TLS 1.2.
- **Caching**: leave default; static Next.js assets (`/_next/static/*`,
  fonts, images) cache automatically. Don't cache `/api/v1/*` (dynamic) — add a
  Cache Rule `Bypass cache` for `/api/v1/*` if needed.
- **Security → WAF → Rate limiting rules** (Free = up to 5): start with one on
  the public, un-authed endpoints that today only have per-user quota:
  - Match: `http.request.uri.path` starts with `/api/v1/market/` **or**
    `/api/v1/macro/`
  - Threshold: e.g. **60 requests / 10s per IP** → action **Block** (tune later).
  This closes the "anonymous preview has no IP-level throttle" gap with no
  backend change.
- **Security → Bots**: enable *Bot Fight Mode* (free).

## Step 8 — Verify

```bash
# DNS now resolves to Cloudflare, not the origin IP:
dig +short mindmarket.app            # expect Cloudflare IPs (104.x / 172.x …), NOT 52.71.140.252

# Site still serves the Next.js app through the proxy:
curl -sI https://mindmarket.app/ | grep -i -E 'server|cf-ray'   # expect a `cf-ray:` header

# Origin is NO LONGER reachable directly (the key proof):
curl -sI --max-time 8 https://52.71.140.252/ -k                 # expect timeout / refused

# API + app still route correctly through Cloudflare:
curl -sI https://mindmarket.app/api/v1/health          # expect 200
curl -sI https://mindmarket.app/                       # expect 200 (Next.js)
# (the /legacy/* Streamlit routes were retired 2026-06-23 — a /legacy/ curl
#  now returns the Next.js 404, which is correct)
```

Also confirm in Cloudflare → Analytics that requests are flowing, and that Caddy
logs now show real client IPs (Step 6).

## Rollback (fast)

Any single one of these reverts the change:

- **Per-record**: in Cloudflare DNS, flip the apex/`www` records to **grey cloud**
  (DNS-only) → traffic goes straight to origin again (IP re-exposed but site up).
- **Full**: at Porkbun, switch nameservers back to Porkbun's → DNS leaves
  Cloudflare entirely (takes propagation time).
- **Firewall**: if the origin becomes unreachable through Cloudflare, temporarily
  re-open 443 to `0.0.0.0/0` on the Security Group while you debug.

> If you locked the SG to Cloudflare-only AND switch DNS to grey cloud, remember
> to also re-open the SG, or direct traffic will be blocked.

---

## Notes / caveats specific to this stack

- **Let's Encrypt vs Origin CA**: the Origin CA path (Step 3) is recommended so
  ACME renewal isn't happening behind the proxy. If you keep Let's Encrypt, the SG
  **must** allow Cloudflare on :80 and Cloudflare must not cache
  `/.well-known/acme-challenge/*`.
- **Reboot behaviour**: unrelated to Cloudflare, but recall the box reverts Caddy
  routing on reboot (see `docs/aws/operations.md` / CLAUDE.md). The Cloudflare
  edge keeps absorbing traffic regardless; only origin routing needs the usual
  post-reboot fix.
- **Cost**: Free plan is sufficient for launch. Pro ($20/mo) adds image
  optimization, more page/WAF rules, and better analytics — revisit after traffic
  grows.
