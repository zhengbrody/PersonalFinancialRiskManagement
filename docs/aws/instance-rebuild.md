# Instance rebuild — from-scratch EC2 recovery runbook

> **Purpose.** If the production EC2 instance is terminated/corrupted, this
> checklist rebuilds it in ~1 hour. Without it, recovery means reconstructing
> the `.env` from ~8 provider dashboards and the systemd unit from session
> logs (realistic 4–12h). Everything user-data lives in **Supabase** (backed
> up by `.github/workflows/db-backup.yml`) — the box itself is stateless and
> fully rebuildable.

## What is NOT in git (the reason this runbook exists)

| Asset | Where it lives | Recovery |
| --- | --- | --- |
| `.env` (all secrets) | Box only | Rebuild from the key inventory below |
| `mindmarket.service` | Box + `deploy/mindmarket.service` (verbatim copy, captured 2026-07-01) | `sudo cp` from the repo |
| GHCR `docker login` | Box only | Re-login with a `read:packages` PAT |
| Let's Encrypt certs | `caddy_data` named volume | Auto-reissued by Caddy on first boot **if** DNS + SG are right (see step 8) |

## Fixed identifiers

- Elastic IP: `52.71.140.252` (survives instance loss; re-associate it)
- Security group: `sg-0dc3e94ea8cb95d8b` — 443/80 ← Cloudflare prefix lists
  (`pl-0527625cd846d43d7` v4, `pl-0232a98d6b2b6335b` v6), 22 ← operator IPs
- Region/AZ: `us-east-1` · AWS profile `mindmarket` (acct `520622116862`)
- Repo path on box: `/home/ec2-user/PersonalFinancialRiskManagement`

## Steps

1. **Launch** an AL2023 `t3.micro` (or `t3.small` if budget allows) in
   `us-east-1`, attach security group `sg-0dc3e94ea8cb95d8b`, key pair
   `mindmarket_aws`.
2. **Re-associate the Elastic IP** `52.71.140.252` to the new instance
   (EC2 → Elastic IPs → Associate). DNS/Cloudflare need no change — CF
   points at this IP.
3. **Base packages + swap** (the 1 GB swapfile is load-bearing on 916 MB RAM):
   ```bash
   sudo dnf install -y docker git
   sudo systemctl enable --now docker
   sudo usermod -aG docker ec2-user   # re-login afterwards
   # AL2023's docker package does NOT ship the compose v2 plugin, and every
   # runbook command + the boot unit use `docker compose`. (The live box runs
   # Compose v5.1.4 from this same cli-plugins path — verified 2026-07-01.)
   sudo mkdir -p /usr/local/lib/docker/cli-plugins
   sudo curl -fsSL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
   sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
   docker compose version   # verify
   sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
   sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   swapon --show   # verify
   ```
4. **Clone the repo:**
   ```bash
   cd ~ && git clone https://github.com/zhengbrody/PersonalFinancialRiskManagement.git
   cd PersonalFinancialRiskManagement
   ```
5. **GHCR login as ec2-user** (pull-only PAT with `read:packages`). The
   images are private; the boot unit runs as `User=ec2-user` (verbatim unit
   in `deploy/mindmarket.service`), so this single login covers both the
   boot-time pull and manual `scripts/deploy-ec2.sh` runs:
   ```bash
   echo <PAT> | docker login ghcr.io -u zhengbrody --password-stdin
   ```
6. **Rebuild `.env`** at the repo root from this inventory (values are NEVER
   in git — retrieve each from its dashboard; rotate anything you suspect):

   | Key | Where to retrieve the value |
   | --- | --- |
   | `SITE_HOST` | `mindmarket.app` (plain value) |
   | `MINDMARKET_ENV` | `production` (plain value) |
   | `MINDMARKET_OWNER_EMAIL` / `MINDMARKET_OWNER_EMAILS` | Owner's email(s) |
   | `MINDMARKET_APP_URL` | `https://mindmarket.app` |
   | `MINDMARKET_ALLOWED_ORIGINS` | Same origin list as before (app URL) |
   | `SUPABASE_URL` | Supabase dashboard → Settings → API |
   | `SUPABASE_ANON_KEY` | Supabase → Settings → API (publishable `sb_publishable_…`) |
   | `SUPABASE_SERVICE_KEY` | Supabase → Settings → API (service role — server-only) |
   | `SUPABASE_JWT_SECRET` | Supabase → Settings → API → JWT (legacy HS256 only) |
   | `FMP_API_KEY` | financialmodelingprep.com account |
   | `MASSIVE_API_KEY` | massive.com account (optional fallback) |
   | `STRIPE_SECRET_KEY` | Stripe dashboard (TEST mode while in free beta) |
   | `STRIPE_BASIC_PRICE_ID` / `STRIPE_PRO_PRICE_ID` | Stripe → Products |
   | `STRIPE_WEBHOOK_SECRET` | Stripe → Webhooks (Supabase Edge Function endpoint) |
   | `SENTRY_DSN` | Sentry → Project settings → Client keys |
   | `MINDMARKET_LLM_PROVIDER` | `deepseek` (current default) |
   | `DEEPSEEK_API_KEY` | platform.deepseek.com |
   | `ANTHROPIC_API_KEY` | console.anthropic.com |
   | `MASSIVE_BASE_URL` / `MASSIVE_EOD_PATH` / `MASSIVE_HISTORY_PATH` / `MASSIVE_REFERENCE_PATH`, `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | Optional overrides — normally unset (blank default = built-in behavior) |
   | `NEXT_PUBLIC_*` | GitHub repo → Settings → Variables (only needed on-box for a local build — which you never do; images carry them baked) |

7. **Install the boot unit + start the stack:**
   ```bash
   sudo cp deploy/mindmarket.service /etc/systemd/system/mindmarket.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now mindmarket.service
   # expect backend + frontend (healthy) and caddy Up within ~1 min
   # (caddy has no healthcheck — see docs/aws/hardening-backlog.md)
   docker ps
   ```
8. **TLS caveat:** the new `caddy_data` volume is empty, so Caddy re-issues
   the Let's Encrypt cert via HTTP-01 on `:80`. That works only because the
   SG admits Cloudflare on 80/443 and CF doesn't cache
   `/.well-known/acme-challenge/*`. If issuance loops, check
   `docker logs <caddy>` and Cloudflare SSL/TLS mode (Full). The permanent fix
   is a Cloudflare **Origin CA** cert (see `docs/aws/hardening-backlog.md`).
9. **Verify:**
   ```bash
   curl -sI https://mindmarket.app/ | head -3                 # 200 via CF
   curl -s https://mindmarket.app/api/v1/macro/regime | head  # real JSON
   sudo systemctl status mindmarket                           # active (exited), 0/SUCCESS
   swapon --show                                              # swap survived
   ```
10. **If user data was also lost** (Supabase incident): restore the latest
    encrypted dump per the RESTORE section in
    `.github/workflows/db-backup.yml`.
