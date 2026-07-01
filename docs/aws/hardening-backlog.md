# Hardening backlog — business-ranked

> Ranked for the actual business goal (a trust-selling retail risk product,
> currently in free beta at ~0 traffic): **trust artifacts first** — uptime,
> data safety, recoverability. Scale work deliberately waits for traffic.
> Context: the 2026-07-01 deployment-audit pass (concurrency, CI config
> validation, log rotation, dep ceilings, DB-backup workflow, DR assets)
> already landed; this is what remains.

## Do next (trust artifacts — each is hours, not days)

1. **External uptime monitoring + alerting** *(owner-side, ~1h — highest value
   per hour of anything on this page).* UptimeRobot/BetterStack free tier:
   monitors on `https://mindmarket.app/` and
   `https://mindmarket.app/api/v1/health`, 5-min interval, email + phone push.
   Take the bundled free public **status page** — cheap credibility for a
   fintech. Today, if prod 500s at 2am, nothing tells anyone: Sentry only sees
   in-app exceptions (a dead container/Caddy/cert/CF-52x emits none), and the
   nightly e2e is ≤24h behind. Note: GitHub auto-disables cron workflows after
   60 days of repo inactivity — the external monitor keeps watching regardless.
2. **Test-restore the DB backup once** *(half-day).* `db-backup.yml` ships
   encrypted weekly dumps after the owner sets `SUPABASE_DB_URL` +
   `BACKUP_PASSPHRASE` secrets. An untested backup is a hope, not a control:
   restore one dump into a scratch Supabase project per the workflow header.
3. **Capture the live systemd unit into git** *(minutes, next SSH).*
   `sudo cat /etc/systemd/system/mindmarket.service` → diff against
   `deploy/mindmarket.service` → commit the verbatim copy (its header explains).
4. **Cloudflare Origin CA cert** *(owner-side, ~1-2h — runbook already in
   `cloudflare-setup.md`).* Kills the recurring ~60-day Let's Encrypt renewal
   dependency (a silent renewal failure darkens the origin on a timer). Apply
   behind the new `validate-config` CI gate + confirm SSL/TLS = Full (Strict).
5. **Deep readiness probe** *(small backend PR).* `GET /api/v1/health` is
   import-sanity only — containers stay "healthy" while every authed route
   401s or Supabase is down. Add `/api/v1/health?deep=1` (timeboxed ~2s
   Supabase REST ping + config-presence booleans, never key values) and point
   the external monitor's second check at it. Deliberately do NOT wire it into
   the compose healthcheck — a Supabase blip must not restart-loop containers.
6. **One-command remote deploy** *(~1 day).* `scripts/deploy-ec2.sh` (landed)
   already de-fangs the SSH ritual; the next step is a GH Actions workflow
   (SSM or SSH secret) running that script — deploys stop depending on one
   human's terminal. Do this before deploy frequency rises.

## Ready-to-apply snippets (deferred, deliberate)

- **Caddy: Cloudflare real client IP** — Caddy logs currently record CF edge
  IPs. The exact global block (`client_ip_headers CF-Connecting-IP` +
  `trusted_proxies static <CF ranges>`) is written out in
  `cloudflare-setup.md` Step 6. Observability-only today (no per-IP backend
  logic exists); apply together with #4, gated by `validate-config`.
- **Caddy: safe security headers** — `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`. Skip
  `X-Frame-Options: DENY` (would break the report-preview iframe), skip strict
  CSP (breaks Next/Supabase/Sentry/PostHog without report-only tuning), add
  HSTS only after confirming no plain-HTTP subdomain need — or set HSTS at the
  Cloudflare edge instead.
- **Caddy healthcheck in compose.aws.yml** — e.g.
  `test: ["CMD","wget","-q","--spider","http://localhost:2019/config/"]`.
  Note Docker does NOT restart merely-unhealthy containers; the external
  monitor (#1) is the real remediation trigger. Recreates the ingress
  container on next `up -d` — apply during a normal deploy window.
- **CloudWatch alarms on already-shipped metrics** *(owner-side).* The CW
  agent reports CPU/mem/disk to `MindMarket/EC2`, but the planned alarms were
  never created. SNS email + alarms: `disk_used_percent > 90`,
  `mem_used_percent > 90` (15m), `StatusCheckFailed_System` (+ auto-recover
  action). Free tier covers it. Disk/RAM creep is this box's signature
  failure mode — this is the pre-outage warning to #1's post-outage alert.
- **GHCR retention** — sha tags accumulate unboundedly (two per push, no
  cleanup workflow). Monthly `actions/delete-package-versions` keeping the
  last ~30 sha tags per image.

## Deliberately WAIT (≈0 traffic — revisit when it isn't)

- **Trivy image scanning / SBOM / provenance attestations** — no customers, no
  compliance ask; revisit at the first enterprise/compliance conversation.
- **Gate `latest` on green CI** (`workflow_run` chaining) — main is already
  PR-gated; the human pull-only deploy is the second gate. Revisit with
  automated deploys (#6).
- **Python constraints lockfile** — the ceilings added 2026-07-01 cover the
  drift class that actually bit prod. If more drift bites: a 10-minute
  `constraints.txt` (`pip freeze` from a green build) beats a pip-tools/uv
  migration.
- **Instance upsize / ECS / multi-AZ / k8s / Terraform / load testing** — a
  t3.micro behind Cloudflare serves orders of magnitude more than today's
  traffic. App tier is stateless (state = Supabase + Stripe), so the eventual
  scale-out is easy; buying it early buys nothing.
- **Stripe Live, `mindmarket.ai` domain** — owner-deferred; traffic-gated,
  not infra-gated.

## Open product-of-ops decisions

- **Retire or activate the Lambda experiment** — `deploy-services.yml`
  (deploy job `if: false` forever) + `services/` + `infra/` CDK. Either
  activate via an OIDC role or retire the workflow and archive the code; the
  interview/career story already lives in `docs/interview/`.

## Risk register (post-2026-07-01 state)

| Sev | Risk | State |
| --- | --- | --- |
| HIGH | No uptime alerting | **Open** → item #1 (owner, ~1h) |
| HIGH | DB backup never restore-tested | Mitigated by `db-backup.yml` once secrets set → item #2 |
| HIGH | On-box build → OOM | Guardrails procedural (`--no-build` in unit + script); structural fix impossible while `build:` blocks serve local dev |
| MED | Instance loss MTTR | Mitigated: `deploy/mindmarket.service` + `instance-rebuild.md` (verify unit copy, item #3) |
| MED | LE cert ~60-day renewal behind proxy | Open → item #4 (Origin CA) |
| MED | Shallow healthchecks (healthy ≠ working) | Open → item #5 |
| MED | Solo-owner deploy bus factor | Reduced by `deploy-ec2.sh`; automation is item #6 |
| MED | No CloudWatch alarms | Open (snippet above) |
| LOW | Caddyfile drift outage | **Closed** — `validate-config` CI job |
| LOW | `latest` tag race | **Closed** — build-images concurrency (serialized) |
| LOW | Log-storm disk fill | **Closed** — json-file caps in compose.split.yml |
| LOW | Dep major-version drift | **Closed** — ceilings in requirements.txt |
| LOW | Caddy silent auto-upgrade | **Closed** — pinned `caddy:2.11-alpine` |
| LOW | Backend sees CF IPs, not clients | Open (snippet above; no consumer today) |
| LOW | Cron workflows auto-disable after 60d inactivity | Documented; mitigated by external monitor (#1) |
| LOW | GHCR sha-tag accumulation | Open (snippet above) |
