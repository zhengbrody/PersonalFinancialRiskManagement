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
2. **Test-restore the DB backup** — now AUTOMATED as
   `.github/workflows/db-restore-drill.yml` (dispatch-only): downloads the
   latest backup artifact, decrypts with the same secret, restores into a
   throwaway Postgres 17 on the runner, asserts core tables + prints row
   counts. Secrets were set + first backup succeeded 2026-07-01. Re-run the
   drill after schema migrations and quarterly (cron workflows auto-disable
   after 60 days of repo inactivity — dispatch is deliberate).
3. ~~**Capture the live systemd unit into git**~~ **DONE 2026-07-01** —
   `deploy/mindmarket.service` is now the verbatim on-box unit (runs as
   `User=ec2-user`, so the ec2-user GHCR login covers boot pulls). Swap
   persistence also verified the same session (`/swapfile` in fstab).
4. ~~**Cloudflare Origin CA cert**~~ **DONE 2026-07-02** — 15-year cert
   (expires 2041) live at `/srv/tls`, pinned in the Caddyfile, CI-validated
   with a dummy pair. The ~60-day LE renewal timer is gone; port 80 no longer
   needed for ACME (optional follow-up: drop :80 from the SG).
5. ~~**Deep readiness probe**~~ **DONE 2026-07-17** — `GET /api/v1/health?deep=1`
   (timeboxed 2s Supabase REST ping + config-presence booleans + core-module
   check; 503 when a REQUIRED check fails; never a key value). Deliberately
   NOT in the compose healthcheck (a Supabase blip must not restart-loop
   containers) — point the external monitor's second check at it.
6. ~~**One-command remote deploy**~~ **DONE 2026-07-17 (activation owner-side)**
   — `.github/workflows/deploy-ec2.yml`: dispatch with a full main sha →
   validates ancestry + GHCR manifests → runs `scripts/deploy-ec2.sh` on the
   box via SSM (no inbound SSH) → verifies 6 public URLs incl. deep health.
   Fails with the exact missing secret names until the owner creates
   `AWS_DEPLOY_ACCESS_KEY_ID` / `AWS_DEPLOY_SECRET_ACCESS_KEY` (IAM scoped to
   ssm:SendCommand + ssm:GetCommandInvocation on the instance).

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
- **CloudWatch alarms** — now CODE: `scripts/cloudwatch-alarms.sh` (2026-07-17)
  creates the SNS topic + the three alarms (`disk_used_percent > 90`,
  `mem_used_percent > 90` 15m, `StatusCheckFailed_System` + auto-recover),
  discovering the CW-agent's live dimension sets so a rebuilt host still
  binds. *Owner runs it once* (`./scripts/cloudwatch-alarms.sh you@email`,
  `mindmarket` profile) + confirms the SNS subscription email.
- ~~**GHCR retention**~~ **DONE 2026-07-17** — `.github/workflows/
  ghcr-retention.yml` (monthly + dispatch) keeps the newest 30 versions per
  image via `actions/delete-package-versions`.

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

- ~~**Retire or activate the Lambda experiment**~~ **RETIRED 2026-07-17** —
  `deploy-services.yml` + `services/` + `libs/remote_compute.py` (+ its test)
  deleted after a reference-graph audit confirmed zero production / recovery /
  test consumers; story archived in `docs/archive/lambda-experiment.md`
  (recoverable from git history). `infra/` CDK KEPT — `compute_stack.py`
  bootstrapped the live EC2 and documents the CW-agent metric config the
  alarms script binds to.

## Risk register (post-2026-07-01 state)

| Sev | Risk | State |
| --- | --- | --- |
| HIGH | No uptime alerting | **Closed 2026-07-02** — monitors live on `/` + `/api/v1/health`; alert path proven by the first (405/HEAD) incident; server now answers HEAD |
| HIGH | DB backup never restore-tested | Mitigated by `db-backup.yml` once secrets set → item #2 |
| HIGH | On-box build → OOM | Guardrails procedural (`--no-build` in unit + script); structural fix impossible while `build:` blocks serve local dev |
| MED | Instance loss MTTR | Mitigated: verbatim `deploy/mindmarket.service` (captured 2026-07-01) + `instance-rebuild.md` |
| MED | LE cert ~60-day renewal behind proxy | **Closed 2026-07-02** — Origin CA (15yr) pinned in Caddy |
| MED | Shallow healthchecks (healthy ≠ working) | **Closed 2026-07-17** — `?deep=1` readiness (503 on degraded); point the external monitor at it |
| MED | Solo-owner deploy bus factor | **Closed 2026-07-17** — `deploy-ec2.yml` GH workflow (SSM); owner creates the AWS secrets to activate |
| MED | No CloudWatch alarms | Script ready (`scripts/cloudwatch-alarms.sh`) — owner runs once + confirms SNS email |
| LOW | Caddyfile drift outage | **Closed** — `validate-config` CI job |
| LOW | `latest` tag race | **Closed** — build-images concurrency (serialized) |
| LOW | Log-storm disk fill | **Closed** — json-file caps in compose.split.yml |
| LOW | Dep major-version drift | **Closed** — ceilings in requirements.txt |
| LOW | Caddy silent auto-upgrade | **Closed** — pinned `caddy:2.11-alpine` |
| LOW | Backend sees CF IPs, not clients | Open (snippet above; no consumer today) |
| LOW | Cron workflows auto-disable after 60d inactivity | Documented; mitigated by external monitor (#1) |
| LOW | GHCR sha-tag accumulation | **Closed 2026-07-17** — monthly `ghcr-retention.yml` keeps newest 30/image |
