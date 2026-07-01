# Split-Stack Deployment (Caddy + Next.js + FastAPI)

> **HISTORICAL — kept for reference.** This is the original 2026-05 split-stack
> migration design. Production was cut over to the Next.js + FastAPI split stack
> in 2026-05, and the legacy **Streamlit tier was fully retired on 2026-06-23**
> (UI code, the backend's dependency on Streamlit, and the running `/legacy`
> container were all removed). The design-time "Not cut over" status below is no
> longer accurate — the current deploy/rollback runbook is
> `docs/aws/ci-image-deploy.md` (instance recovery: `docs/aws/instance-rebuild.md`).
>
> **2026-07-01:** `Caddyfile.split` and the `compose.split.yml` `caddy` service
> were removed (the live, CI-validated `Caddyfile` + `compose.aws.yml` are
> canonical). Commands below referencing them — including the §7 rollback and
> any `docker compose -f compose.split.yml exec caddy …` — are preserved
> verbatim as history and are **no longer runnable**; today's caddy reload is
> `docker compose -f compose.aws.yml exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`,
> and "roll back to Streamlit" is impossible (the container and image are gone).

> **Status:** Design + artifacts ready. **Not cut over to production.**
> Production cutover requires explicit operator approval ("approve
> production cutover"). See §6.
>
> **Owner:** zhengbrody
> **Last updated:** 2026-05-29 (Phase 5 prep)

## Why this exists

Phases 1–4 added a FastAPI backend (`backend/`) and a Next.js frontend
(`frontend/`) alongside the existing Streamlit production at
`mindmarket.app`. CI is green; nothing is deployed. This doc + the
artifacts beside it set up the **safest** path to put the new stack
behind the same Caddy without ever forcing live users off Streamlit
before we say so.

The non-negotiables:

* `mindmarket.app/` must keep serving Streamlit until explicit cutover.
* No secrets in the frontend bundle. `NEXT_PUBLIC_*` only.
* MCP server is **not** behind Caddy. It is stdio-only.
* Rollback completes in < 30 s after SSH login.
* Existing prod files (`compose.aws.yml`, `Caddyfile`, root `Dockerfile`)
  are **not** modified in this round — split-stack lives in its own
  set of files so the legacy path stays trivially recoverable.

## Target topology (after cutover — not today)

```
internet ─┐
          ▼
        Caddy :80/:443  ────┬─► /api/v1/*  ─►  backend  :8000   (FastAPI)
                            │
                            ├─► /legacy/*  ─►  streamlit :8501   (current prod)
                            │
                            └─► /          ─►  frontend :3000   (Next.js prod server)
```

MCP server runs **outside** the compose graph (`python -m backend.mcp_server`),
stdio only. Not internet-reachable.

## Current state (no change to prod)

```
internet → Caddy :80/:443 → streamlit :8501 (compose.aws.yml, Caddyfile)
```

`mindmarket.app/` is Streamlit. No backend or frontend container exists
on EC2 yet.

## Service names + internal ports

| Service | Internal port | Health check |
|---------|---------------|--------------|
| `caddy` | 80, 443 | n/a (entrypoint) |
| `streamlit` | 8501 | `GET /_stcore/health` |
| `backend` | 8000 | `GET /api/v1/health` |
| `frontend` | 3000 | `GET /` |

`streamlit` is renamed (was `app` in `compose.aws.yml`) **only inside**
`compose.split.yml`. The live `compose.aws.yml` keeps the `app` name.

## Files added in this round (all additive)

* `backend/Dockerfile` — FastAPI production image
* `frontend/Dockerfile` — multi-stage Next.js production image
* `frontend/.dockerignore`, `backend/.dockerignore`
* `compose.split.yml` — split-stack compose, layered on top of (not
  replacing) `compose.aws.yml`
* `Caddyfile.split` — preview-safe routing variant
* `docs/aws/split-stack-deployment.md` (this file)

Files **not** touched: `Dockerfile`, `compose.aws.yml`, `Caddyfile`,
`infra/scripts/*`, `.streamlit/secrets.toml`, systemd unit.

## Image design

### `backend/Dockerfile`
- Base: `python:3.12-slim` (backend uses 3.12 in CI; existing Streamlit
  image is on 3.10, kept separate so we don't disturb it).
- `WORKDIR /app`, copy repo root (`engine/`, `domain/`, `libs/`,
  `data_provider.py`, etc.) so `backend/app/api/v1/risk.py`'s
  `from engine.quant import …` resolves at import time.
- Install root `requirements.txt` + `backend/requirements-backend.txt`.
- `EXPOSE 8000`.
- `CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- Healthcheck via `python -c "urllib.request.urlopen('http://localhost:8000/api/v1/health')"`
  (same pattern as the Streamlit image — no `curl` needed).

### `frontend/Dockerfile`
- Two-stage build:
  1. `node:20-alpine` → `npm ci && npm run build`
  2. Slim runtime that copies `.next/standalone` + `.next/static` +
     `public/`, runs `node server.js` (Next.js standalone output mode).
- `EXPOSE 3000`.
- Standalone mode keeps the production image around 200 MB instead
  of dragging full `node_modules` into prod.
- Build-time `NEXT_PUBLIC_*` injection via `--build-arg` so the
  compiled bundle has the production API origin baked in.

### Why two Python images instead of one merged container
The Streamlit production image runs on Python 3.10 with the current
`requirements.txt`. The backend uses Python 3.12 features
(`dict[str, Any]`, etc.) and lighter deps. Keeping them as separate
images is the minimum change — nothing in the legacy image surface
moves.

## Routing strategy (no live cutover today)

The repo ships **two** Caddy configurations. The live one is
unchanged. The split one is for staging / preview only until you
approve cutover.

### Live (`Caddyfile`, unchanged)
- `/` → `app:8501` (Streamlit)

### Preview / final (`Caddyfile.split`)
- `/api/v1/*` → `backend:8000`
- `/legacy/*` → `streamlit:8501` (strips `/legacy` prefix on its way in)
- `/` → `frontend:3000`
- All SEO/brand handlers preserved verbatim
- TLS issuance identical (same `SITE_HOST` env var)

### Why a separate file, not a feature flag
Caddy supports neither environment-driven `handle` blocks nor includes
cleanly. The least-clever path is a parallel file. Cutover swaps
which file Caddy mounts; rollback swaps back. One-line change either
direction.

## Secrets posture

| Variable | Lives in | Visible to |
|----------|----------|------------|
| `SUPABASE_JWT_SECRET` | `backend` env | backend container only; required only for legacy HS256 Supabase JWTs |
| `SUPABASE_SERVICE_KEY` | `streamlit` env (existing) | streamlit only |
| `STRIPE_SECRET_KEY` | `streamlit` env (existing) | streamlit only |
| `ANTHROPIC_API_KEY` | `streamlit` + (later) `backend` env | server only |
| `NEXT_PUBLIC_API_BASE_URL` | `frontend` build arg | **baked into JS bundle (public by design)** |
| `NEXT_PUBLIC_SUPABASE_URL` | `frontend` build arg | **bundle (public)** |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `frontend` build arg | **bundle (public — RLS enforces tenancy)** |

The frontend image only receives `NEXT_PUBLIC_*` at build time. The
backend image only receives server-side secrets at runtime through
`compose.split.yml` env mapping. The two never overlap.

## MCP server is not deployed via Caddy

The MCP server (`backend/mcp_server/`) is stdio-only. It is **not**
in `compose.split.yml`, **not** routed through Caddy, **not** behind
any port. Operators run it manually:

```bash
# From the repo root on whichever host is acting as the LLM client
python -m backend.mcp_server
```

A container target may be added later, **opt-in only** (disabled by
default), once we have a concrete consumer.

---

## Local Docker validation results (already executed, 2026-05-29)

Reference for the EC2 plan below — anything that passed locally is
expected to pass on EC2.

| Check | Result |
|---|---|
| `compose -f compose.split.yml config` | parses cleanly |
| `caddy validate Caddyfile.split` | Valid configuration |
| Build backend + frontend images | OK |
| Up: all 4 services (`streamlit`, `backend`, `frontend`, `caddy`) | all `healthy` |
| `GET /api/v1/health` | 200, full envelope |
| `GET /api/v1/macro/series?series=DFF,UNRATE` | 200, real FRED values |
| `GET /api/v1/macro/yield_curve` | local hit timed out (Mac Docker → Treasury.gov); error envelope rendered cleanly; EC2 path is shorter |
| `GET /legacy/` | 200, Streamlit body |
| `GET /` | 200, Next.js page with correct title + MacroSnapshot + dark class |
| `GET /robots.txt`, `/favicon.ico` | SEO + brand handlers preserved |
| CORS preflight from disallowed origin | 400, no `allow-origin` header (strict prod allow-list working) |
| Idle memory total | ~270 MB (fits t3.micro) |
| Tear-down + Caddyfile restore | clean |

## §5 — EC2 staging deployment plan

> **Read-only.** Do not execute until operator says go.

Pre-conditions:
- SSH key `~/.ssh/mindmarket_aws` on operator machine
- EC2 instance up (`infra/scripts/deploy-phase-1.sh` already ran at
  least once for the legacy stack)
- Operator has approved running the staging steps

```bash
# === 1. SSH in ===
EIP=$(jq -r '.["MindMarket-Compute"].PublicIp' infra/cdk.out/outputs.json)
ssh -i ~/.ssh/mindmarket_aws ec2-user@${EIP}

# === 2. Back up live config (cheap insurance) ===
cd ~/PersonalFinancialRiskManagement
sudo cp compose.aws.yml         compose.aws.yml.bak.$(date +%Y%m%d-%H%M%S)
sudo cp Caddyfile               Caddyfile.bak.$(date +%Y%m%d-%H%M%S)
ls -la compose.aws.yml.bak.* Caddyfile.bak.*

# === 3. Fetch the new commits ===
git fetch origin
git log --oneline HEAD..origin/main          # what's coming
git reset --hard origin/main                 # match local

# === 4. Build the new images WITHOUT touching live containers ===
# Note: this uses the SPLIT compose file, not the live one.
docker compose -f compose.split.yml build backend frontend

# === 5. Start backend + frontend on private network (no Caddy yet) ===
# The legacy `app` (compose.aws.yml) keeps serving public traffic.
docker compose -f compose.split.yml up -d backend frontend

# === 6. Verify backend health from inside EC2 ===
docker compose -f compose.split.yml exec backend \
    python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read())"

# === 7. Verify macro endpoint (real upstream — FRED + Treasury) ===
docker compose -f compose.split.yml exec backend \
    python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/v1/macro/yield_curve').read()[:200])"

# === 8. Verify frontend serves on internal port ===
docker compose -f compose.split.yml exec frontend \
    wget -qO- http://localhost:3000/ | head -20

# === 9. CONFIRM Streamlit production is still serving ===
curl -fsSI https://mindmarket.app/ | head -3
curl -fsS  https://mindmarket.app/ | grep -i "streamlit\|MindMarket" | head -5

# === 10. Collect logs (no Caddy change yet) ===
docker compose -f compose.split.yml logs --tail=50 backend
docker compose -f compose.split.yml logs --tail=50 frontend
sudo journalctl -u mindmarket.service --since "10 minutes ago" --no-pager | tail -20
```

After step 10, **stop**. Report status back to operator. Do not touch
Caddy until cutover is approved.

---

## §6 — Production cutover plan

> **Trigger:** operator says **"approve production cutover"**.
> Until that exact string is said, the cutover steps below are not
> to be executed. Steps 1–10 above (§5) may run beforehand.

Cutover changes one symlink and reloads Caddy. The container set
already running from §5 stays running.

```bash
# === A. SSH in ===
ssh -i ~/.ssh/mindmarket_aws ec2-user@${EIP}
cd ~/PersonalFinancialRiskManagement

# === B. Re-verify staging is healthy before any change ===
docker compose -f compose.split.yml ps
docker compose -f compose.split.yml exec backend \
    python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read())"

# === C. Swap Caddy config (one atomic line) ===
# Save the current state so rollback restores byte-for-byte.
sudo cp Caddyfile Caddyfile.live.bak

# Point Caddy at the split config.
sudo cp Caddyfile.split Caddyfile

# === D. Reload Caddy WITHOUT restart (keeps existing TLS sessions) ===
docker compose -f compose.split.yml exec caddy \
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

# === E. Smoke-test from outside ===
# Run from operator laptop, not EC2 (proves DNS / public path).
curl -sI https://mindmarket.app/ | head -3
curl -s  https://mindmarket.app/api/v1/health | jq .
curl -s  https://mindmarket.app/api/v1/macro/yield_curve | jq '.data.as_of, (.data.points|length)'
curl -sI https://mindmarket.app/legacy/ | head -3
```

Expected:
- `https://mindmarket.app/` → Next.js (look for `MindMarket — Portfolio Risk` `<title>` from `app/layout.tsx`).
- `/api/v1/health` → envelope `{"data":{"status":"ok",…}}`.
- `/api/v1/macro/yield_curve` → real `as_of` ISO date + > 0 points.
- `/legacy/` → Streamlit (`_stcore` references).

Then **monitor for 10 minutes** before declaring cutover complete:

```bash
# Watch backend + Caddy + Streamlit logs in parallel
docker compose -f compose.split.yml logs -f --tail=20 backend frontend caddy streamlit
```

Tear-down indicator (anything below = abort + rollback):
- Sustained 5xx > 1% on Caddy
- Backend log shows repeated tracebacks
- Streamlit log shows reduced traffic to zero (would mean `/legacy`
  routing broke and a legacy bookmark user lost access)
- Frontend bundle 404 on a static asset

---

## §7 — Rollback (≤ 30 s after SSH)

Whenever rollback is needed, run **exactly** these 4 commands. They
restore the Caddyfile to the pre-cutover byte sequence and reload.

```bash
cd ~/PersonalFinancialRiskManagement
sudo cp Caddyfile.live.bak Caddyfile
docker compose -f compose.split.yml exec caddy \
    caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
curl -sI https://mindmarket.app/ | head -3            # expect Streamlit again
```

**Why this is enough:**
- Backend + frontend containers can stay running. They take no public
  traffic when `/` is back on Streamlit; they idle at zero RPS.
- Streamlit container was never stopped or restarted.
- TLS sessions reload in place (no certificate re-issuance).
- DNS does not change.

If a deeper rollback is needed (e.g. backend container leaking memory
into the docker network), stop them:

```bash
docker compose -f compose.split.yml stop backend frontend
# Streamlit + Caddy untouched.
```

If the Caddy reload itself fails (syntax error in the backup file —
shouldn't happen, but planning for it), restart the full Caddy
container, which re-reads `/etc/caddy/Caddyfile`:

```bash
docker compose -f compose.split.yml restart caddy
```

Last-resort nuclear option (operator approval only):

```bash
docker compose -f compose.aws.yml up -d --force-recreate caddy app
# Use ONLY if compose.split.yml is itself broken; rebuilds the legacy
# stack from compose.aws.yml verbatim.
```

---

## Open items / not in this round

- Sentry wiring for backend + frontend (Phase 5b).
- Cloudflare in front of Caddy (Phase 5c).
- Splitting `secrets.toml` into a backend-only env file (Phase 5 follow-up
  once Streamlit retires).
- Container target for MCP server. Default disabled; opt-in only.
