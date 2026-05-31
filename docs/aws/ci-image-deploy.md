# Off-box image deploys (GHCR) — no more on-box builds

## Why
The EC2 box is a **t3.micro (~916 MB RAM)**. Building the frontend (`next build`)
on it OOM-thrashes the instance and **took the site down on 2026-05-31**. Fix:
build images in **GitHub Actions** (~7 GB runners) → push to **GHCR** → EC2 only
`docker compose pull`s. Zero build load on the box.

- Workflow: `.github/workflows/build-images.yml` (builds `mindmarket-frontend` +
  `mindmarket-backend`, tags `latest` + `<sha>`).
- `compose.split.yml` `frontend`/`backend` services now carry an
  `image: ghcr.io/zhengbrody/mindmarket-<svc>:${MM_IMAGE_TAG:-latest}` so EC2 can
  `pull`. (`build:` is kept only for local dev — never run it on EC2.)

## One-time setup (owner — the agent cannot do these; they're secrets)

1. **GitHub repo Variables** (Settings → Secrets and variables → Actions →
   **Variables** tab) — same values as the EC2 `.env`, all publishable:
   - `NEXT_PUBLIC_API_BASE_URL` = `https://mindmarket.app`
   - `NEXT_PUBLIC_SUPABASE_URL` = `https://<project>.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = `sb_publishable_...`
   ⚠️ Set these **before** the first build, or the frontend bundle bakes empty
   URLs → "Supabase not configured".

2. **EC2 GHCR login** (once, so private images can be pulled):
   ```bash
   echo <PAT_with_read:packages> | docker login ghcr.io -u zhengbrody --password-stdin
   ```
   (Create a classic PAT with `read:packages` at GitHub → Settings → Developer
   settings → Personal access tokens.)

## Build (automatic)
On push to `main` touching `frontend/`, `backend/`, the Dockerfiles, or the
imported root modules — or via **Actions → Build & push images → Run workflow**.
Wait for it green; images land in GHCR under the owner's Packages.

## Deploy on EC2 (NO build — safe on the t3.micro)
```bash
cd ~/PersonalFinancialRiskManagement
git pull --ff-only origin main          # picks up compose/Caddy/code changes
docker compose -f compose.split.yml pull backend frontend
docker compose -f compose.split.yml up -d --no-deps backend frontend
docker image prune -f
docker compose -f compose.split.yml ps  # expect (healthy)
```
To deploy a specific build instead of `latest`:
`MM_IMAGE_TAG=sha-<full-sha> docker compose -f compose.split.yml pull ... && ... up -d ...`

## Guardrails (unchanged)
No `git reset --hard`, no `--remove-orphans` (keeps the legacy `app` container),
never touch `.env` / `secrets.toml` / Supabase secrets / systemd / volumes.
Precheck `free -m` + `df -h /` — but with pull-only deploys, RAM is no longer at
risk from builds.
