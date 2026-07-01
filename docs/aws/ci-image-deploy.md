# Off-box image deploys (GHCR) — no more on-box builds

## Why
The EC2 box is a **t3.micro (~916 MB RAM)**. Building the frontend (`next build`)
on it OOM-thrashes the instance and **took the site down on 2026-05-31**. Fix:
build images in **GitHub Actions** (~7 GB runners) → push to **GHCR** → EC2 only
`docker compose pull`s. Zero build load on the box.

- Workflow: `.github/workflows/build-images.yml` (builds `mindmarket-frontend` +
  `mindmarket-backend`, tags `latest` + `sha-<full commit sha>`).
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

One command (encodes every guardrail below):
```bash
cd ~/PersonalFinancialRiskManagement
./scripts/deploy-ec2.sh                 # deploy :latest
```
Or by hand:
```bash
cd ~/PersonalFinancialRiskManagement
git pull --ff-only origin main          # picks up compose/Caddy/code changes
docker compose -f compose.split.yml pull backend frontend
docker compose -f compose.split.yml up -d --no-deps --no-build backend frontend
docker image prune -af                  # -a: also unused non-dangling (disk is tight)
docker compose -f compose.split.yml ps  # expect (healthy)
```

## Rollback (pinned sha)

Every build pushes `latest` + `sha-<full-40-char-commit-sha>`. To roll back
(or deploy a specific build), run the same sequence pinned to that tag:
```bash
./scripts/deploy-ec2.sh sha-<full-sha>
# or by hand — export ONCE so pull AND up use the same tag:
export MM_IMAGE_TAG=sha-<full-sha>
docker compose -f compose.split.yml pull backend frontend
docker compose -f compose.split.yml up -d --no-deps --no-build backend frontend
```
Find shas via `git log --oneline` (tag = `sha-` + full commit sha) or the GHCR
package pages. Note `MM_IMAGE_TAG` pins BOTH images to one commit's build —
there is no per-service pin.

⚠️ An image pin rolls back CODE only: the deploy still fast-forwards the repo
(compose/Caddyfile/assets) to origin/main, and the boot unit resets to
origin/main regardless. A CONFIG regression (bad compose or Caddyfile commit)
therefore needs a `git revert` on main — that's also what keeps the next
reboot safe.

## Guardrails
- **Never `--remove-orphans`** — backend/frontend (this file) and caddy
  (`compose.aws.yml`) share one compose project; each file sees the other's
  services as orphans, so the flag would delete the live caddy container.
- **Never a bare `up` without `--no-build`** — if an image is missing locally
  (e.g. after an aggressive prune), compose would BUILD it on the box → OOM.
- Never touch `.env` / Supabase secrets / volumes. Precheck `free -m` +
  `df -h /` (the deploy script does this for you).

## Boot behavior (systemd)

`mindmarket.service` (on-box; reference copy at `deploy/mindmarket.service`)
runs on boot: `git reset --hard origin/main` → pull-only `--no-build` up of
backend+frontend (compose.split.yml) then caddy (compose.aws.yml). Reboots are
safe and self-healing — but note `reset --hard` means a bad COMMITTED
Caddyfile becomes a boot-time outage, which is why ci.yml's `validate-config`
job validates it on every push. If the instance itself is lost, see
`docs/aws/instance-rebuild.md`.

## Ops notes
- Disk is chronically tight (~80%): `docker image prune -af` after every
  deploy; check `df -h /` before.
- On the next SSH, verify swap persistence once: `swapon --show && grep
  swapfile /etc/fstab` (the 1 GB swapfile was added mid-incident; if the
  fstab line is missing, a reboot returns the box to bare 916 MB — the OOM
  precondition).
